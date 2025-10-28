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

# Focus on the channels where we saw activity
JOIN_CHANNELS = [916600000, 916800000]  # Reduced to most likely channels
RX2_FREQ = 916600000
RX2_SF = 10

lora.setLoRaModulation(7, 125000, 5, False)
lora.setSyncWord(0x34)
lora.setTxPower(14, 1)
lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)

# --- OTAA Keys ---
DevEUI = bytes.fromhex("2ccf67fffe203bf5")
JoinEUI = bytes.fromhex("cb94f571f53f3936")
AppKey = bytes.fromhex("bf04d2d2ee0ab772acea9ebf219a8f66")

print("\n" + "="*70)
print("ENHANCED LoRaWAN OTAA Diagnostic")
print("="*70)
print("\nDevice Configuration:")
print(f"  DevEUI:  {DevEUI.hex()}")
print(f"  JoinEUI: {JoinEUI.hex()}")
print(f"  AppKey:  {AppKey.hex()}")
print("\nKEY VERIFICATION:")
print("  Please verify these EXACT values are in ChirpStack!")
print("  - No spaces, no dashes")
print("  - Copy-paste to avoid typos")
print("="*70)

DevAddr = None
NwkSKey = None
AppSKey = None

def aes128_encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)

def derive_session_key(appkey, key_type, appnonce, netid, devnonce):
    data = bytearray(16)
    data[0] = key_type
    data[1:4] = appnonce
    data[4:7] = netid
    data[7:9] = devnonce
    return aes128_encrypt(appkey, bytes(data))

def try_decrypt_with_multiple_keys(join_accept_raw, dev_nonce_bytes):
    """Try decrypting with AppKey and show what we get"""
    global DevAddr, NwkSKey, AppSKey
    
    print(f"\n  📦 Received: {len(join_accept_raw)} bytes")
    print(f"     Hex: {join_accept_raw.hex()}")
    
    if len(join_accept_raw) < 17:
        print(f"  ❌ Too short")
        return False
    
    mhdr = join_accept_raw[0]
    print(f"  📋 MHDR: 0x{mhdr:02x}", end="")
    
    if mhdr != 0x20:
        print(f" ❌ (Expected 0x20 for Join Accept)")
        return False
    
    print(f" ✓ (Valid Join Accept)")
    
    # Decrypt
    encrypted_payload = join_accept_raw[1:]
    block = encrypted_payload
    if len(block) % 16 != 0:
        block = block + bytes(16 - (len(block) % 16))
    
    decrypted_full = aes128_encrypt(AppKey, block)
    decrypted = decrypted_full[:len(encrypted_payload)]
    
    print(f"\n  🔓 Decrypted payload:")
    print(f"     {decrypted.hex()}")
    
    # Parse fields
    AppNonce = decrypted[0:3]
    NetID = decrypted[3:6]
    DevAddr_recv = decrypted[6:10]
    DLSettings = decrypted[10]
    RxDelay = decrypted[11]
    
    print(f"\n  📊 Parsed fields:")
    print(f"     AppNonce:   {AppNonce.hex()}")
    print(f"     NetID:      {NetID.hex()}")
    print(f"     DevAddr:    {DevAddr_recv.hex()}")
    print(f"     DLSettings: 0x{DLSettings:02x}")
    print(f"     RxDelay:    {RxDelay}")
    
    # MIC check
    msg_to_mic = bytearray([mhdr]) + decrypted[:-4]
    mic_recv = decrypted[-4:]
    
    cmac = CMAC.new(AppKey, ciphermod=AES)
    cmac.update(msg_to_mic)
    mic_calc = cmac.digest()[:4]
    
    print(f"\n  🔐 MIC Verification:")
    print(f"     Received:   {mic_recv.hex()}")
    print(f"     Calculated: {mic_calc.hex()}", end="")
    
    if mic_recv != mic_calc:
        print(f" ❌ MISMATCH")
        print(f"\n  ⚠️  KEY MISMATCH DETECTED!")
        print(f"      The AppKey in your device doesn't match ChirpStack!")
        print(f"\n  🔧 Action Required:")
        print(f"      1. Go to ChirpStack device configuration")
        print(f"      2. Verify AppKey is: {AppKey.hex()}")
        print(f"      3. If wrong, update it and try again")
        print(f"      4. If correct, try deleting and recreating the device")
        return False
    
    print(f" ✓ VALID!")
    
    # Derive session keys
    NwkSKey = derive_session_key(AppKey, 0x01, AppNonce, NetID, dev_nonce_bytes)
    AppSKey = derive_session_key(AppKey, 0x02, AppNonce, NetID, dev_nonce_bytes)
    DevAddr = DevAddr_recv
    
    print(f"\n  🔑 Session Keys Derived:")
    print(f"     NwkSKey: {NwkSKey.hex()}")
    print(f"     AppSKey: {AppSKey.hex()}")
    print(f"\n  ✅ JOIN SUCCESSFUL!")
    
    return True

