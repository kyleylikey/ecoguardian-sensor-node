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
# NEW IMPORTS FOR MULTI-THREADING AND AUDIO CLASSIFICATION
import threading
from edge_impulse_linux.audio import AudioImpulseRunner


# --- ABP Credentials (PASTE YOUR KEYS FROM CHIRPSTACK HERE) ---
DevAddr = bytes.fromhex("01122765")
NwkSKey = bytes.fromhex("0537ed2cdee9f226874e74a211c03417")
AppSKey = bytes.fromhex("bd3b68fc557f24f881c298f74d55736a")
# Frame counter for LoRaWAN
frame_counter = 0

# --- Radio Setup ---
lora = SX127x()
lora.begin()
TX_FREQ = 916600000
TX_SF = 10
TX_BW = 125000
LORA_PACKET_INTERVAL = 10 # seconds between regular LoRa packet transmissions

# --- Edge Impulse Audio Classification Setup ---
MODEL_PATH = "gunshot-and-chainsaw-detection-70%-accuracy-linux-aarch64-v1.eim"
# Use the working hardware address, e.g., "plughw:1,0" or "dsnoop:CARD=1,DEV=0"
# NOTE: Using None or an incorrect ID will cause the audio thread to crash.
AUDIO_DEVICE_ID = None
CONFIDENCE_THRESHOLD = 60.0

# Global state to store the latest classification result and a lock for thread safety
global_audio_result = {
    "risk_level": "none",
    "confidence": 0.0,
    "last_event": None
}
audio_result_lock = threading.Lock()

# --- New Global State for Persistent Audio Monitoring ---
# Stores the last N audio classification results for persistence checking
AUDIO_HISTORY = []
HISTORY_LENGTH = 10 # Check against the last 10 seconds (since loop is 1 sec)
PERSISTENCE_THRESHOLD_PCT = 30 # 30% persistence required (3 out of 10 seconds)

# SENSOR_READ_INTERVAL is used as the loop sleep time
# CRITICAL: MUST BE 1 second for the 10-second audio persistence check to work
SENSOR_READ_INTERVAL = 1

# DHT22 Configuration
DHT_PIN = board.D4
TEMP_WARNING = 35.0
TEMP_DANGER = 40.0
HUMIDITY_WARNING = 30.0
HUMIDITY_DANGER = 20.0

# Gas Sensor and Thresholds
VCC = 5.0
RL = 10.0
R0 = 170.278
FIRE_TEMP_THRESHOLD = 30.0
FIRE_HUMID_THRESHOLD = 60.0 # Below this value
FIRE_CO_THRESHOLD = 10.0

# GPS Configuration
GPS_PORT = "/dev/ttyS0"
GPS_BAUDRATE = 9600

# --- LoRa Setup (Omitted for brevity, remains the same) ---
lora.setSyncWord(0x34)
lora.setTxPower(20, 1)
lora.setLoRaModulation(TX_SF, TX_BW, 5, False)
lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)

# --- AES helpers (Omitted for brevity, remains the same) ---
def aes128_encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)

def calculate_mic(key, msg):
    cmac = CMAC.new(key, ciphermod=AES)
    cmac.update(msg)
    return cmac.digest()[:4]

def encrypt_payload(key, devaddr, fcnt, payload):
    encrypted = bytearray()
    block_index = 1
    payload_len = len(payload)
    for i in range(0, payload_len, 16):
        a_block = bytearray(16)
        a_block[0] = 0x01
        a_block[5] = 0x00
        a_block[6:10] = devaddr[::-1]
        a_block[10:14] = struct.pack('<L', fcnt)
        a_block[15] = block_index & 0xFF
        s_block = aes128_encrypt(key, a_block)
        chunk = payload[i : min(i + 16, payload_len)]
        for j in range(len(chunk)):
            encrypted.append(chunk[j] ^ s_block[j])
        block_index += 1
    return bytes(encrypted)


# ===== SENSOR INITIALIZATION AND READ FUNCTIONS =====
# ... (dht_device, ads, i2c, gps_serial initialization code here)

dht_device = adafruit_dht.DHT22(DHT_PIN, use_pulseio=False)
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)
gas_channel = AnalogIn(ads, 0)
gps_serial = None
try:
    gps_serial = serial.Serial(GPS_PORT, baudrate=GPS_BAUDRATE, timeout=0.1)
    print("[GPS] Serial port opened successfully")
except Exception as e:
    print(f"[GPS] ERROR: Could not open serial port: {e}")

