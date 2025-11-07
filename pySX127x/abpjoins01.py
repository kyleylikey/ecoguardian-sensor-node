import sys
import struct
import time
import random
import time
import board
import busio
import serial
import subprocess
import os
import adafruit_dht
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import math
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
LORA_PACKET_INTERVAL = 30  # seconds between LoRa packet transmissions

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
R0 = 489.2278  # IMPORTANT: Calibrated Value. Please recalibrate this value once in a while using the MQ9 Calibrate Script.

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
lora.setTxPower(14, 1)
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

    # Loop through the payload in 16-byte chunks
    for i in range(0, payload_len, 16):
        # 1. Create the A-block (the counter block)
        a_block = bytearray(16)
        a_block[0] = 0x01
        a_block[5] = 0x00  # 0x00 = Uplink
        a_block[6:10] = devaddr[::-1]  # Little-endian DevAddr
        a_block[10:14] = struct.pack('<L', fcnt)  # Little-endian 32-bit FCnt
        a_block[15] = block_index & 0xFF  # Set the block index

        # 2. Encrypt A-block to get S-block (keystream)
        s_block = aes128_encrypt(key, a_block)

        # 3. Get the current 16-byte chunk of the payload
        chunk = payload[i : min(i + 16, payload_len)]

        # 4. XOR the chunk with the S-block
        for j in range(len(chunk)):
            encrypted.append(chunk[j] ^ s_block[j])

        # 5. Increment the block index for the next loop
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
try:
    gps_serial = serial.Serial(GPS_PORT, baudrate=GPS_BAUDRATE, timeout=1)
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
    try:
        temperature = dht_device.temperature
        humidity = dht_device.humidity
        
        if temperature is not None and humidity is not None:
            # Assess fire risk
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
            return None
    except RuntimeError as error:
        print(f"[DHT22] Reading error: {error.args[0]}")
        return None
    except Exception as error:
        print(f"[DHT22] Unexpected error: {error}")
        return None

# --- Gas Sensor (MQ-9) ---
def get_resistance(voltage):
    """Calculate sensor resistance from voltage."""
    if voltage <= 0:
        return 999999
    return RL * (VCC - voltage) / voltage

def get_ppm_co(Rs, R0):
    """
    Calculate CO concentration in ppm.
    NOTE: This uses an approximate curve. For accurate readings,
    calibrate R0 in clean air and adjust the curve coefficients
    based on the MQ-9 datasheet for your specific conditions.
    """
    ratio = Rs / R0
    a = 100.0
    b = -1.5
    return a * pow(ratio, b)

def read_gas_sensor():
    """Read MQ-9 gas sensor and calculate CO concentration."""
    # REMINDER: CALIBRATE R0 VALUE IN CLEAN AIR BEFORE DEPLOYMENT
    # Run sensor in clean air for 24-48 hours and measure stable Rs value
    # Set R0 to that value for accurate ppm readings
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
    
    return {
        "time": parts[1][:6] if parts[1] else "N/A",  # HHMMSS format
        "latitude": convert_to_decimal(parts[2], parts[3]),
        "longitude": convert_to_decimal(parts[4], parts[5]),
        "fix": parts[6] != "0",
        "satellites": int(parts[7]) if parts[7] else 0,
        "altitude": float(parts[9]) if parts[9] else None
    }

def read_gps():
    """
    Read GPS data from serial port.
    NOTE: GPS needs 30-60 seconds of warm-up time outdoors to acquire fix.
    Returns simplified, parsed data ready for LoRa transmission.
    """
    if gps_serial is None:
        return None
    
    try:
        # Read up to 20 lines looking for GNGGA sentence
        for _ in range(20):
            line = gps_serial.readline().decode(errors="ignore").strip()
            if line.startswith("$GNGGA"):
                gps_data = parse_gngga(line)
                if gps_data:
                    return gps_data
        return None
    except Exception as error:
        print(f"[GPS] Error reading data: {error}")
        return None

