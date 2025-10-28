import sys
import struct
import time
import random
from LoRaRF import SX127x
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

# --- ABP Credentials (PASTE YOUR KEYS FROM CHIRPSTACK HERE) ---
DevAddr = bytes.fromhex("0060276b")
NwkSKey = bytes.fromhex("4dad53a60342ea5b3b0d6a1ca5e80cec")
AppSKey = bytes.fromhex("249a97f57042ec468d5b5c45302a1af4")
frame_counter = 0

# --- Radio Setup ---
lora = SX127x()
lora.begin()
TX_FREQ = 916600000  # We'll send on the first channel
TX_SF = 10           # We use SF10 because it worked for your Join Request
TX_BW = 125000       # 125kHz bandwidth

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
    # A block = 0x01 | 4x 0x00 | 0x00 (dir=up) | DevAddr | FCnt (32-bit) | 0x00 | 0x01 (block index)
    a_block = bytearray(16)
    a_block[0] = 0x01
    a_block[5] = 0x00  # 0x00 = Uplink
    a_block[6:10] = devaddr[::-1]  # Little-endian DevAddr
    a_block[10:14] = struct.pack('<L', fcnt)  # Little-endian 32-bit FCnt
    a_block[15] = 0x01  # Block index 1

    # Encrypt the A block to get the S (keystream) block
    s_block = aes128_encrypt(key, a_block)

    # XOR payload with S block
    encrypted = bytearray()
    for i in range(len(payload)):
        encrypted.append(payload[i] ^ s_block[i])
    
    return bytes(encrypted)

def prepare_lora_packet(data):
    """
    Prepare data packet for LoRa transmission.
    Returns a dictionary with all sensor data formatted for transmission.
    """
    packet = {
        "timestamp": time.time(),
        "temp": data.get("temp_humid", {}).get("temperature"),
        "humidity": data.get("temp_humid", {}).get("humidity"),
        "co_ppm": data.get("gas", {}).get("co_ppm"),
        "latitude": data.get("gps", {}).get("latitude"),
        "longitude": data.get("gps", {}).get("longitude"),
        "altitude": data.get("gps", {}).get("altitude"),
        "gps_fix": data.get("gps", {}).get("fix", False),
    }
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
    lora.write(list(phy_payload), len(phy_payload))
    lora.endPacket()
    lora.wait()
    
    print("→ Packet SENT")

    frame_counter += 1 # Increment for next packet

# --- Main Execution ---
if __name__ == "__main__":
    
    # This is a placeholder for your *real* sensor reading code.
    # Replace this with your actual functions that get data.
    def get_all_sensor_data():
        """
        [PLACEHOLDER] Replace this with your actual sensor reading code.
        This function should return a dictionary in the format
        your prepare_lora_packet function expects.
        """
        print("Reading data from sensors... (simulated)")
        simulated_data = {
            "temp_humid": {"temperature": 25.6, "humidity": 55.2},
            "gas": {"co_ppm": 45},
            "gps": {"latitude": 14.6507, "longitude": 121.0493, "altitude": 52.0, "fix": True}
        }
        # Simulate GPS fix loss occasionally
        if random.randint(0, 10) > 8:
            simulated_data["gps"]["fix"] = False
            
        return simulated_data

    # Main sensor loop
    while True:
        try:
            # 1. Get data from your sensors
            sensor_data = get_all_sensor_data()
            
            # 2. Prepare the data packet (your function)
            packet_dict = prepare_lora_packet(sensor_data)
            
            # 3. Encode the packet into bytes (new function)
            my_payload = encode_payload(packet_dict)
            
            # 4. Send the packet (existing function)
            if my_payload:
                send_data_packet(my_payload)
            else:
                print("Skipping send due to payload encoding error.")
            
            print("\nWaiting 60 seconds to send next packet...")
            time.sleep(60)
        
        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(0)