# --- Temperature & Humidity ---
def read_temp_humidity():
    # ... (read_temp_humidity logic remains the same)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            temperature = dht_device.temperature
            humidity = dht_device.humidity
            if temperature is not None and humidity is not None:
                temp_status = "Normal"
                if temperature >= TEMP_DANGER: temp_status = "DANGER"
                elif temperature >= TEMP_WARNING: temp_status = "WARNING"
                humidity_status = "Normal"
                if humidity <= HUMIDITY_DANGER: humidity_status = "DANGER"
                elif humidity <= HUMIDITY_WARNING: humidity_status = "WARNING"
                return {
                    "temperature": round(temperature, 1),
                    "humidity": round(humidity, 1),
                    "temp_status": temp_status,
                    "humidity_status": humidity_status
                }
            else:
                time.sleep(0.5)
                continue
        except RuntimeError as error:
            if "Checksum" in str(error):
                time.sleep(0.5)
                if attempt < max_retries - 1: continue
                else: print(f"[DHT22] Checksum error after {max_retries} attempts: {error.args[0]}"); return None
            else: print(f"[DHT22] Reading error: {error.args[0]}"); return None
        except Exception as error:
            print(f"[DHT22] Unexpected error: {error}"); return None
    return None

# --- Gas Sensor (MQ-7) ---
def get_resistance(voltage):
    if voltage <= 0: return 999999
    return RL * (VCC - voltage) / voltage

def get_ppm_co(Rs, R0):
    ratio = Rs / R0
    a_co = 10.0
    b_co = -1.8
    return a_co * pow(ratio, b_co)

def read_gas_sensor():
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
        print(f"[GAS] Error reading sensor: {error}"); return None

# --- GPS ---
def convert_to_decimal(coord, direction):
    # ... (convert_to_decimal logic remains the same)
    if not coord or coord == "0": return None
    if direction in ["N", "S"]: degrees = int(coord[:2]); minutes = float(coord[2:])
    else: degrees = int(coord[:3]); minutes = float(coord[3:])
    decimal = degrees + minutes / 60
    if direction in ["S", "W"]: decimal = -decimal
    return round(decimal, 6)

def parse_gngga(sentence):
    # ... (parse_gngga logic remains the same)
    parts = sentence.split(",")
    if len(parts) < 15: return None
    fix_quality = parts[6]
    if fix_quality == "0": return None
    return {
        "time": parts[1][:6] if parts[1] else "N/A",
        "latitude": convert_to_decimal(parts[2], parts[3]),
        "longitude": convert_to_decimal(parts[4], parts[5]),
        "fix": True,
        "satellites": int(parts[7]) if parts[7] else 0,
        "altitude": float(parts[9]) if parts[9] else None
    }

def read_gps():
    # ... (read_gps logic remains the same)
    if gps_serial is None: return None
    try:
        gps_serial.reset_input_buffer()
        for attempt in range(5):
            line = gps_serial.readline().decode(errors="ignore").strip()
            if line.startswith("$GNGGA"):
                gps_data = parse_gngga(line)
                if gps_data: return gps_data
        return None
    except Exception as error:
        print(f"[GPS] Error reading data: {error}"); return None


# --- Audio Classification Thread Logic ---
def audio_inference_thread():
    # ... (audio_inference_thread logic remains the same)
    global global_audio_result, audio_result_lock
    script_dir = os.path.dirname(os.path.realpath(__file__))
    modelfile_path = os.path.join(script_dir, MODEL_PATH)
    print("--- Starting Live Audio Inference via Edge Impulse SDK ---")
    if not os.path.exists(modelfile_path):
        print(f"\n[FATAL] The required model file was not found at: '{modelfile_path}'"); return
    if not os.access(modelfile_path, os.X_OK):
        print("\n[CRITICAL] Model file does NOT have executable permission."); print(f"Action Required: Run 'chmod +x {MODEL_PATH}' in this directory."); return
    try:
        with AudioImpulseRunner(modelfile_path) as runner:
            model_info = runner.init()
            labels = model_info['model_parameters']['labels']
            print(f"🎧 Model Labels: {labels}")
            for res, audio in runner.classifier(device_id=AUDIO_DEVICE_ID):
                if "classification" not in res["result"].keys(): continue
                classification_result = res['result']['classification']
                max_confidence = 0.0
                predicted_label = 'unknown'
                for label, confidence_val in classification_result.items():
                    if confidence_val > max_confidence:
                        max_confidence = confidence_val
                        predicted_label = label
                confidence = max_confidence * 100
                is_ignored_class = predicted_label.lower() in ['others']
                with audio_result_lock:
                    if confidence >= CONFIDENCE_THRESHOLD and not is_ignored_class:
                        if predicted_label != global_audio_result["last_event"]:
                            print(f"\n[AUDIO EVENT] ** {predicted_label.upper()} ** (Conf: {confidence:.2f}%)\n")
                        global_audio_result["risk_level"] = predicted_label.lower()
                        global_audio_result["confidence"] = round(confidence, 2)
                        global_audio_result["last_event"] = predicted_label
                    elif global_audio_result["last_event"] is not None and confidence < CONFIDENCE_THRESHOLD:
                        if not global_audio_result["last_event"].lower() in ['others', 'none']:
                            print(f"[AUDIO] Confidence for {global_audio_result['last_event']} dropped below {CONFIDENCE_THRESHOLD:.1f}%...")
                        global_audio_result["risk_level"] = "none"
                        global_audio_result["confidence"] = round(confidence, 2)
                        global_audio_result["last_event"] = None
    except Exception as e:
        print(f"\n[FATAL AUDIO ERROR] An unexpected error occurred: {e}")
    finally:
        print("\n[INFO] Audio inference thread exited.")


