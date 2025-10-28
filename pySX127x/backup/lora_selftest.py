import sys
from time import sleep
from SX127x.LoRa import LoRa
from SX127x.board_config import BOARD

# Setup board
BOARD.setup()

class LoRaSelfTest(LoRa):
    def __init__(self, verbose=False):
        super(LoRaSelfTest, self).__init__(verbose)
        self.set_mode(MODE.SLEEP)
        self.set_dio_mapping([0,0,0,0,0,0])

    def on_tx_done(self):
        print("[OK] TX Done interrupt received")
        self.clear_irq_flags(TxDone=1)
        self.set_mode(MODE.STDBY)

    def on_rx_done(self):
        print("[OK] RX Done interrupt received")
        payload = self.read_payload(nocheck=True)
        print("Payload:", bytes(payload).decode(errors="ignore"))
        self.clear_irq_flags(RxDone=1)
        self.set_mode(MODE.STDBY)

# ---- Main Test ----
try:
    print("LoRa SX127x Self-Test Starting...")

    lora = LoRaSelfTest(verbose=True)

    # Set some basic config (AS923_3 freq as example)
    lora.set_freq(916.5)
    lora.set_spreading_factor(7)
    lora.set_bandwidth(BW.BW125)
    lora.set_coding_rate(CODING_RATE.CR4_5)
    lora.set_preamble(8)
    lora.set_pa_config(pa_select=1)

    print("LoRa module configured.")
    print("Testing TX...")

    # Send a simple test packet
    test_message = "LORA-TEST"
    payload = [ord(c) for c in test_message]
    lora.write_payload(payload)
    lora.set_mode(MODE.TX)

    sleep(2)

    # Switch to RX mode to see if module enters listening
    print("Switching to RX mode for check...")
    lora.reset_ptr_rx()
    lora.set_mode(MODE.RXCONT)

    print("Module is in RX mode. If hardware is OK, no errors should occur.")
    print("Press Ctrl+C to exit.")

    while True:
        sleep(1)

except KeyboardInterrupt:
    print("\nExiting self-test.")
    sys.exit(0)
