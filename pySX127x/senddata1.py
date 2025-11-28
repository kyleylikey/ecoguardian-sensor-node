import sys
import struct
import time
import random
import board
import busio
import serial
import subprocess
import os
import adafruit_dht
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import math
import json
from LoRaRF import SX127x
from Crypto.Cipher import AES
from Crypto.Hash import CMAC


# --- ABP Credentials (PASTE YOUR KEYS FROM CHIRPSTACK HERE) ---
DevAddr = bytes.fromhex("0060276b")
NwkSKey = bytes.fromhex("4dad53a60342ea5b3b0d6a1ca5e80cec")
AppSKey = bytes.fromhex("249a97f57042ec468d5b5c45302a1af4")
# Frame counter for LoRaWAN
frame_counter = 0
# loop counter for periodic actions (e.g. send every N seconds)
loop_count = 0

# --- Radio Setup ---
lora = SX127x()
lora.begin()
TX_FREQ = 916600000  # We'll send on the first channel
TX_SF = 10           # We use SF10 because it worked for your Join Request
TX_BW = 125000       # 125kHz bandwidth
LORA_PACKET_INTERVAL = 5  # seconds between LoRa packet transmissions (shortened for testing)

#--Audio setup--
AUDIO_DEVICE = "default"
AUDIO_DURATION = 5  # seconds
RECORDINGS_DIR = "../recordings"

SENSOR_READ_INTERVAL = 5  # seconds between sensor readings

# DHT22 Configuration
DHT_PIN = board.D4
TEMP_WARNING = 35.0
TEMP_DANGER = 40.0
HUMIDITY_WARNING = 30.0
HUMIDITY_DANGER = 20.0

# MQ-7 Gas Sensor Configuration
VCC = 5.0
RL = 10.0
R0 = 70.278  # IMPORTANT: Calibrated Value. Please recalibrate this value once in a while using the MQ9 Calibrate Script.

# GPS Configuration
GPS_PORT = "/dev/ttyS0"
GPS_BAUDRATE = 9600

print("\n" + "=" * 60)
print("LoRaWAN ABP Sender - AS923-3")
print(f"  DevAddr: {DevAddr.hex()}")
print(f"  TX Freq: {TX_FREQ/1e6} MHz (SF{TX_SF})")
print("=" * 60)
print("Press Ctrl+C to stop.\n")

# --- Set radio parameters for TX ---
lora.setSyncWord(0x34)  # LoRaWAN Public
lora.setTxPower(20, 1)
lora.setLoRaModulation(TX_SF, TX_BW, 5, False)
lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False) # invertIQ=False for uplink

# --- AES helpers ---
def aes128_encrypt(key, plaintext):
    """ Encrypts a 16-byte block using AES128-ECB """
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)

def calculate_mic(key, msg):
    """ Calculates the LoRaWAN MIC (first 4 bytes of CMAC) """
    cmac = CMAC.new(key, ciphermod=AES)
    cmac.update(msg)
    return cmac.digest()[:4]

def encrypt_payload(key, devaddr, fcnt, payload):
    """ Encrypts a payload using AES128-CTR """
    encrypted = bytearray()
    block_index = 1
    payload_len = len(payload)

    for i in range(0, payload_len, 16):
        a_block = bytearray(16)
        a_block[0] = 0x01
        a_block[5] = 0x00  # 0x00 = Uplink
        a_block[6:10] = devaddr[::-1]  # Little-endian DevAddr
        a_block[10:14] = struct.pack('<L', fcnt)  # Little-endian 32-bit FCnt
        a_block[15] = block_index & 0xFF  # Set the block index

        s_block = aes128_encrypt(key, a_block)
        chunk = payload[i : min(i + 16, payload_len)]

        for j in range(len(chunk)):
            encrypted.append(chunk[j] ^ s_block[j])

        block_index += 1

    return bytes(encrypted)

# ===== SENSOR INITIALIZATION =====
print("Initializing sensors...")

# DHT22 Temperature & Humidity
dht_device = adafruit_dht.DHT22(DHT_PIN, use_pulseio=False)

# ADS1115 ADC for MQ-9 Gas Sensor
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)
gas_channel = AnalogIn(ads, 0)

# GPS Serial
gps_serial = None
try:
    gps_serial = serial.Serial(GPS_PORT, baudrate=GPS_BAUDRATE, timeout=0.1)
    print("[GPS] Serial port opened successfully")
except Exception as e:
    print(f"[GPS] ERROR: Could not open serial port: {e}")
    gps_serial = None

