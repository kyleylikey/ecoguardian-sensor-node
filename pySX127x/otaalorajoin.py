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

UPLINK_CHANNELS = [916600000, 916800000]
JOIN_CHANNEL = 916800000      # AS923-3 join channel
RX2_FREQ = 923300000          # AS923-3 RX2 frequency
RX2_SF = 10                   # AS923-3 RX2 Spreading Factor (DR2)
channel_index = 0
FREQ_COMPENSATION = 0

# Set initial radio parameters (will be changed for Join)
lora.setLoRaModulation(7, 125000, 5, False)
lora.setSyncWord(0x34) # 0x34 for public, 0x12 for private
lora.setTxPower(14, 1)
lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)

# --- OTAA Keys (From your logs) ---
DevEUI = bytes.fromhex("2ccf67fffe203bf5")
JoinEUI = bytes.fromhex("311ca7e09018d9ec") # Updated JoinEUI
AppKey = bytes.fromhex("490026878401980550897019dc784bad")

# Session keys (will be set after join)
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

# --- Join Accept Validator (Helper Function) ---
def validate_and_process_join_accept(join_accept_raw, appkey, dev_nonce_bytes):
    """Checks a raw packet. If it's a valid Join Accept, it processes it."""
    global DevAddr, NwkSKey, AppSKey
    
    print(f"\nReceived packet: {join_accept_raw.hex()}")

    # 1. Verify MHDR (should be 0x20 for Join Accept)
    mhdr_recv = join_accept_raw[0]
    if mhdr_recv != 0x20:
        print(f"Error: Not a Join Accept (MHDR: 0x{mhdr_recv:02x}). Discarding.")
        return False  # Not a Join Accept

    # 2. Validate MIC
    msg_to_mic = join_accept_raw[:-4]
    mic_recv = join_accept_raw[-4:]

    cmac = CMAC.new(appkey, ciphermod=AES)
    cmac.update(msg_to_mic)
    mic_calc = cmac.digest()[:4]

    if mic_recv != mic_calc:
        print(f"Error: Invalid Join Accept MIC. Discarding.")
        print(f"  Received:   {mic_recv.hex()}")
        print(f"  Calculated: {mic_calc.hex()}")
        return False  # Bad MIC

    print("✓ Join Accept MIC is valid!")

    # 3. Correct Decryption (LoRaWAN spec: encrypt with AppKey)
    encrypted_payload = join_accept_raw[1:-4]
    
    # Pad if necessary for AES block size
    block = encrypted_payload
    if len(block) % 16 != 0:
        block = block + bytes(16 - (len(block) % 16))
    
    decrypted = aes128_encrypt(appkey, block)
    
    # Trim to actual payload length
    decrypted = decrypted[:len(encrypted_payload)]
    print(f"Decrypted Join Accept: {decrypted.hex()}")

    # 4. Parse Decrypted Payload
    AppNonce = decrypted[0:3]
    NetID = decrypted[3:6]
    DevAddr = decrypted[6:10] # Stored in Big-Endian format
    DLSettings = decrypted[10]
    RxDelay = decrypted[11]

    print(f"\nJoin Accept parsed:")
    print(f"  AppNonce: {AppNonce.hex()}")
    print(f"  NetID: {NetID.hex()}")
    print(f"  DevAddr: {DevAddr.hex()}")
    print(f"  DLSettings: 0x{DLSettings:02x}")
    print(f"  RxDelay: {RxDelay}")

    # 5. Derive session keys
    NwkSKey = derive_session_key(appkey, 0x01, AppNonce, NetID, dev_nonce_bytes)
    AppSKey = derive_session_key(appkey, 0x02, AppNonce, NetID, dev_nonce_bytes)

    print(f"\nSession keys derived:")
    print(f"  NwkSKey: {NwkSKey.hex()}")
    print(f"  AppSKey: {AppSKey.hex()}")
    print("\n✓ Join successful! Device is now activated.\n")

    return True  # Success!

