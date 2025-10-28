import sys
import struct
import random
import time
from LoRaRF import SX127x
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

# --- Radio Setup ---
lora = SX127x()
lora.begin()

# Try all gateway RX channels for Join Request
JOIN_CHANNELS = [916600000, 916800000, 917000000, 917200000, 917600000, 917800000, 918000000, 918200000]
RX2_FREQ = 916600000           # ChirpStack RX2 frequency
RX2_SF = 10                    # RX2 Spreading Factor

# Set initial radio parameters
lora.setLoRaModulation(7, 125000, 5, False)
lora.setSyncWord(0x34)  # 0x34 for LoRaWAN public
lora.setTxPower(14, 1)
lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)

# --- OTAA Keys ---
DevEUI = bytes.fromhex("2ccf67fffe203bf5")
JoinEUI = bytes.fromhex("311ca7e09018d9ec")
AppKey = bytes.fromhex("f3fa2f0d1d52a7764b4ece4afef53afd")

# Session keys
DevAddr = None
NwkSKey = None
AppSKey = None
frame_counter = 0

# --- AES helpers ---
def aes128_encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)

def aes128_decrypt(key, ciphertext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.decrypt(ciphertext)

# --- Session Key Derivation ---
def derive_session_key(appkey, key_type, appnonce, netid, devnonce):
    """Derive NwkSKey (0x01) or AppSKey (0x02)"""
    data = bytearray(16)
    data[0] = key_type
    data[1:4] = appnonce
    data[4:7] = netid
    data[7:9] = devnonce
    return aes128_encrypt(appkey, bytes(data))

# --- Join Accept Validator ---
def validate_and_process_join_accept(join_accept_raw, appkey, dev_nonce_bytes):
    """Checks a raw packet. If it's a valid Join Accept, it processes it."""
    global DevAddr, NwkSKey, AppSKey

    print(f"\n  Received packet ({len(join_accept_raw)} bytes): {join_accept_raw.hex()}")

    # Minimum length check
    if len(join_accept_raw) < 17:
        print(f"  → Too short, ignoring")
        return False

    # 1. Verify MHDR
    mhdr_recv = join_accept_raw[0]
    if mhdr_recv != 0x20:
        print(f"  → Wrong MHDR (0x{mhdr_recv:02x}), ignoring")
        return False

    print(f"  → Valid MHDR! Attempting to decrypt...")

    # 2. Decrypt (Join Accept is encrypted with AppKey)
    encrypted_payload = join_accept_raw[1:]
    
    block = encrypted_payload
    if len(block) % 16 != 0:
        block = block + bytes(16 - (len(block) % 16))

    decrypted_full = aes128_encrypt(appkey, block)
    decrypted = decrypted_full[:len(encrypted_payload)]
    print(f"  → Decrypted: {decrypted.hex()}")

    # 3. Validate MIC
    msg_to_mic = bytearray([mhdr_recv]) + decrypted[:-4]
    mic_recv = decrypted[-4:]

    cmac = CMAC.new(appkey, ciphermod=AES)
    cmac.update(msg_to_mic)
    mic_calc = cmac.digest()[:4]

    if mic_recv != mic_calc:
        print(f"  → Invalid MIC (recv: {mic_recv.hex()}, calc: {mic_calc.hex()})")
        return False

    print("  → ✓ Valid Join Accept MIC!")

    # 4. Parse
    if len(decrypted) < 16:
        print("  → Decrypted payload too short")
        return False

    AppNonce = decrypted[0:3]
    NetID = decrypted[3:6]
    DevAddr = decrypted[6:10]
    DLSettings = decrypted[10]
    RxDelay = decrypted[11]

    print(f"\n  Join Accept Details:")
    print(f"    AppNonce: {AppNonce.hex()}")
    print(f"    NetID: {NetID.hex()}")
    print(f"    DevAddr: {DevAddr.hex()}")
    print(f"    DLSettings: 0x{DLSettings:02x}")
    print(f"    RxDelay: {RxDelay}")

    # 5. Derive session keys
    NwkSKey = derive_session_key(appkey, 0x01, AppNonce, NetID, dev_nonce_bytes)
    AppSKey = derive_session_key(appkey, 0x02, AppNonce, NetID, dev_nonce_bytes)

    print(f"\n  Session Keys:")
    print(f"    NwkSKey: {NwkSKey.hex()}")
    print(f"    AppSKey: {AppSKey.hex()}")
    print("\n✓ ✓ ✓ JOIN SUCCESSFUL! ✓ ✓ ✓\n")

    return True

# --- Join Procedure ---
def join_network_on_channel(join_channel):
    """Attempt join on a specific channel"""
    global dev_nonce

    print(f"\n{'='*60}")
    print(f"Attempting Join on {join_channel/1e6:.1f} MHz")
    print(f"{'='*60}")

    # Generate DevNonce
    dev_nonce = random.randint(0, 65535)
    dev_nonce_bytes = struct.pack('<H', dev_nonce)

    # Build Join Request
    mhdr = 0x00
    join_payload = bytearray()
    join_payload.append(mhdr)
    join_payload.extend(JoinEUI[::-1])
    join_payload.extend(DevEUI[::-1])
    join_payload.extend(dev_nonce_bytes)

    # Calculate MIC
    cmac = CMAC.new(AppKey, ciphermod=AES)
    cmac.update(bytes(join_payload))
    mic = cmac.digest()[:4]
    join_payload.extend(mic)

    print(f"DevNonce: {dev_nonce} (0x{dev_nonce:04x})")
    print(f"Join Request: {join_payload.hex()}")

    # Configure and send
    lora.setFrequency(join_channel)
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)

    lora.beginPacket()
    lora.write(list(join_payload), len(join_payload))
    lora.endPacket()
    lora.wait()

    print(f"→ Join Request SENT")
    print(f"\nListening for Join Accept...")

    # --- RX1 Window ---
    print(f"  RX1 (t+5s): {join_channel/1e6:.1f} MHz, SF10")
    lora.setFrequency(join_channel)
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, True)
    
    time.sleep(5)
    lora.request()

    start = time.time()
    while time.time() - start < 1.0:
        if lora.available():
            length = lora.available()
            join_accept_raw = bytes(lora.read(length))
            if validate_and_process_join_accept(join_accept_raw, AppKey, dev_nonce_bytes):
                return True
        time.sleep(0.02)

    # --- RX2 Window ---
    print(f"  RX2 (t+6s): {RX2_FREQ/1e6:.1f} MHz, SF{RX2_SF}")
    lora.setFrequency(RX2_FREQ)
    lora.setLoRaModulation(RX2_SF, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, True)
    lora.request()

    time.sleep(0.1)

    start = time.time()
    while time.time() - start < 2.0:
        if lora.available():
            length = lora.available()
            join_accept_raw = bytes(lora.read(length))
            if validate_and_process_join_accept(join_accept_raw, AppKey, dev_nonce_bytes):
                return True
        time.sleep(0.02)

    print(f"  → No Join Accept received")
    return False