# Audio recording directory
if not os.path.exists(RECORDINGS_DIR):
    os.makedirs(RECORDINGS_DIR)

print("=" * 60)
print("Forest Fire Detection System - Unified Sensor Monitor")
print("=" * 60)
print(f"Sensor readings every: {SENSOR_READ_INTERVAL}s")
print(f"LoRa packet preparation every: {LORA_PACKET_INTERVAL}s")
print("=" * 60)

# ===== HELPER FUNCTIONS =====

# --- Temperature & Humidity ---
def read_temp_humidity():
    """Read DHT22 temperature and humidity with fire risk assessment."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            temperature = dht_device.temperature
            humidity = dht_device.humidity
            
            if temperature is not None and humidity is not None:
                temp_status = "Normal"
                if temperature >= TEMP_DANGER:
                    temp_status = "DANGER"
                elif temperature >= TEMP_WARNING:
                    temp_status = "WARNING"
                
                humidity_status = "Normal"
                if humidity <= HUMIDITY_DANGER:
                    humidity_status = "DANGER"
                elif humidity <= HUMIDITY_WARNING:
                    humidity_status = "WARNING"
                
                return {
                    "temperature": round(temperature, 1),
                    "humidity": round(humidity, 1),
                    "temp_status": temp_status,
                    "humidity_status": humidity_status
                }
            else:
                # Retry on next attempt
                time.sleep(0.5)
                continue
                
        except RuntimeError as error:
            if "Checksum" in str(error):
                # Checksum error - retry
                time.sleep(0.5)
                if attempt < max_retries - 1:
                    continue
                else:
                    print(f"[DHT22] Checksum error after {max_retries} attempts: {error.args[0]}")
                    return None
            else:
                print(f"[DHT22] Reading error: {error.args[0]}")
                return None
        except Exception as error:
            print(f"[DHT22] Unexpected error: {error}")
            return None
    
    return None

# --- Gas Sensor (MQ-7) ---
def get_resistance(voltage):
    """Calculate sensor resistance from voltage."""
    if voltage <= 0:
        return 999999
    return RL * (VCC - voltage) / voltage

def get_ppm_co(Rs, R0):
    """Calculate CO concentration in ppm."""
    ratio = Rs / R0
    a_co = 10.0
    b_co = -1.8
    return a_co * pow(ratio, b_co)

def read_gas_sensor():
    """Read MQ-7 gas sensor and calculate CO concentration."""
    try:
        voltage = gas_channel.voltage
        Rs = get_resistance(voltage)
        ppm = get_ppm_co(Rs, R0)
        
        return {
            "voltage": round(voltage, 3),
            "resistance": round(Rs, 2),
            "co_ppm": round(ppm, 1)
        }
    except Exception as error:
        print(f"[GAS] Error reading sensor: {error}")
        return None

# --- GPS ---
def convert_to_decimal(coord, direction):
    """Convert NMEA coordinates to decimal degrees."""
    if not coord or coord == "0":
        return None
    
    if direction in ["N", "S"]:  # latitude
        degrees = int(coord[:2])
        minutes = float(coord[2:])
    else:  # longitude
        degrees = int(coord[:3])
        minutes = float(coord[3:])
    
    decimal = degrees + minutes / 60
    if direction in ["S", "W"]:
        decimal = -decimal
    
    return round(decimal, 6)

def parse_gngga(sentence):
    """Parse GNGGA NMEA sentence."""
    parts = sentence.split(",")
    if len(parts) < 15:
        return None
    
    # Only return valid GPS fix (fix quality must not be "0")
    fix_quality = parts[6]
    if fix_quality == "0":
        # No fix yet - return None instead of invalid data
        return None
    
    return {
        "time": parts[1][:6] if parts[1] else "N/A",
        "latitude": convert_to_decimal(parts[2], parts[3]),
        "longitude": convert_to_decimal(parts[4], parts[5]),
        "fix": True,  # If we got here, fix is valid
        "satellites": int(parts[7]) if parts[7] else 0,
        "altitude": float(parts[9]) if parts[9] else None
    }

def read_gps():
    """Read fresh GPS data from serial port."""
    if gps_serial is None:
        return None
    
    try:
        # Flush stale data
        gps_serial.reset_input_buffer()
        
        # Read up to 50 lines looking for fresh GNGGA sentence
        for attempt in range(5):
            line = gps_serial.readline().decode(errors="ignore").strip()
            if line.startswith("$GNGGA"):
                gps_data = parse_gngga(line)
                if gps_data:
                    return gps_data
        
        return None
    except Exception as error:
        print(f"[GPS] Error reading data: {error}")
        return None

# --- Audio Classification ---
def classify_audio():
    """
    Record audio and classify fire risk level.
    TODO: Integrate your audio classification model here.
    
    For now, returns a placeholder. Once model is ready:
    1. Record audio clip
    2. Pass to classification model
    3. Return risk level: "low-risk", "medium-risk", or "high-risk"
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(RECORDINGS_DIR, f"clip_{timestamp}.wav")
    
    try:
        # Step 1: Record audio
        command = [
            "arecord",
            "-D", AUDIO_DEVICE,
            "-f", "S32_LE",
            "-r", "16000",
            "-c", "1",
            "-d", str(AUDIO_DURATION),
            filepath
        ]
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=AUDIO_DURATION + 5
        )
        
        if result.returncode != 0:
            print(f"[AUDIO] Recording failed: {result.stderr.strip()}")
            return {
                "risk_level": "unknown",
                "confidence": None,
                "recorded": False
            }
        
        # Step 2: Classify audio (TODO: integrate model here)
        # Example of what the integration might look like:
        # audio_data = load_audio(filepath)
        # prediction = model.predict(audio_data)
        # risk_level = prediction["class"]  # "low-risk", "medium-risk", "high-risk"
        # confidence = prediction["confidence"]
        
        # For now, return placeholder
        print(f"[AUDIO] Recording saved: {filepath}")
        print("[AUDIO] ⚠️  Classification model not yet integrated - returning placeholder")
        
        return {
            "risk_level": "low-risk",  # TODO: Replace with actual model output
            "confidence": None,  # TODO: Add confidence score when model is ready
            "recorded": True,
            "filepath": filepath
        }
        
    except Exception as error:
        print(f"[AUDIO] Error: {error}")
        return {
            "risk_level": "unknown",
            "confidence": None,
            "recorded": False
        }

