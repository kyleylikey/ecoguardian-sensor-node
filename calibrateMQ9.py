import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import statistics

# ==== USER SETTINGS ====
CALIBRATION_DURATION_HOURS = 4         # total calibration time
WARMUP_MINUTES = 15                    # time to ignore readings at start
SAMPLE_INTERVAL_SECONDS = 5            # how often to read Rs
OUTPUT_FILE = "R0.txt"
# ========================

# Setup ADC
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)
chan = AnalogIn(ads, 0)

# Sensor constants
VCC = 5.0     # supply voltage to sensor
RL = 10.0     # kΩ load resistor

def get_resistance(voltage):
    if voltage <= 0:
        return None
    return RL * (VCC - voltage) / voltage  # kΩ

total_seconds = CALIBRATION_DURATION_HOURS * 3600
warmup_seconds = WARMUP_MINUTES * 60

rs_samples = []

print(f"=== MQ-9 Calibration Started ===")
print(f"Warmup period: {WARMUP_MINUTES} min")
print(f"Total calibration time: {CALIBRATION_DURATION_HOURS} hours\n")

start_time = time.time()

while True:
    elapsed = time.time() - start_time
    vout = chan.voltage
    rs = get_resistance(vout)

    if rs is not None:
        if elapsed > warmup_seconds:
            rs_samples.append(rs)
            print(f"[{elapsed/60:.1f} min] Rs = {rs:.2f} kΩ (collected {len(rs_samples)})")
        else:
            print(f"[{elapsed/60:.1f} min] Warming up... Rs = {rs:.2f} kΩ")

    if elapsed >= total_seconds:
        break

    time.sleep(SAMPLE_INTERVAL_SECONDS)

# Compute R0
if len(rs_samples) > 0:
    R0 = statistics.mean(rs_samples)
    print(f"\n=== Calibration complete! ===")
    print(f"Calculated R0 = {R0:.2f} kΩ (avg of {len(rs_samples)} samples)")

    with open(OUTPUT_FILE, "w") as f:
        f.write(f"{R0:.4f}")
    print(f"R0 saved to {OUTPUT_FILE}")
else:
    print("Error: No valid Rs samples collected!")

