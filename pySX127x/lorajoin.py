import sys
import struct
from time import sleep
from LoRaRF import SX127x
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

# --- Radio Setup ---
lora = SX127x()

# Initialize the module
lora.begin()

# AS923-3 uplink channels
UPLINK_CHANNELS = [916600000, 916800000]
channel_index = 0

# Frequency compensation for crystal error (adjust if needed)
# Your module transmits ~100kHz lower than set frequency
FREQ_COMPENSATION = 100000  # +100 kHz to compensate

# Configure modem parameters (will set frequency in loop)
lora.setLoRaModulation(7, 125000, 5, False)  # SF7, BW125kHz, CR4/5, LDRO off
lora.setSyncWord(0x34)  # LoRaWAN sync word
lora.setTxPower(14, 1)  # +14 dBm (1 = PA_BOOST, 0 = RFO)

# Set packet parameters
lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)

# --- ABP Keys ---
DevAddr = bytes.fromhex("01a375c5")
NwkSKey = bytes.fromhex("a9393eaa20a62685cc3451eefb18752b")
AppSKey = bytes.fromhex("ff1accacba6c12567764955ec664a674")

# --- Manual LoRaWAN Frame Construction ---
frame_counter = 0

def aes128_encrypt(key, plaintext):
    """Encrypt plaintext with AES128 ECB mode"""
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)

def lorawan_encrypt(key, devaddr, fcnt, payload, direction=0):
    """Encrypt/decrypt LoRaWAN payload"""
    k = len(payload) // 16 + 1
    s = bytearray()

    for i in range(k):
        # Build block Ai
        a = bytearray(16)
        a[0] = 0x01
        a[1] = 0x00
        a[2] = 0x00
        a[3] = 0x00
        a[4] = 0x00
        a[5] = direction  # 0 for uplink, 1 for downlink
        # DevAddr (little endian)
        a[6:10] = devaddr[::-1]
        # Frame counter (little endian)
        a[10:14] = struct.pack('<I', fcnt)
        a[14] = 0x00
        a[15] = i + 1

        s.extend(aes128_encrypt(key, bytes(a)))

    # XOR with payload
    encrypted = bytearray()
    for i in range(len(payload)):
        encrypted.append(payload[i] ^ s[i])

    return bytes(encrypted)

def calculate_mic(key, mhdr, devaddr, fcnt, fport, payload):
    """Calculate LoRaWAN MIC"""
    # Build B0 block
    b0 = bytearray(16)
    b0[0] = 0x49
    b0[1] = 0x00
    b0[2] = 0x00
    b0[3] = 0x00
    b0[4] = 0x00
    b0[5] = 0x00  # Direction: 0 for uplink
    # DevAddr (little endian)
    b0[6:10] = devaddr[::-1]
    # Frame counter (little endian)
    b0[10:14] = struct.pack('<I', fcnt)
    b0[14] = 0x00
    b0[15] = len(payload) + 1  # Length of FHDR + FPort + FRMPayload

    # Build message to authenticate
    msg = bytearray()
    msg.append(mhdr)
    msg.extend(devaddr[::-1])  # DevAddr (little endian)
    msg.append(0x00)  # FCtrl
    msg.extend(struct.pack('<H', fcnt))  # FCnt (little endian, 16 bits)
    msg.append(fport)  # FPort
    msg.extend(payload)  # Encrypted payload

    # Calculate CMAC
    cmac = CMAC.new(key, ciphermod=AES)
    cmac.update(bytes(b0))
    cmac.update(bytes(msg))
    mic = cmac.digest()[:4]

    return mic

def make_uplink(payload_str):
    """Build LoRaWAN uplink frame"""
    global frame_counter

    # Convert payload to bytes
    payload_bytes = payload_str.encode()

    # Encrypt payload
    encrypted_payload = lorawan_encrypt(AppSKey, DevAddr, frame_counter, payload_bytes, direction=0)

    # Build frame
    mhdr = 0x40  # Unconfirmed Data Up
    fport = 1

    # Calculate MIC
    mic = calculate_mic(NwkSKey, mhdr, DevAddr, frame_counter, fport, encrypted_payload)

    # Assemble complete frame
    frame = bytearray()
    frame.append(mhdr)
    frame.extend(DevAddr[::-1])  # DevAddr (little endian)
    frame.append(0x00)  # FCtrl
    frame.extend(struct.pack('<H', frame_counter))  # FCnt (little endian, 16 bits)
    frame.append(fport)  # FPort
    frame.extend(encrypted_payload)
    frame.extend(mic)

    return bytes(frame)

# --- Send Loop ---
print("Starting LoRaWAN uplink loop (AS923-3)...")
print("DevAddr:", DevAddr.hex())
print("Channels:", [f"{ch/1e6:.1f} MHz" for ch in UPLINK_CHANNELS])
print("Initial frame counter:", frame_counter)
print()

try:
    while True:
        # Select channel for this transmission
        current_freq = UPLINK_CHANNELS[channel_index % len(UPLINK_CHANNELS)]
        compensated_freq = current_freq + FREQ_COMPENSATION
        lora.setFrequency(compensated_freq)
        
        payload = make_uplink("EcoPing")
        print(f"Frame #{frame_counter}")
        print(f"  Target: {current_freq/1e6:.1f} MHz, Set: {compensated_freq/1e6:.1f} MHz (Channel {channel_index % len(UPLINK_CHANNELS)})")
        print(f"  Raw hex: {payload.hex()}")
        print(f"  Length: {len(payload)} bytes")

        # Convert bytes to list for LoRaRF
        payload_list = list(payload)

        # Transmit using LoRaRF's recommended method
        lora.beginPacket()
        lora.write(payload_list, len(payload_list))
        lora.endPacket()
        lora.wait()  # Wait for transmission to complete

        print(f"  ✓ Transmitted successfully")
        print()

        frame_counter += 1
        channel_index += 1
        sleep(5)

except KeyboardInterrupt:
    print("\n\nTransmission stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
