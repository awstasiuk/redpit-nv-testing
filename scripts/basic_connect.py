import os
import sys

from pyrpl import Pyrpl

HOSTNAME = os.getenv("REDPITAYA_HOST")
PASSWORD = os.getenv("REDPITAYA_PASSWORD", "")
CONFIG = os.getenv("REDPITAYA_CONFIG", "pyrpl_config.yml")

if not HOSTNAME:
    sys.exit(
        "Error: REDPITAYA_HOST is not set.\n"
        "  PowerShell : $env:REDPITAYA_HOST = 'rp-XXXXXX.local'\n"
        "  bash/zsh   : export REDPITAYA_HOST=rp-XXXXXX.local"
    )

p = Pyrpl(hostname=HOSTNAME, password=PASSWORD, gui=False, config=CONFIG)
r = p.rp

print("Connected to Red Pitaya at", HOSTNAME)
print("Firmware version:", r.firmware_version)
print("Available modules:", r.modules)
