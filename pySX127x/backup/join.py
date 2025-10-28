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

JOIN_FREQ = 916800000  # Focus on 916.8 MHz where gateway responds
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

def analyze_packet(packet, timestamp, window_name):
    """Analyze any received packet"""
    if len(packet) < 1:
        return
    
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
    print(f"    Hex:  {packet.hex()}")
    print(f"    MHDR: 0x{mhdr:02x} → {mtype_names.get(mtype, 'Unknown')}")
    
    # If it looks like a Join Accept, try to decrypt
    if mtype == 1:  # Join Accept
        print(f"    ✓ This is a Join Accept! Attempting decrypt...")
        return True
    
    return False

def send_join_request():
    """Send join request and return details"""
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
    
    print(f"\n📤 Sending Join Request on {JOIN_FREQ/1e6:.1f} MHz")
    print(f"   DevNonce: {dev_nonce} (0x{dev_nonce:04x})")
    print(f"   Payload:  {join_payload.hex()}")
    
    # Send
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
    """Listen across extended RX1 and RX2 windows"""
    
    print(f"\n{'='*70}")
    print("Extended Listening Windows")
    print("="*70)
    
    # RX1 Extended Window: Listen from t+4s to t+7s on JOIN_FREQ
    print(f"\n📥 RX1 Extended Window: {JOIN_FREQ/1e6:.1f} MHz, SF10")
    print(f"   Listening from t+4.0s to t+7.0s (3 second window)")
    
    lora.setFrequency(JOIN_FREQ)
    lora.setLoRaModulation(10, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, True)
    
    # Wait until t+4s
    wait_time = 4.0 - (time.time() - tx_time)
    if wait_time > 0:
        time.sleep(wait_time)
    
    lora.request()
    
    end_time = tx_time + 7.0
    packets_rx1 = []
    
    while time.time() < end_time:
        if lora.available():
            length = lora.available()
            packet = bytes(lora.read(length))
            elapsed = time.time() - tx_time
            packets_rx1.append((packet, elapsed))
            analyze_packet(packet, elapsed, "RX1")
        time.sleep(0.02)
    
    if not packets_rx1:
        print(f"   ℹ️  No packets in RX1 window")
    
    # RX2 Extended Window: Listen from t+5s to t+9s on RX2_FREQ
    print(f"\n📥 RX2 Extended Window: {RX2_FREQ/1e6:.1f} MHz, SF{RX2_SF}")
    print(f"   Listening from t+5.0s to t+9.0s (4 second window)")
    
    lora.standby()
    time.sleep(0.1)
    
    lora.setFrequency(RX2_FREQ)
    lora.setLoRaModulation(RX2_SF, 125000, 5, False)
    lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, True)
    
    # Wait until t+5s
    wait_time = 5.0 - (time.time() - tx_time)
    if wait_time > 0:
        time.sleep(wait_time)
    
    lora.request()
    
    end_time = tx_time + 9.0
    packets_rx2 = []
    
    while time.time() < end_time:
        if lora.available():
            length = lora.available()
            packet = bytes(lora.read(length))
            elapsed = time.time() - tx_time
            packets_rx2.append((packet, elapsed))
            analyze_packet(packet, elapsed, "RX2")
        time.sleep(0.02)
    
    if not packets_rx2:
        print(f"   ℹ️  No packets in RX2 window")
    
    return packets_rx1, packets_rx2

# Main execution
if __name__ == "__main__":
    input("\n⚡ Press Enter to send Join Request and listen for response...\n")
    
    # Send join request
    tx_time, dev_nonce_bytes = send_join_request()
    
    # Listen with extended windows
    rx1_packets, rx2_packets = listen_extended_windows(tx_time)
    
    # Summary
    print(f"\n{'='*70}")
    print("Summary")
    print("="*70)
    print(f"Total packets in RX1 window: {len(rx1_packets)}")
    print(f"Total packets in RX2 window: {len(rx2_packets)}")
    
    if not rx1_packets and not rx2_packets:
        print("\n❌ NO PACKETS RECEIVED AT ALL")
        print("\nPossible causes:")
        print("  1. Gateway is not transmitting the Join Accept")
        print("  2. Gateway is using wrong frequency")
        print("  3. Gateway TX power too low / antenna issue")
        print("  4. RX sensitivity issue on end device")
        print("\nNext steps:")
        print("  - Check ChirpStack 'Live LoRaWAN frames' for downlink")
        print("  - Verify gateway is transmitting on correct frequency")
        print("  - Check gateway antenna connection")
    else:
        print("\n✓ Packets were received, but none were valid Join Accepts")
        print("\nPossible causes:")
        print("  1. Receiving other devices' traffic")
        print("  2. Join Accept on different frequency than expected")
        print("  3. Timing offset (try adjusting RX1 delay in ChirpStack)")
        print("\nNext steps:")
        print("  - Check what frequency ChirpStack is using for Join Accept")
        print("  - Verify RX1 delay setting (should be 5 seconds)")
        print("  - Check if gateway has correct regional parameters")
