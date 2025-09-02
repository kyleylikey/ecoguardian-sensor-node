import serial
import time

# Common baud rates to test
BAUD_RATES = [9600, 19200, 38400, 57600, 115200]

def test_a9g(port="/dev/serial0"):
    for baud in BAUD_RATES:
        print("=" * 40)
        print(f"Testing baud rate: {baud}")
        try:
            ser = serial.Serial(port, baud, timeout=1)
            time.sleep(2)  # wait for port to settle

            # Send basic AT command
            ser.write(b"AT\r\n")
            time.sleep(1)
            reply = ser.read_all().decode(errors="ignore")
            print("Reply to AT:", repr(reply))

            # If we got "OK", continue testing GPS
            if "OK" in reply:
                print(f"A9G is alive at {baud} baud!\n")

                # Turn on GPS
                ser.write(b"AT+GPS=1\r\n")
                time.sleep(2)
                print("Reply to AT+GPS=1:", ser.read_all().decode(errors="ignore"))

                # Wait a bit for GPS startup
                print("Waiting for GPS to initialize...")
                time.sleep(5)

                # Request location
                ser.write(b"AT+LOCATION=2\r\n")
                time.sleep(2)
                print("Reply to AT+LOCATION=2:", ser.read_all().decode(errors="ignore"))

                ser.close()
                return  # Stop after first success

            ser.close()
        except Exception as e:
            print(f"Error at {baud}: {e}")

    print("\nNo response from A9G at any tested baud rate.\n")
    print("Check power (3.7–4.2 V, >=2 A bursts), wiring (TX/RX cross, common GND),")
    print("and whether PWRKEY needs to be pressed to boot your module.")

if __name__ == "__main__":
    test_a9g()
