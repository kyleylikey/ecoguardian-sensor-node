import serial
import time

def test_a9g(port="/dev/serial0", baud=9600):
    print("=" * 40)
    print(f"Testing A9G at {baud} baud")
    try:
        ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2)  # wait for port to settle

        # Send basic AT command
        ser.write(b"AT\r\n")
        time.sleep(1)
        raw = ser.read_all()
        print("Raw reply to AT:", raw)
        print("Decoded reply:", raw.decode(errors="ignore"))

        if b"OK" in raw:
            print("A9G is alive!\n")

            # Turn on GPS
            ser.write(b"AT+GPS=1\r\n")
            time.sleep(2)
            raw = ser.read_all()
            print("Raw reply to AT+GPS=1:", raw)
            print("Decoded reply:", raw.decode(errors="ignore"))

            # Wait a bit for GPS startup
            print("Waiting for GPS to initialize...")
            time.sleep(5)

            # Request location
            ser.write(b"AT+LOCATION=2\r\n")
            time.sleep(2)
            raw = ser.read_all()
            print("Raw reply to AT+LOCATION=2:", raw)
            print("Decoded reply:", raw.decode(errors="ignore"))

        ser.close()
    except Exception as e:
        print(f"Error opening port: {e}")

if __name__ == "__main__":
    test_a9g()
