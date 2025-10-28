import RPi.GPIO as GPIO

# Use BCM numbering
GPIO.setmode(GPIO.BCM)

# LoRa pins according to your board_config
lora_pins = {
    "DIO0": 25,
    "DIO1": 24,
    "DIO2": 23,
    "DIO3": 16,
    "LED": 18,
    "SWITCH": 4,
    "CS": 8,      # SPI CE0
    "SCK": 11,    # SPI SCLK
    "MOSI": 10,   # SPI MOSI
    "MISO": 9     # SPI MISO
}

def check_pin(pin):
    try:
        # Try setting up as input to see if it's available
        GPIO.setup(pin, GPIO.IN)
        return True
    except RuntimeError as e:
        print(f"Pin {pin} busy or unavailable: {e}")
        return False

print("Checking LoRa GPIO pins...\n")
for name, pin in lora_pins.items():
    free = check_pin(pin)
    print(f"{name} (GPIO{pin}): {'Free' if free else 'Busy'}")

GPIO.cleanup()
