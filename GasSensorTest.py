import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import math

# Setup ADS1115
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)
chan = AnalogIn(ads, ADS.P0)

# Constants
VCC = 5.0     # sensor powered at 5V
RL = 10.0     # kO load resistor on module
R0 = 10.0     # kO baseline resistance in clean air (calibrate this!)

def get_resistance(voltage):
    if voltage <= 0:
        return 999999  # avoid div by zero
    return RL * (VCC - voltage) / voltage

def get_ppm_co(Rs, R0):
    ratio = Rs / R0
    # Approx curve for CO (from datasheet graph, tuned)
    a = 100.0
    b = -1.5
    return a * pow(ratio, b)

while True:
    vout = chan.voltage
    Rs = get_resistance(vout)
    ppm = get_ppm_co(Rs, R0)
    print(f"Vout: {vout:.3f} V | Rs: {Rs:.2f} kO | CO: {ppm:.1f} ppm")
    time.sleep(1)

