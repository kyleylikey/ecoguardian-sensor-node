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

JOIN_FREQ = 916800000
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
print("LoRaWAN OTAA Timing Diagnostic Tool")
print("="*70)
print("\nThis will listen continuously around RX1/RX2 windows")
print("to capture ALL packets and help diagnose timing issues.\n")
print(f"DevEUI:  {DevEUI.hex()}")
print(f"JoinEUI: {JoinEUI.hex()}")
print(f"AppKey:  {AppKey.hex()}")
print("="*70)

def aes128_encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)

def decrypt_join_accept(encrypted_payload):
    """Decrypt Join Accept (AES-ECB)"""
    cipher = AES.new(AppKey, AES.MODE_ECB)
    return cipher.decrypt(encrypted_payload)

def verify_join_accept_mic(decrypted_payload, mic):
    """Verify Join Accept MIC using AppKey and DevEUI"""
    cmac = CMAC.new(AppKey, ciphermod=AES)
    cmac.update(decrypted_payload)
    calc_mic = cmac.digest()[:4]
    return calc_mic == mic

def analyze_packet(packet, timestamp, window_name):
    """Analyze received packets and verify Join Accept"""
    if len(packet) < 1:
        return False
    
    mhdr = packet[0]
    mtype = (mhdr >> 5) & 0x07
    
    mtype_names = {
        0: "Join Request",
        1: "Join Accept", 
        2: "Unconfirmed Data Up",
        3: "Unconfirmed Data Down",
        4: "Confirmed Data Up",
        5: "Confirmed Data Down",
        6: "RFU",
        7: "Proprietary"
    }
    
    print(f"\n  [{window_name}] t+{timestamp:.2f}s: Packet received ({len(packet)} bytes)")
    print(f"    Hex: {packet.hex()}")
    print(f"    MHDR: 0x{mhdr:02x} → {mtype_names.get(mtype, 'Unknown')}")
    
    if mtype == 1:  # Join Accept
        print("    ✓ This is a Join Accept! Attempting decrypt...")
        decrypted = decrypt_join_accept(packet[1:-4])
        mic_received = packet[-4:]
        print(f"    Decrypted payload: {decrypted.hex()}")
        if verify_join_accept_mic(decrypted, mic_received):
            print("    ✅ MIC verified! Valid Join Accept.")
            return True
        else:
            print("    ❌ MIC verification failed.")
    
    return False

def send_join_request():
    """Send Join Request"""
    dev_nonce = random.randint(0, 65535)
    dev_nonce_bytes = struct.pack('<H', dev_nonce)
    
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
    
    print(f"\n📤 Sending Join Request on {JOIN_FREQ/1e6:.1f} MHz")
    print(f"   DevNonce: {dev_nonce} (0x{dev_nonce:04x})")
    print(f"   Payload:  {join_payload.hex()}")
    
    lora.setFrequency(JOIN_FREQ)
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)
    
    lora.standby()
    time.sleep(0.1)
    
    tx_time = time.time()
    lora.beginPacket()
    lora.write(list(join_payload), len(join_payload))
    lora.endPacket()
    lora.wait()
    
    print(f"   ✓ Transmitted at {time.strftime('%H:%M:%S', time.localtime(tx_time))}")
    
    # Clear buffers
    lora.standby()
    time.sleep(0.2)
    lora.sleep()
    time.sleep(0.05)
    lora.standby()
    
    return tx_time, dev_nonce_bytes

def listen_extended_windows(tx_time):
    """Listen RX1 and RX2 with inversion and MIC check"""
    print(f"\n{'='*70}\nExtended Listening Windows\n{'='*70}")
    
    packets_rx1, packets_rx2 = [], []
    
    # --- RX1 ---
    rx1_start = tx_time + 4.8
    rx1_end = tx_time + 6.3
    lora.setFrequency(JOIN_FREQ)
    lora.setLoRaModulation(10, 125000, 5, True)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, True)
    
    wait_time = rx1_start - time.time()
    if wait_time > 0:
        time.sleep(wait_time)
    lora.request()
    
    while time.time() < rx1_end:
        if lora.available():
            length = lora.available()
            packet = bytes(lora.read(length))
            elapsed = time.time() - tx_time
            packets_rx1.append((packet, elapsed))
            analyze_packet(packet, elapsed, "RX1")
        time.sleep(0.02)
    
    if not packets_rx1:
        print("   ℹ️  No packets in RX1 window")
    
    # --- RX2 ---
    rx2_start = tx_time + 5.0
    rx2_end = tx_time + 9.0
    lora.standby()
    time.sleep(0.1)
    
    lora.setFrequency(RX2_FREQ)
    lora.setLoRaModulation(RX2_SF, 125000, 5, True)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, True)
    
    wait_time = rx2_start - time.time()
    if wait_time > 0:
        time.sleep(wait_time)
    lora.request()
    
    while time.time() < rx2_end:
        if lora.available():
            length = lora.available()
            packet = bytes(lora.read(length))
            elapsed = time.time() - tx_time
            packets_rx2.append((packet, elapsed))
            analyze_packet(packet, elapsed, "RX2")
        time.sleep(0.02)
    
    if not packets_rx2:
        print("   ℹ️  No packets in RX2 window")
    
    return packets_rx1, packets_rx2

# --- Main ---
if __name__ == "__main__":
    input("\n⚡ Press Enter to send Join Request and listen for response...\n")
    tx_time, _ = send_join_request()
    rx1_packets, rx2_packets = listen_extended_windows(tx_time)
    
    print(f"\n{'='*70}\nSummary\n{'='*70}")
    print(f"Total packets in RX1 window: {len(rx1_packets)}")
    print(f"Total packets in RX2 window: {len(rx2_packets)}")
    
    if not rx1_packets and not rx2_packets:
        print("\n❌ NO PACKETS RECEIVED AT ALL")
    else:
        print("\n✓ Packets received. Join Accepts will be validated above.")