# --- Join Procedure ---
def join_network():
    global dev_nonce

    print("=" * 50)
    print("Starting OTAA Join Procedure...")
    print("=" * 50)

    # Generate DevNonce
    dev_nonce = random.randint(0, 65535)
    dev_nonce_bytes = struct.pack('<H', dev_nonce) # Little-endian

    # Build Join Request
    mhdr = 0x00  # Join Request
    join_payload = bytearray()
    join_payload.append(mhdr)
    join_payload.extend(JoinEUI[::-1])  # Little-endian
    join_payload.extend(DevEUI[::-1])  # Little-endian
    join_payload.extend(dev_nonce_bytes)

    # Calculate MIC for Join Request
    cmac = CMAC.new(AppKey, ciphermod=AES)
    cmac.update(bytes(join_payload))
    mic = cmac.digest()[:4]
    join_payload.extend(mic)

    print(f"DevEUI: {DevEUI.hex()}")
    print(f"JoinEUI: {JoinEUI.hex()}")
    print(f"DevNonce: {dev_nonce} (0x{dev_nonce:04x})")
    print(f"Join Request: {join_payload.hex()}")

    # --- FIX 1: Set SF10 for Join Request ---
    print(f"Setting radio to SF10/125kHz for Join Request...")
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setInvertIq(False) # Uplinks are NOT inverted

    # Send Join Request on join channel
    lora.setFrequency(JOIN_CHANNEL)
    lora.beginPacket()
    lora.write(list(join_payload), len(join_payload))
    lora.endPacket()
    lora.wait()

    print(f"Join Request sent on {JOIN_CHANNEL/1e6:.1f} MHz")
    print("Waiting for Join Accept...")

    # --- FIX 2: Implement RX1 and RX2 Windows ---
    # --- RX1 Window ---
    # Opens 5 seconds after TX (JOIN_ACCEPT_DELAY1)
    print("Waiting for RX1 window (t+5s)...")
    time.sleep(5)
    
    print(f"Configuring for RX1 on {JOIN_CHANNEL/1e6:.1f} MHz (SF10)...")
    # --- THIS IS THE FIX ---
    # Explicitly set all parameters for RX1
    lora.setFrequency(JOIN_CHANNEL)
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setInvertIq(True) # Downlinks ARE inverted
    # ------------------------
    
    lora.request() # Put radio in RX mode
    
    # Listen for ~0.9 seconds
    start = time.time()
    while time.time() - start < 0.9:
        if lora.available():
            length = lora.available()
            join_accept_raw = bytes(lora.read(length))
            if validate_and_process_join_accept(join_accept_raw, AppKey, dev_nonce_bytes):
                return True # Success!
        time.sleep(0.02) # Short poll

    # --- RX2 Window ---
    # Opens 6 seconds after TX (JOIN_ACCEPT_DELAY2)
    # AS923-3: 923.3 MHz, SF10 (DR2)
    print(f"Switching to RX2 on {RX2_FREQ/1e6:.1f} MHz (SF{RX2_SF})...")
    lora.setFrequency(RX2_FREQ)
    lora.setLoRaModulation(RX2_SF, 125000, 5, False)
    lora.setInvertIq(True)
    lora.request() # Put radio in RX mode on new settings
    
    # We already waited ~5.9s. RX2 opens at 6s.
    # Sleep for the remaining fraction + listen duration
    time.sleep(0.1) # Wait for t=6s to be certain
    
    start = time.time()
    while time.time() - start < 2.0: # Listen for 2 seconds
        if lora.available():
            length = lora.available()
            join_accept_raw = bytes(lora.read(length))
            if validate_and_process_join_accept(join_accept_raw, AppKey, dev_nonce_bytes):
                return True # Success!
        time.sleep(0.02)

    # If we get here, both windows timed out
    print("\n✗ Join Accept timeout - no response received in RX1 or RX2")
    print("  Check: Gateway is online, device keys match ChirpStack\n")
    return False

# --- LoRaWAN Frame Construction ---
def lorawan_encrypt(key, devaddr, fcnt, payload, direction=0):
    """Encrypt payload for uplink (direction=0) or downlink (direction=1)"""
    k = len(payload) // 16 + 1
    s = bytearray()
    for i in range(k):
        a = bytearray(16)
        a[0] = 0x01
        a[5] = direction
        a[6:10] = devaddr[::-1] # DevAddr in little-endian
        a[10:14] = struct.pack('<I', fcnt) # FCnt in little-endian
        a[15] = i + 1
        s.extend(aes128_encrypt(key, bytes(a)))
    encrypted = bytearray()
    for i in range(len(payload)):
        encrypted.append(payload[i] ^ s[i])
    return bytes(encrypted)

