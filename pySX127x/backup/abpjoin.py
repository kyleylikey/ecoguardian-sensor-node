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

# --- ABP Keys and addresses ---
DevAddr = bytes.fromhex("017f6070")  # DevAddr registered in ChirpStack
NwkSKey = bytes.fromhex("6189ffdd05b0c1d9f67d6e298f1f5021")  # NwkSKey
AppSKey = bytes.fromhex("187276a7872f6e6b1e116fb30d9a1c53")  # AppSKey

FCnt = 0  # start frame counter
FPort = 1  # application port

def aes128_encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(plaintext)

def encrypt_payload(app_skey, dev_addr, fcnt, payload):
    """Encrypt application payload for ABP uplink"""
    size = len(payload)
    enc_payload = bytearray()
    block_a = bytearray(16)
    block_a[0] = 0x01
    block_a[5] = 0x00
    block_a[6:10] = dev_addr[::-1]  # DevAddr little endian
    block_a[10:12] = struct.pack('<H', fcnt)
    block_a[15] = 0x01
    cipher = AES.new(app_skey, AES.MODE_ECB)

    for i in range(size):
        block_a[15] = i // 16 + 1
        s = cipher.encrypt(bytes(block_a))
        enc_payload.append(payload[i] ^ s[i % 16])

    return enc_payload

def calculate_mic(nwkskey, dev_addr, fcnt, fport, enc_payload):
    """Compute LoRaWAN MIC for ABP uplink"""
    msg = bytearray()
    msg.append(0x40)  # MHDR: unconfirmed data up
    msg.extend(dev_addr[::-1])
    msg.append(0x00)  # FCtrl
    msg.extend(struct.pack('<H', fcnt))
    msg.append(fport)
    msg.extend(enc_payload)

    cmac = CMAC.new(nwkskey, ciphermod=AES)
    cmac.update(msg)
    return cmac.digest()[:4]

def send_uplink(payload_bytes):
    global FCnt
    enc_payload = encrypt_payload(AppSKey, DevAddr, FCnt, payload_bytes)
    mic = calculate_mic(NwkSKey, DevAddr, FCnt, FPort, enc_payload)

    frame = bytearray()
    frame.append(0x40)  # MHDR
    frame.extend(DevAddr[::-1])  # DevAddr
    frame.append(0x00)  # FCtrl
    frame.extend(struct.pack('<H', FCnt))  # FCnt
    frame.append(FPort)
    frame.extend(enc_payload)
    frame.extend(mic)

    lora.standby()
    lora.beginPacket()
    lora.write(list(frame), len(frame))
    lora.endPacket()
    lora.wait()

    print(f"Uplink sent: {frame.hex()} at {time.strftime('%H:%M:%S')}")
    FCnt += 1

# --- Main Loop ---
if __name__ == "__main__":
    payload = b'\x01\x02\x03\x04'  # example sensor data
    while True:
        send_uplink(payload)
        time.sleep(5)