# --- Packet Preparation ---
def prepare_lora_packet_json(data):
    """Serialize sensor packet to compact JSON and send as FRMPayload (AppSKey encrypt)."""
    th = data.get("temp_humid") or {}
    gas = data.get("gas") or {}
    gps = data.get("gps") or {}

    # Create packet in backend's expected format
    packet = {
        "type": "reading",
        "nodeID": 1,
        "temp": th.get("temperature"),
        "humidity": th.get("humidity"),
        "co_ppm": gas.get("co_ppm"),
        "latitude": gps.get("latitude"),
        "longitude": gps.get("longitude"),
        "altitude": gps.get("altitude"),
        "gps_fix": bool(gps.get("fix", False))
    }

    json_bytes = json.dumps(packet, separators=(',', ':')).encode('utf-8')
    if len(json_bytes) > 200:
        print(f"[LoRa][WARN] JSON payload length {len(json_bytes)} bytes — may exceed max FRMPayload for your DR.")
    print("\n📡 LoRa JSON Packet Ready:", packet)
    print(f"   JSON bytes len: {len(json_bytes)} hex: {json_bytes.hex()}")

    # Verify payload changed
    if hasattr(prepare_lora_packet_json, '_last_payload'):
        if prepare_lora_packet_json._last_payload == json_bytes:
            print("[LoRa][WARN] ⚠️  Payload appears identical to last packet!")
    prepare_lora_packet_json._last_payload = json_bytes

    try:
        send_data_packet(json_bytes)
    except Exception as e:
        print(f"[LoRa] Error sending JSON packet: {e}")

    return packet

