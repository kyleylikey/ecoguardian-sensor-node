import serial
import time

# --- Helpers for NMEA parsing ---
def convert_to_decimal(coord, direction):
    """Convert NMEA coordinates into decimal degrees."""
    if not coord or coord == "0":
        return None
    if direction in ["N", "S"]:  # latitude
        degrees = int(coord[:2])
        minutes = float(coord[2:])
    else:  # longitude
        degrees = int(coord[:3])
        minutes = float(coord[3:])
    decimal = degrees + minutes / 60
    if direction in ["S", "W"]:
        decimal = -decimal
    return round(decimal, 6)

def parse_gngga(sentence):
    """Parse a GNGGA sentence and extract useful data."""
    parts = sentence.split(",")
    if len(parts) < 15:
        return None
    return {
        "time_utc": parts[1],
        "latitude": convert_to_decimal(parts[2], parts[3]),
        "longitude": convert_to_decimal(parts[4], parts[5]),
        "fix_quality": parts[6],
        "satellites": parts[7],
        "altitude_m": parts[9]
    }

# --- Serial setup ---
try:
    ser = serial.Serial("/dev/ttyS0", baudrate=9600, timeout=1)
    print("[INFO] Serial port opened successfully: /dev/ttyS0")
except Exception as e:
    print(f"[ERROR] Could not open serial port: {e}")
    exit(1)

print("[INFO] Listening for GPS data...")

last_info_time = 0
interval = 10  # seconds between INFO updates

try:
    while True:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue

        if line.startswith("$GNGGA"):
            gps_data = parse_gngga(line)
            if gps_data and gps_data["fix_quality"] != "0":
                now = time.time()
                if now - last_info_time >= interval:
                    print("[INFO] Parsed GPS Data:")
                    print(f"  Time (UTC): {gps_data['time_utc']}")
                    print(f"  Latitude : {gps_data['latitude']}")
                    print(f"  Longitude: {gps_data['longitude']}")
                    print(f"  Altitude : {gps_data['altitude_m']} m")
                    print(f"  Satellites: {gps_data['satellites']}")
                    print("-----------")
                    last_info_time = now
            else:
                print("[WARN] No GPS fix yet. Possible reasons:")
                print("  - Wiring issue (TX/RX swapped, missing GND)")
                print("  - A9G not powered correctly")
                print("  - GPS needs more time to lock (try outdoors, wait 1–2 mins)")
                time.sleep(1)  # slow down warnings
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n[INFO] GPS reading stopped by user.")
    ser.close()
