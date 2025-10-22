import time
import struct
from LoRaRF import SX127x
from Crypto.Cipher import AES
from Crypto.Hash import CMAC

# --- Radio Setup ---
lora = SX127x()
lora.begin()

FREQ = 916800000
SF = 10
BW = 125000
CR = 5
INVERT_IQ = True  # ChirpStack uses polarity inversion

lora.setLoRaModulation(SF, BW, CR, INVERT_IQ)
lora.setFrequency(FREQ)
lora.setTxPower(14, 1)
lora.setLoRaPacket(lora.HEADER_EXPLICIT, 8, 255, True, False)
print("Radio initialized on 916.8 MHz.")

# --- ABP Keys and addresses ---
DevAddr = bytes.fromhex("017f6070")  # DevAddr registered in ChirpStack
NwkSKey = bytes.fromhex("6189ffdd05b0c1d9f67d6e298f1f5021")  # NwkSKey
AppSKey = bytes.fromhex("187276a7872f6e6b1e116fb30d9a1c53")  # AppSKey

FCnt = 0  # start frame counter
FPort = 1  # application port


def encrypt_payload(app_skey, dev_addr, fcnt, payload):
    """
    ### FIXED ###
    Encrypt application payload for ABP uplink (LoRaWAN 1.0.x)
    This version uses the correct 32-bit frame counter.
    """
    size = len(payload)
    enc_payload = bytearray()
    
    # Create the 'A' block for encryption
    block_a = bytearray(16)
    block_a[0] = 0x01                 # Block type
    # bytes 1-4 are 0x00 (already set)
    block_a[5] = 0x00                 # Dir (0 = uplink)
    block_a[6:10] = dev_addr[::-1]    # DevAddr (little-endian)
    
    # --- CRITICAL FIX #1 ---
    # Use the full 32-bit Frame Counter (little-endian)
    # Your old code used '<H' (16-bit)
    block_a[10:14] = struct.pack('<L', fcnt) 
    
    # byte 14 is 0x00 (already set)
    
    cipher = AES.new(app_skey, AES.MODE_ECB)
    
    # Generate the keystream (S) by encrypting 'A' blocks
    keystream = b''
    num_blocks = (size + 15) // 16 # Calculate number of 16-byte blocks needed
    for i in range(num_blocks):
        block_a[15] = i + 1  # Set block counter (starts at 1)
        keystream += cipher.encrypt(bytes(block_a))

    # XOR the payload with the generated keystream
    for i in range(size):
        enc_payload.append(payload[i] ^ keystream[i])

    return enc_payload


def calculate_mic(nwkskey, dev_addr, fcnt, fport, enc_payload):
    """
    ### FIXED ###
    Compute LoRaWAN MIC for ABP uplink (LoRaWAN 1.0.x)
    This version uses the correct B0 block as required by the spec.
    """
    
    # Create the message (FHDR + FPort + FRMPayload)
    msg = bytearray()
    msg.append(0x40)                  # MHDR (unconfirmed data up)
    msg.extend(dev_addr[::-1])        # DevAddr (little-endian)
    msg.append(0x00)                  # FCtrl
    
    # The FCnt in the *frame header* is 16-bit (we use the 16 LSBs)
    msg.extend(struct.pack('<H', fcnt & 0xFFFF))
    
    msg.append(fport)
    msg.extend(enc_payload)

    # --- CRITICAL FIX #2 ---
    # Create the B0 block required for MIC calculation
    b0 = bytearray(16)
    b0[0] = 0x49
    # bytes 1-4 are 0x00
    b0[5] = 0x00                      # Dir (0 = uplink)
    b0[6:10] = dev_addr[::-1]         # DevAddr (little-endian)
    
    # The FCnt in the *B0 block* is the full 32-bit counter
    b0[10:14] = struct.pack('<L', fcnt)
    
    # byte 14 is 0x00
    b0[15] = len(msg)                 # Message length
    
    # Calculate CMAC over (B0 + msg)
    cmac = CMAC.new(nwkskey, ciphermod=AES)
    cmac.update(b0 + msg)
    
    # The MIC is the first 4 bytes of the digest
    return cmac.digest()[:4]


def send_uplink(payload_bytes):
    global FCnt
    
    print(f"Encrypting payload with FCnt={FCnt}...")
    enc_payload = encrypt_payload(AppSKey, DevAddr, FCnt, payload_bytes)
    
    print("Calculating MIC...")
    mic = calculate_mic(NwkSKey, DevAddr, FCnt, FPort, enc_payload)

    # Build the final frame to transmit
    frame = bytearray()
    frame.append(0x40)                      # MHDR
    frame.extend(DevAddr[::-1])             # DevAddr (little-endian)
    frame.append(0x00)                      # FCtrl
    
    # The final frame on the air uses the 16-bit FCnt
    frame.extend(struct.pack('<H', FCnt & 0xFFFF)) # FCnt (little-endian, 16-bit)
    
    # The FPort MUST be in the frame
    frame.append(FPort)
    
    frame.extend(enc_payload)
    frame.extend(mic)

    lora.standby()
    lora.beginPacket()
    lora.write(list(frame), len(frame))
    lora.endPacket()
    lora.wait()

    print(f"Uplink sent: {frame.hex()} at {time.strftime('%H:%M:%S')}")
    
    # Increment the 32-bit frame counter
    FCnt += 1
    # NOTE: In a real project, you must save FCnt to a file here
    # and read it back when the script starts.


# --- Main Loop ---
if __name__ == "__main__":
    payload = b'\x01\x02\x03\x04'  # example sensor data
    while True:
        send_uplink(payload)
        
        # A 5-second sleep is TOO FAST for SF10.
        # It violates the 1% duty cycle.
        print("Sleeping for 30 seconds to respect duty cycle...")
        time.sleep(30)