def calculate_mic(key, mhdr, devaddr, fcnt, fport, payload):
    """Calculate MIC for uplink frame"""
    b0 = bytearray(16)
    b0[0] = 0x49
    b0[5] = 0x00  # Direction: uplink
    b0[6:10] = devaddr[::-1] # DevAddr in little-endian
    b0[10:14] = struct.pack('<I', fcnt) # FCnt in little-endian
    
    msg = bytearray()
    msg.append(mhdr)
    msg.extend(devaddr[::-1]) # DevAddr in little-endian
    msg.append(0x00)  # FCtrl
    msg.extend(struct.pack('<H', fcnt)) # FCnt (lower 16 bits) in little-endian
    msg.append(fport)
    msg.extend(payload)

    # --- FIX 3: Set b0[15] to the length of the message ---
    b0[15] = len(msg)
    # ----------------------------------------------------

    cmac = CMAC.new(key, ciphermod=AES)
    cmac.update(bytes(b0))
    cmac.update(bytes(msg))
    return cmac.digest()[:4]

def make_uplink(payload_str):
    """Create LoRaWAN uplink frame"""
    global frame_counter

    if DevAddr is None or NwkSKey is None or AppSKey is None:
        raise Exception("Device not joined! Run join_network() first.")

    payload_bytes = payload_str.encode()
    encrypted_payload = lorawan_encrypt(AppSKey, DevAddr, frame_counter, payload_bytes, direction=0)

    mhdr = 0x40  # Unconfirmed Data Up
    fport = 1
    
    # Note: DevAddr is already stored Big-Endian from Join Accept
    # calculate_mic and lorawan_encrypt handle flipping it to little-endian
    mic = calculate_mic(NwkSKey, mhdr, DevAddr, frame_counter, fport, encrypted_payload)

    frame = bytearray()
    frame.append(mhdr)
    frame.extend(DevAddr[::-1]) # DevAddr in little-endian
    frame.append(0x00)  # FCtrl
    frame.extend(struct.pack('<H', frame_counter)) # FCnt (lower 16 bits)
    frame.append(fport)
    frame.extend(encrypted_payload)
    frame.extend(mic)

    return bytes(frame)

# --- Main Execution ---
if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("LoRaWAN OTAA Device - AS923-3")
    print("=" * 50 + "\n")

    # Attempt to join
    max_join_attempts = 3
    for attempt in range(1, max_join_attempts + 1):
        print(f"Join attempt {attempt}/{max_join_attempts}")
        if join_network():
            break
        if attempt < max_join_attempts:
            print(f"Retrying in 10 seconds...\n")
            time.sleep(10)
    else:
        print("Failed to join after all attempts. Exiting.")
        sys.exit(1)

    # Start uplink loop
    print("=" * 50)
    print("Starting uplink transmission loop...")
    print("=" * 50 + "\n")

    try:
        while True:
            current_freq = UPLINK_CHANNELS[channel_index % len(UPLINK_CHANNELS)]
            compensated_freq = current_freq + FREQ_COMPENSATION
            lora.setFrequency(compensated_freq)

            # --- FIX 4: Set SF7 for Data Uplinks ---
            lora.setLoRaModulation(7, 125000, 5, False)
            lora.setInvertIq(False)
            # ---------------------------------------

            payload = make_uplink("EcoPing")
            print(f"[{time.strftime('%H:%M:%S')}] Frame #{frame_counter} | "
                  f"Freq: {current_freq/1e6:.1f} MHz (SF7) | "
                  f"Payload: {payload.hex()}")

            payload_list = list(payload)
            lora.beginPacket()
            lora.write(payload_list, len(payload_list))
            lora.endPacket()
            tx_status = lora.wait(timeout=5000)  # Wait max 5 seconds

            if tx_status:
                print(f"  ✓ TX completed successfully")
            else:
                print(f"  ✗ TX failed or timeout!")

            frame_counter += 1
            channel_index += 1

            # TODO: Add downlink listening logic here in RX1/RX2
            
            time.sleep(15)  # Wait before next transmission

    except KeyboardInterrupt:
        print("\n\nTransmission stopped by user")
        print(f"Total frames sent: {frame_counter}")
        sys.exit(0)