# --- Main Execution ---
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("LoRaWAN OTAA Diagnostic Tool - AS923-3")
    print("=" * 60)
    print("\nThis script will try joining on ALL gateway channels")
    print("to help identify which frequency is working.\n")

    print("Device Info:")
    print(f"  DevEUI: {DevEUI.hex()}")
    print(f"  JoinEUI: {JoinEUI.hex()}")
    print(f"  AppKey: {AppKey.hex()}")
    print(f"\nGateway Channels to Test: {[f'{f/1e6:.1f}' for f in JOIN_CHANNELS]} MHz")
    print(f"RX2 Configuration: {RX2_FREQ/1e6:.1f} MHz, SF{RX2_SF}")
    
    input("\nPress Enter to start join attempts...")

    # Try each channel
    for channel in JOIN_CHANNELS:
        if join_network_on_channel(channel):
            print(f"\n{'='*60}")
            print(f"SUCCESS! Device joined on {channel/1e6:.1f} MHz")
            print(f"{'='*60}\n")
            sys.exit(0)
        
        print("\nWaiting 5 seconds before next attempt...\n")
        time.sleep(5)

    print("\n" + "="*60)
    print("FAILED - No successful join on any channel")
    print("="*60)
    print("\nTroubleshooting steps:")
    print("1. Check gateway is online and receiving packets")
    print("2. Verify keys match in ChirpStack device configuration")
    print("3. Check ChirpStack Gateway 'Live LoRaWAN frames' tab")
    print("4. Verify gateway global.json has no syntax errors")
    print("5. Check gateway service logs: journalctl -u chirpstack-* -f")
    sys.exit(1)