def read_audio_classification():
    """ Safely reads the latest classification result from the thread. """
    global global_audio_result, audio_result_lock
    with audio_result_lock:
        return global_audio_result.copy()

# --- NEW: Audio Persistence Logic ---

def check_audio_persistence(current_audio_risk_level, history):
    """
    Checks if 'logging' has been detected in at least 30% of the last 10 readings.
    For 'poaching', returns immediately without persistence check.
    Returns the detected risk level (chainsaw/gunshots) or "none".
    """

    # Poaching (gunshots) should be sent immediately without persistence check
    if current_audio_risk_level == "poaching":
        return "gunshots"

    # 1. Update History (only for logging)
    history.append(current_audio_risk_level)
    while len(history) > HISTORY_LENGTH:
        history.pop(0)

    # We must have enough data points to check persistence
    if len(history) < HISTORY_LENGTH:
        return "none"

    # 2. Check Persistence for logging (chainsaw) only
    logging_count = history.count("logging")
    required_count = len(history) * (PERSISTENCE_THRESHOLD_PCT / 100.0)

    if logging_count >= required_count:
        return "chainsaw"
    else:
        return "none"


# --- Packet Preparation ---
def prepare_lora_packet_json(data, is_alert=False):
    """
    Serializes the packet based on whether it is a regular reading or an alert.
    The structure MUST match the ChirpStack decoder.
    """
    global frame_counter

    if is_alert:
        # Structure for ALERT type (matches your decoder's alert path)
        packet = {
            "type": "alert",
            "nodeID": 2,
            "risk_type": data["risk_type"],
            "risk_level": data["risk_level"] if data.get("risk_level") else None, # risk_level is used for the audio code, but the decoder handles risk_type
            "confidence": data["confidence"] if data.get("confidence") else None
        }
    else:
        # Structure for READING type (matches your decoder's reading path)
        th = data.get("temp_humid") or {}
        gas = data.get("gas") or {}
        gps = data.get("gps") or {}

        packet = {
            "type": "reading",
            "nodeID": 2,
            "temp": th.get("temperature"),
            "humidity": th.get("humidity"),
            "co_ppm": gas.get("co_ppm"),
            "latitude": gps.get("latitude"),
            "longitude": gps.get("longitude"),
            "altitude": gps.get("altitude"),
            "gps_fix": bool(gps.get("fix", False)),
            # NOTE: The existing decoder ignores audio data in the 'reading' packet.
            # We omit it here to keep the packet small and clean.
        }

    json_bytes = json.dumps(packet, separators=(',', ':')).encode('utf-8')

    print(f"\n📤 JSON being sent: {packet}")
    print(f"   Raw JSON string: {json.dumps(packet, separators=(',', ':'))}")
    print(f"   JSON bytes length: {len(json_bytes)}")

    # --- LoRaWAN Sending Logic ---
    if len(json_bytes) > 200:
        print(f"[LoRa][WARN] JSON payload length {len(json_bytes)} bytes — may exceed max FRMPayload for your DR.")

    print(f"\n📡 LoRa JSON Packet Ready (Type: {packet['type']}):", packet)
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
    # ... (send_data_packet logic remains the same)
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
                print(f"[LoRa] final write attempt failed: {e3}"); raise
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
    else: print("🌡️  Temperature: ERROR"); print("💧 Humidity: ERROR")
    # Gas Sensor
    if data.get("gas"):
        gas = data["gas"]
        print(f"🔥 CO Level: {gas['co_ppm']} ppm | Voltage: {gas['voltage']}V | Rs: {gas['resistance']}kΩ")
        print("   ⚠️  REMINDER: Calibrate R0 in clean air for accurate readings")
    else: print("🔥 Gas Sensor: ERROR")
    # GPS
    if data.get("gps"):
        gps = data["gps"]
        if gps["fix"]:
            print(f"📍 GPS: {gps['latitude']}, {gps['longitude']} | Alt: {gps['altitude']}m")
            print(f"   Satellites: {gps['satellites']} | Time: {gps['time']}")
        else:
            print(f"📍 GPS: No fix yet (Satellites: {gps['satellites']}) - warming up...")
    else: print("📍 GPS: No data (check wiring or wait for warm-up)")
    # Audio Classification
    if data.get("audio"):
        audio = data["audio"]
        level = audio.get("risk_level", "unknown").upper()
        conf = audio.get("confidence", 0.0)
        if level in ["LOGGING", "POACHING"]:
            print(f"🚨 Audio: **{level}** (Conf: {conf:.2f}%)")
        else:
            print(f"🎤 Audio: {level} (Conf: {conf:.2f}%)")
    print("=" * 60)

