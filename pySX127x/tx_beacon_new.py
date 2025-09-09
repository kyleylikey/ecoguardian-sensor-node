import sys
from time import sleep
from SX127x.LoRa import *
from SX127x.LoRaArgumentParser import LoRaArgumentParser
from SX127x.board_config import BOARD

BOARD.setup()

parser = LoRaArgumentParser("LoRa TX Beacon")
parser.add_argument('--single', '-S', dest='single', default=False, action="store_true",
                    help="Send only one packet and exit")
parser.add_argument('--wait', '-w', dest='wait', default=1, type=int,
                    help="Seconds to wait between packets")

class LoRaBeacon(LoRa):

    tx_counter = 0

    def __init__(self, verbose=False):
        super(LoRaBeacon, self).__init__(verbose)
        self.set_mode(MODE.SLEEP)
        self.set_dio_mapping([1,0,0,0,0,0])

    def on_tx_done(self):
        global args
        self.set_mode(MODE.STDBY)
        self.clear_irq_flags(TxDone=1)
        self.tx_counter += 1
        print(f"TX #{self.tx_counter}")
        sys.stdout.flush()
        if args.single:
            sys.exit(0)
        BOARD.led_off()
        sleep(args.wait)
        self.send_message("Hello")

    def send_message(self, message):
        payload = [ord(c) for c in message]
        self.write_payload(payload)
        BOARD.led_on()
        self.set_mode(MODE.TX)

    def start(self):
        global args
        self.tx_counter = 0
        self.send_message("Hello")
        while True:
            sleep(1)

# --- main ---
lora = LoRaBeacon(verbose=False)
args = parser.parse_args(lora)

# Radio config (AS923_3)
lora.set_freq(916.5)                         # MHz
lora.set_spreading_factor(7)                 # SF7
lora.set_bw(BW.BW125)                 # 125 kHz
lora.set_coding_rate(CODING_RATE.CR4_5)      # 4/5
lora.set_preamble(8)
lora.set_sync_word(0x34)

lora.set_pa_config(pa_select=1, output_power=14)

print("Starting LoRa TX Beacon at 916.5 MHz...")
lora.start()