def join_on_channel(join_channel, attempt_num):
    """Attempt join on specific channel"""
    
    print(f"\n{'='*70}")
    print(f"Attempt #{attempt_num}: {join_channel/1e6:.1f} MHz")
    print(f"{'='*70}")
    
    dev_nonce = random.randint(0, 65535)
    dev_nonce_bytes = struct.pack('<H', dev_nonce)
    
    # Build Join Request
    mhdr = 0x00
    join_payload = bytearray()
    join_payload.append(mhdr)
    join_payload.extend(JoinEUI[::-1])
    join_payload.extend(DevEUI[::-1])
    join_payload.extend(dev_nonce_bytes)
    
    cmac = CMAC.new(AppKey, ciphermod=AES)
    cmac.update(bytes(join_payload))
    mic = cmac.digest()[:4]
    join_payload.extend(mic)
    
    print(f"\n📤 Sending Join Request:")
    print(f"   DevNonce: {dev_nonce} (0x{dev_nonce:04x})")
    print(f"   Payload:  {join_payload.hex()}")
    
    # Send
    lora.setFrequency(join_channel)
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)
    
    lora.beginPacket()
    lora.write(list(join_payload), len(join_payload))
    lora.endPacket()
    lora.wait()
    
    print(f"   ✓ Transmitted")
    
    # RX1 Window
    print(f"\n📥 RX1 Window (t+5s): {join_channel/1e6:.1f} MHz, SF10")
    lora.setFrequency(join_channel)
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, True)
    
    time.sleep(5)
    lora.request()
    
    start = time.time()
    while time.time() - start < 1.5:
        if lora.available():
            length = lora.available()
            join_accept_raw = bytes(lora.read(length))
            if try_decrypt_with_multiple_keys(join_accept_raw, dev_nonce_bytes):
                return True
        time.sleep(0.02)
    
    # RX2 Window
    print(f"\n📥 RX2 Window (t+6s): {RX2_FREQ/1e6:.1f} MHz, SF{RX2_SF}")
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
            if try_decrypt_with_multiple_keys(join_accept_raw, dev_nonce_bytes):
                return True
        time.sleep(0.02)
    
    print(f"\n  ⏱️  No Join Accept received in RX windows")
    return False

# Main execution
if __name__ == "__main__":
    input("\n⚡ Press Enter to start join attempts...")
    
    for i, channel in enumerate(JOIN_CHANNELS, 1):
        if join_on_channel(channel, i):
            print(f"\n{'='*70}")
            print(f"🎉 SUCCESS! Device joined on {channel/1e6:.1f} MHz")
            print(f"{'='*70}\n")
            sys.exit(0)
        
        if i < len(JOIN_CHANNELS):
            print(f"\n⏳ Waiting 5 seconds before next attempt...")
            time.sleep(5)
    
    print(f"\n{'='*70}")
    print(f"❌ FAILED - No successful join")
    print(f"{'='*70}")
    print(f"\n🔧 Next Steps:")
    print(f"   1. Verify AppKey in ChirpStack matches: {AppKey.hex()}")
    print(f"   2. Check ChirpStack 'Live LoRaWAN frames' tab")
    print(f"   3. Try deleting and recreating the device")
    print(f"   4. Check gateway logs: journalctl -u chirpstack-gateway-bridge -f")
    sys.exit(1)
