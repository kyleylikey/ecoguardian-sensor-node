import time
import board
import adafruit_dht

dht_device = adafruit_dht.DHT22(board.D4)  # GPIO4, pin 7

while True:
    try:
        temp = dht_device.temperature
        hum = dht_device.humidity
        print(f"Temp: {temp:.1f}°C  Humidity: {hum:.1f}%")
    except RuntimeError as e:
        print("Reading error:", e.args[0])
    time.sleep(2)