# ===== MAIN LOOP =====
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Forest Fire Detection System - Unified Sensor Monitor")
    print("=" * 60)
    print(f"Sensor readings every: {SENSOR_READ_INTERVAL}s")
    print(f"LoRa packet preparation every: {LORA_PACKET_INTERVAL}s")
    print("=" * 60)

    # Start the audio inference thread
    audio_thread = threading.Thread(target=audio_inference_thread, daemon=True)
    audio_thread.start()
    print("✅ Started Edge Impulse audio inference thread.")

    try:
        print("\n🚀 Starting sensor monitoring loop...")
        if gps_serial: time.sleep(10)
        last_lora_send = time.time()

        while True:
            current_time = time.time()

            # 1. READ ALL SENSORS
            sensor_data = {
                "temp_humid": read_temp_humidity(),
                "gas": read_gas_sensor(),
                "gps": read_gps(),
                "audio": read_audio_classification()
            }

            # 2. CHECK ALL THRESHOLDS AND PERSISTENCE
            th = sensor_data["temp_humid"]
            gas = sensor_data["gas"]
            audio_result = sensor_data["audio"]

            # --- Check Audio Persistence Threshold (60% of last 10s) ---
            persistent_audio_risk = check_audio_persistence(
                audio_result.get("risk_level"), AUDIO_HISTORY
            )

            # --- Check Fire Sensor Thresholds (ALL must be met) ---
            is_fire_alert = False
            if th and gas and th["temperature"] is not None and th["humidity"] is not None and gas["co_ppm"] is not None:
                is_fire_alert = (
                    th["temperature"] > FIRE_TEMP_THRESHOLD and
                    th["humidity"] < FIRE_HUMID_THRESHOLD and
                    gas["co_ppm"] > FIRE_CO_THRESHOLD
                )

            # 3. DETERMINE PACKET TYPE AND SEND

            # Prioritize alert packets
            if persistent_audio_risk != "none":
                # Audio Alert: Logging or Poaching
                alert_payload = {
                    "risk_type": persistent_audio_risk, # "chainsaw" or "gunshots"
                    "risk_level": 1 if persistent_audio_risk == "chainsaw" else 2, # Using risk_level for the decoder's null check
                    "confidence": audio_result.get("confidence")
                }
                prepare_lora_packet_json(alert_payload, is_alert=True)
                # Different message for chainsaw (persistent) vs gunshots (immediate)
                if persistent_audio_risk == "chainsaw":
                    print(f"!!! 🚨 CRITICAL AUDIO ALERT: {persistent_audio_risk.upper()} (Persistent)")
                else:
                    print(f"!!! 🚨 CRITICAL AUDIO ALERT: {persistent_audio_risk.upper()} (Immediate)")
                last_lora_send = current_time

            elif is_fire_alert:
                # Fire Alert: Critical Sensor Readings
                alert_payload = {
                    "risk_type": "fire", # Custom type for fire event
                    "risk_level": 3, # arbitrary code for fire
                    "confidence": None # Confidence is not applicable for fire sensors
                }
                prepare_lora_packet_json(alert_payload, is_alert=True)
                print("!!! 🔥 CRITICAL FIRE ALERT: Thresholds breached.")
                last_lora_send = current_time

            elif current_time - last_lora_send >= LORA_PACKET_INTERVAL:
                # Regular Reading: Send full sensor data
                prepare_lora_packet_json(sensor_data, is_alert=False)
                last_lora_send = current_time

            # Display in console
            display_sensor_data(sensor_data)

            # Wait before next sensor read
            time.sleep(SENSOR_READ_INTERVAL) # Set to 1 second

    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped by user.")
        if gps_serial: gps_serial.close()
        dht_device.exit()
        print("✅ Cleanup complete. Goodbye!")