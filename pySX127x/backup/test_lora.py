#!/usr/bin/env python3

"""
Unit tests for pySX127x LoRa module.
GPIO interrupt detection is disabled for testing purposes.
"""

from SX127x.LoRa import *
from SX127x import board_config
import unittest

# ----------------------------------------------------------------------
# Disable GPIO event detection (DIO interrupts) for testing
# ----------------------------------------------------------------------
board_config.BOARD.add_events = lambda *args, **kwargs: None
board_config.BOARD.add_event_detect = lambda *args, **kwargs: None

# ----------------------------------------------------------------------
# Decorator to save and restore registers around a test
# ----------------------------------------------------------------------
def SaveState(reg_addr, n_registers=1):
    """Decorator: save/restore registers around a test call."""
    def decorator(func):
        def wrapper(self):
            reg_bkup = self.lora.get_register(reg_addr)
            func(self)
            self.lora.set_register(reg_addr, reg_bkup)
        return wrapper
    return decorator

# ----------------------------------------------------------------------
# LoRa subclass for tests (no IRQ needed)
# ----------------------------------------------------------------------
class LoRaNoIRQ(LoRa):
    def __init__(self, verbose=False):
        super().__init__(verbose)

# ----------------------------------------------------------------------
# Unit test class
# ----------------------------------------------------------------------
class TestSX127x(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from SX127x.board_config import BOARD
        BOARD.setup()
        cls.lora = LoRaNoIRQ(verbose=False)

    @classmethod
    def tearDownClass(cls):
        from SX127x.board_config import BOARD
        BOARD.teardown()

    def test_setter_getter(self):
        bkup = self.lora.get_payload_length()
        for l in [1, 50, 128, bkup]:
            self.lora.set_payload_length(l)
            self.assertEqual(self.lora.get_payload_length(), l)

    @SaveState(REG.LORA.OP_MODE)
    def test_mode(self):
        mode = self.lora.get_mode() & 0x7F  # mask LoRa bit
        for m in [MODE.STDBY, MODE.SLEEP, mode]:
            self.lora.set_mode(m)
            actual = self.lora.get_mode() & 0x7F  # mask top bit
            self.assertEqual(actual, m)

    @SaveState(REG.LORA.FR_MSB, n_registers=3)
    def test_set_freq(self):
        freq = self.lora.get_freq()
        for f in [433.5, 434.5, 434.0, freq]:
            self.lora.set_freq(f)
            self.assertEqual(self.lora.get_freq(), f)

    @SaveState(REG.LORA.MODEM_CONFIG_3)
    def test_set_agc_on(self):
        self.lora.set_agc_auto_on(True)
        self.assertEqual((self.lora.get_register(REG.LORA.MODEM_CONFIG_3) & 0b100) >> 2, 1)
        self.lora.set_agc_auto_on(False)
        self.assertEqual((self.lora.get_register(REG.LORA.MODEM_CONFIG_3) & 0b100) >> 2, 0)

    @SaveState(REG.LORA.MODEM_CONFIG_3)
    def test_set_low_data_rate_optim(self):
        self.lora.set_low_data_rate_optim(True)
        self.assertEqual((self.lora.get_register(REG.LORA.MODEM_CONFIG_3) & 0b1000) >> 3, 1)
        self.lora.set_low_data_rate_optim(False)
        self.assertEqual((self.lora.get_register(REG.LORA.MODEM_CONFIG_3) & 0b1000) >> 3, 0)

    @SaveState(REG.LORA.DIO_MAPPING_1, 2)
    def test_set_dio_mapping(self):
        dio_mapping = [1] * 6
        self.lora.set_dio_mapping(dio_mapping)
        self.assertEqual(self.lora.get_register(REG.LORA.DIO_MAPPING_1), 0b01010101)
        self.assertEqual(self.lora.get_register(REG.LORA.DIO_MAPPING_2), 0b01010000)
        self.assertEqual(self.lora.get_dio_mapping(), dio_mapping)

# ----------------------------------------------------------------------
# Run tests
# ----------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main(verbosity=2)