# --- Main Send Function ---
def send_data_packet(payload):
    global frame_counter

    print(f"--- Sending ABP Packet (FCnt={frame_counter}) ---")
    lora.setFrequency(TX_FREQ)

    mhdr = 0x40
    fctrl = 0x00
    fcnt_bytes_16 = struct.pack('<H', frame_counter)
    fhdr = DevAddr[::-1] + bytes([fctrl]) + fcnt_bytes_16
    fport = 1

    encrypted_payload = encrypt_payload(AppSKey, DevAddr, frame_counter, payload)
    print(f"  Encrypted payload len: {len(encrypted_payload)}")
    print(f"  Encrypted payload (hex): {encrypted_payload.hex()}")

    mac_payload = fhdr + bytes([fport]) + encrypted_payload

    b0_block = bytearray(16)
    b0_block[0] = 0x49
    b0_block[5] = 0x00
    b0_block[6:10] = DevAddr[::-1]
    b0_block[10:14] = struct.pack('<L', frame_counter)
    b0_block[15] = len(bytes([mhdr]) + mac_payload)

    msg_for_mic = b0_block + bytes([mhdr]) + mac_payload
    mic = calculate_mic(NwkSKey, msg_for_mic)

    phy_payload = bytes([mhdr]) + mac_payload + mic

    print(f"  Payload: {payload.hex()}")
    print(f"  PHY Pkt: {phy_payload.hex()}")

    lora.beginPacket()
    print(f"  PHY payload len: {len(phy_payload)} type: {type(phy_payload)}")
    
    sent_form = None
    try:
        data_to_send = list(phy_payload)
        lora.write(data_to_send, len(data_to_send))
        sent_form = 'list'
    except Exception as e:
        print(f"[LoRa] write with list failed: {e}")
        try:
            data_to_send = bytearray(phy_payload)
            lora.write(data_to_send, len(data_to_send))
            sent_form = 'bytearray'
        except Exception as e2:
            print(f"[LoRa] write with bytearray failed: {e2}")
            try:
                lora.write(phy_payload)
                sent_form = 'bytes'
            except Exception as e3:
                print(f"[LoRa] final write attempt failed: {e3}")
                raise

    lora.endPacket()
    lora.wait()
    print(f"  lora.write used: {sent_form}")
    print("→ Packet SENT")

    frame_counter += 1

# ===== DISPLAY FUNCTION =====
def display_sensor_data(data):
    """Display all sensor readings in console."""
    print("\n" + "=" * 60)
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)
    
    # Temperature & Humidity
    if data.get("temp_humid"):
        th = data["temp_humid"]
        print(f"🌡️  Temperature: {th['temperature']}°C ({th['temp_status']})")
        print(f"💧 Humidity: {th['humidity']}% ({th['humidity_status']})")
    else:
        print("🌡️  Temperature: ERROR")
        print("💧 Humidity: ERROR")
    
    # Gas Sensor
    if data.get("gas"):
        gas = data["gas"]
        print(f"🔥 CO Level: {gas['co_ppm']} ppm | Voltage: {gas['voltage']}V | Rs: {gas['resistance']}kΩ")
        print("   ⚠️  REMINDER: Calibrate R0 in clean air for accurate readings")
    else:
        print("🔥 Gas Sensor: ERROR")
    
    # GPS
    if data.get("gps"):
        gps = data["gps"]
        if gps["fix"]:
            print(f"📍 GPS: {gps['latitude']}, {gps['longitude']} | Alt: {gps['altitude']}m")
            print(f"   Satellites: {gps['satellites']} | Time: {gps['time']}")
        else:
            print(f"📍 GPS: No fix yet (Satellites: {gps['satellites']}) - warming up...")
    else:
        print("📍 GPS: No data (check wiring or wait for warm-up)")
    
    # Audio Classification (not sent in readings, TODO: send only on risk detection)
    if data.get("audio"):
        audio = data["audio"]
        risk_level = audio.get("risk_level", "unknown").upper()
        if audio["recorded"]:
            print(f"🎤 Audio: {risk_level} (not sent in reading packet)")
        else:
            print(f"🎤 Audio: Recording failed - {risk_level}")
    
    print("=" * 60)

# ===== MAIN LOOP =====
if __name__ == "__main__":
    try:
        print("\n🚀 Starting sensor monitoring loop...")
        print("   Press Ctrl+C to stop\n")
        
        if gps_serial:
            print("⏳ GPS warming up... (this may take 30-60 seconds outdoors)")
            time.sleep(10)
        
        last_lora_send = time.time()
        
        while True:
            current_time = time.time()
            
            # Read all sensors FRESH every cycle
            sensor_data = {
                "temp_humid": read_temp_humidity(),
                "gas": read_gas_sensor(),
                "gps": read_gps(),
                "audio": classify_audio()
            }
            
            # Display in console
            display_sensor_data(sensor_data)
            
            # Send LoRa packet on timer (not counter-based)
            if current_time - last_lora_send >= LORA_PACKET_INTERVAL:
                prepare_lora_packet_json(sensor_data)
                last_lora_send = current_time
            
            # Wait before next sensor read
            time.sleep(SENSOR_READ_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped by user.")
        if gps_serial:
            gps_serial.close()
        dht_device.exit()
        print("✅ Cleanup complete. Goodbye!")
