
import time
import board
import adafruit_dht

# Initialize DHT22 sensor on GPIO4 (Physical Pin 7)
dht_device = adafruit_dht.DHT22(board.D4, use_pulseio=False)

# Optional: Temperature and humidity thresholds for forest fire conditions
TEMP_WARNING = 35.0     # °C - Elevated temperature
TEMP_DANGER = 40.0      # °C - High fire risk
HUMIDITY_WARNING = 30.0 # % - Low humidity increases fire risk
HUMIDITY_DANGER = 20.0  # % - Very dry, high fire risk

print("DHT22 Temperature & Humidity Sensor Test")
print("=" * 50)

while True:
    try:
        # Read temperature and humidity
        temperature_c = dht_device.temperature
        humidity = dht_device.humidity
        
        # Check if readings are valid
        if temperature_c is not None and humidity is not None:
            # Determine fire risk based on conditions
            temp_status = "Normal"
            humidity_status = "Normal"
            
            if temperature_c >= TEMP_DANGER:
                temp_status = "DANGER - High Temp"
            elif temperature_c >= TEMP_WARNING:
                temp_status = "WARNING - Elevated"
            
            if humidity <= HUMIDITY_DANGER:
                humidity_status = "DANGER - Very Dry"
            elif humidity <= HUMIDITY_WARNING:
                humidity_status = "WARNING - Low"
            
            # Display readings
            print(f"Temperature: {temperature_c:.1f}°C ({temp_status}) | "
                  f"Humidity: {humidity:.1f}% ({humidity_status})")
        else:
            print("Failed to retrieve data from sensor. Retrying...")
        
    except RuntimeError as error:
        # DHT sensors occasionally fail to read, this is normal
        print(f"Reading error: {error.args[0]}")
    except Exception as error:
        dht_device.exit()
        raise error
    
    # DHT22 has a 2-second minimum read interval
    time.sleep(2)
