"""
Basic connectivity smoke-test.

Opens two independent connections to the Red Pitaya:
  - RPSynthTransport  (Paramiko SSH + daemon socket) → ADF4355 SPI
  - pyrpl.Pyrpl                                      → scope / ADC
"""

import os
import sys

HOSTNAME = os.getenv("REDPITAYA_HOST")
PASSWORD = os.getenv("REDPITAYA_PASSWORD", "")

if not HOSTNAME:
    sys.exit(
        "Error: REDPITAYA_HOST is not set.\n"
        "  PowerShell : $env:REDPITAYA_HOST = 'rp-XXXXXX.local'\n"
        "  bash/zsh   : export REDPITAYA_HOST=rp-XXXXXX.local"
    )

# --- SPI transport (Paramiko + on-device daemon) --------------------------
from hardware import ADF4355, RPSynthTransport

transport = RPSynthTransport(HOSTNAME, password=PASSWORD)
transport.connect()

synth = ADF4355(transport)
synth.init(f_init_hz=2.87e9)
print("ADF4355 initialised at 2.87 GHz")

transport.close()

# --- Scope / ADC (PyRPL) --------------------------------------------------
try:
    from pyrpl import Pyrpl  # type: ignore[import-untyped]
    rp = Pyrpl(hostname=HOSTNAME, password=PASSWORD, gui=False,
               config=os.getenv("REDPITAYA_CONFIG", "pyrpl_config.yml"))
    print("PyRPL connected. Firmware:", rp.rp.firmware_version)
    rp.close()
except ImportError:
    print("pyrpl not installed — skipping scope check.")
