import serial
import time

# Open serial port
try:
    ser = serial.Serial('/dev/ttyS0', baudrate=115200, timeout=1)
    print("[INFO] Serial port opened successfully: /dev/ttyS0")
except Exception as e:
    print("[ERROR] Could not open serial port /dev/ttyS0")
    print("Details:", e)
    exit(1)

def send_command(cmd, delay=1):
    """Send AT command to A9G and return response"""
    print(f"[DEBUG] Sending command: {cmd}")
    ser.write((cmd + "\r\n").encode())  # send with CR+LF
    time.sleep(delay)
    response = ser.read(200).decode(errors="ignore").strip()
    
    if response:
        print(f"[DEBUG] Raw response: {response}")
    else:
        print("[WARN] No response received. (Check wiring, GPS power, or AT+GPS=1)")
    
    return response

# Enable GPS
print("[INFO] Enabling GPS module...")
resp = send_command("AT+GPS=1", 2)
if not resp:
    print("[WARN] No response to AT+GPS=1. Module may not be connected or powered.")
else:
    print("[INFO] GPS module responded to AT+GPS=1")

# Loop to get GPS location
while True:
    print("[INFO] Requesting GPS location (AT+LOCATION=2)...")
    response = send_command("AT+LOCATION=2", 3)
    
    if not response:
        print("[WARN] Still no GPS data. Possible reasons:")
        print("  - TX/RX wiring swapped or missing GND")
        print("  - A9G not powered correctly")
        print("  - GPS not yet fixed (try outdoors, may take 1–2 mins)")
    else:
        print("[INFO] GPS Response:", response)
    
    time.sleep(5)
