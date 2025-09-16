#!/usr/bin/env python3
import sys
from time import sleep, time
from datetime import datetime
from SX127x.LoRa import *
from SX127x.board_config import BOARD

# --- Setup Board ---
BOARD.setup()

class LoRaTimeSender(LoRa):
    tx_counter = 0

    def __init__(self, verbose=False):
        super(LoRaTimeSender, self).__init__(verbose)
        self.set_mode(MODE.SLEEP)
        self.set_dio_mapping([1,0,0,0,0,0])

    def send_message(self, message):
        payload = [ord(c) for c in message]
        self.write_payload(payload)
        BOARD.led_on()
        self.set_mode(MODE.TX)
        sleep(0.1)           # give time for TX
        BOARD.led_off()
        self.tx_counter += 1
        print(f"TX #{self.tx_counter}: {message}")

# --- Initialize LoRa ---
lora = LoRaTimeSender(verbose=True)

# Radio config (AS923_3)
lora.set_mode(MODE.STDBY)
lora.set_freq(916.5)                         # MHz
lora.set_spreading_factor(7)                 # SF7
lora.set_bw(BW.BW125)                        # 125 kHz
lora.set_coding_rate(CODING_RATE.CR4_5)      # 4/5
lora.set_preamble(8)
lora.set_sync_word(0x34)
lora.set_pa_config(pa_select=1, output_power=14)

print("Starting LoRa Time Sender at 916.5 MHz for 10 seconds...")

# --- Send packets for 10 seconds ---
start_time = time()
while time() - start_time < 5:
    current_time = datetime.now().strftime("%H:%M:%S")
    lora.send_message(current_time)
    sleep(1)

print("Done sending packets.")
BOARD.teardown()