# --- Audio (Microphone) ---
def record_audio_clip():
    """Record a short audio clip for analysis."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(RECORDINGS_DIR, f"clip_{timestamp}.wav")
    
    command = [
        "arecord",
        "-D", AUDIO_DEVICE,
        "-f", "S32_LE",
        "-r", "16000",
        "-c", "1",
        "-d", str(AUDIO_DURATION),
        filepath
    ]
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=AUDIO_DURATION + 5
        )
        
        if result.returncode == 0:
            # Get file size as a simple metric
            file_size = os.path.getsize(filepath)
            return {
                "recorded": True,
                "filepath": filepath,
                "size_bytes": file_size
            }
        else:
            print(f"[AUDIO] Recording failed: {result.stderr.strip()}")
            return {"recorded": False}
    except Exception as error:
        print(f"[AUDIO] Error: {error}")
        return {"recorded": False}

def prepare_lora_packet(data):
    """
    Prepare data packet for LoRa transmission.
    Returns a dictionary with all sensor data formatted for transmission.
    """
    # sensor values may be None; use 'or {}' to fall back to an empty dict
    th = data.get("temp_humid") or {}
    gas = data.get("gas") or {}
    gps = data.get("gps") or {}
    audio = data.get("audio") or {}

    packet = {
        "timestamp": time.time(),
        "temp": th.get("temperature"),
        "humidity": th.get("humidity"),
        "co_ppm": gas.get("co_ppm"),
        "latitude": gps.get("latitude"),
        "longitude": gps.get("longitude"),
        "altitude": gps.get("altitude"),
        "gps_fix": bool(gps.get("fix", False)),
        "audio_recorded": bool(audio.get("recorded", False))
    }

    print("\n📡 LoRa Packet Ready:")
    print(f"   {packet}")

    # Encode and send via LoRa
    payload_bytes = encode_payload(packet)
    if not payload_bytes:
        print("[LoRa] Payload encoding failed, skipping send")
        return packet

    try:
        send_data_packet(payload_bytes)
    except Exception as e:
        print(f"[LoRa] Error sending packet: {e}")

    return packet

def encode_payload(packet):
    """
    Encodes the data dictionary into a compact byte string for LoRaWAN.

    Payload Format (19 bytes total):
    - Temp: 2 bytes (signed short, value * 100)
    - Hum:  2 bytes (unsigned short, value * 100)
    - CO:   2 bytes (unsigned short)
    - Lat:  4 bytes (float)
    - Lon:  4 bytes (float)
    - Alt:  4 bytes (float)
    - Fix:  1 byte (unsigned char, 1=True, 0=False)
    """

    # Handle None values from sensors, default to 0
    temp = int((packet.get("temp") or 0) * 100)
    humidity = int((packet.get("humidity") or 0) * 100)
    co_ppm = int(packet.get("co_ppm") or 0)
    lat = float(packet.get("latitude") or 0.0)
    lon = float(packet.get("longitude") or 0.0)
    alt = float(packet.get("altitude") or 0.0)
    gps_fix = int(packet.get("gps_fix") or 0) # 1 for True, 0 for False

    # Format string:
    # < = Little-endian
    # h = signed short (2 bytes)
    # H = unsigned short (2 bytes)
    # f = float (4 bytes)
    # B = unsigned char (1 byte)
    format_string = '<hHHfffB'

    try:
        payload_bytes = struct.pack(format_string,
            temp,
            humidity,
            co_ppm,
            lat,
            lon,
            alt,
            gps_fix
        )
        return payload_bytes
    except Exception as e:
        print(f"Error packing data: {e}")
        return b'' # Return empty bytes on error

# --- Main Send Function ---
def send_data_packet(payload):
    global frame_counter

    print(f"--- Sending ABP Packet (FCnt={frame_counter}) ---")
    lora.setFrequency(TX_FREQ)

    # 1. MHDR (0x40 = Unconfirmed Data Up)
    mhdr = 0x40

    # 2. FHDR (Frame Header)
    fctrl = 0x00  # No ADR, no ACK, FOptsLen=0
    fcnt_bytes_16 = struct.pack('<H', frame_counter)  # 16-bit FCnt, little-endian
    fhdr = DevAddr[::-1] + bytes([fctrl]) + fcnt_bytes_16

    # 3. FPort (e.g., FPort 1)
    fport = 1

    # 4. FRMPayload (Encrypted)
    encrypted_payload = encrypt_payload(AppSKey, DevAddr, frame_counter, payload)
    print(f"  Encrypted payload len: {len(encrypted_payload)}")
    print(f"  Encrypted payload (hex): {encrypted_payload.hex()}")

    # 5. Construct full MAC Payload (for MIC calculation)
    mac_payload = fhdr + bytes([fport]) + encrypted_payload

    # 6. Construct B0 block for MIC calculation
    # B0 = 0x49 | 4x 0x00 | 0x00 (dir=up) | DevAddr | FCnt (32-bit) | 0x00 | Len(Msg)
    b0_block = bytearray(16)
    b0_block[0] = 0x49
    b0_block[5] = 0x00  # 0x00 = Uplink
    b0_block[6:10] = DevAddr[::-1]  # Little-endian
    b0_block[10:14] = struct.pack('<L', frame_counter)  # 32-bit FCnt
    b0_block[15] = len(bytes([mhdr]) + mac_payload)  # Length of MHDR + MACPayload

    msg_for_mic = b0_block + bytes([mhdr]) + mac_payload

    # 7. Calculate MIC
    mic = calculate_mic(NwkSKey, msg_for_mic)

    # 8. Final Packet (PHY Payload = MHDR | MACPayload | MIC)
    phy_payload = bytes([mhdr]) + mac_payload + mic

    print(f"  Payload: {payload.hex()}")
    print(f"  PHY Pkt: {phy_payload.hex()}")

    # 9. Send
    lora.beginPacket()
    # Ensure we send raw bytes/bytearray to the driver (not a Python list) so the
    # radio sees the correct payload bytes.
    try:
        lora.write(phy_payload, len(phy_payload))
    except TypeError:
        # Some drivers expect a bytearray or list; fall back to bytearray
        lora.write(bytearray(phy_payload), len(phy_payload))
    lora.endPacket()
    lora.wait()

    print("→ Packet SENT")

    frame_counter += 1 # Increment for next packet

# ===== MAIN LOOP =====
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
    
    # Audio
    if data.get("audio"):
        audio = data["audio"]
        if audio["recorded"]:
            print(f"🎤 Audio: Recorded {audio['size_bytes']} bytes → {audio['filepath']}")
        else:
            print("🎤 Audio: Recording failed")
    
    print("=" * 60)

# --- Main Execution ---
if __name__ == "__main__":

    try:
        print("\n🚀 Starting sensor monitoring loop...")
        print("   Press Ctrl+C to stop\n")
        
        # Give GPS time to warm up on first run
        if gps_serial:
            print("⏳ GPS warming up... (this may take 30-60 seconds outdoors)")
            time.sleep(10)
        
        while True:
            # Read all sensors
            sensor_data = {
                "temp_humid": read_temp_humidity(),
                "gas": read_gas_sensor(),
                "gps": read_gps(),
                "audio": record_audio_clip()
            }
            
            # Display in console
            display_sensor_data(sensor_data)
            
            # Prepare LoRa packet every 30 seconds (every 6th loop if SENSOR_READ_INTERVAL=5)
            loop_count += 1
            if (loop_count * SENSOR_READ_INTERVAL) % LORA_PACKET_INTERVAL == 0:
                prepare_lora_packet(sensor_data)
            
            # Wait before next reading
            time.sleep(SENSOR_READ_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped by user.")
        if gps_serial:
            gps_serial.close()
        dht_device.exit()
        print("✅ Cleanup complete. Goodbye!")
