"""
Test basic connectivity to the Red Pitaya.

Usage:
    python scripts/test_connection.py [host]

Default host: 192.168.1.100

Steps performed:
  1. TCP connect to SCPI server (port 5000)
  2. IDN query — confirms the SCPI server is responding
  3. Brief LED blink on LED0 (visual confirmation on the board)
  4. Clean disconnect

If the board is unreachable you will get a clear error message with tips.
"""

import sys
import time
import argparse

sys.path.insert(0, ".")  # allow running from repo root without install

from nv_control.scpi import RedPitaya, SCPIError


def main():
    parser = argparse.ArgumentParser(description="Test Red Pitaya SCPI connection")
    parser.add_argument("host", nargs="?", default="192.168.1.100", help="Red Pitaya IP address")
    parser.add_argument("--port", type=int, default=5000, help="SCPI server port (default 5000)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Socket timeout in seconds")
    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port} ...")

    try:
        rp = RedPitaya(args.host, port=args.port, timeout=args.timeout)
        rp.connect()
    except SCPIError as e:
        print(f"\nERROR: {e}")
        print("\nTroubleshooting:")
        print("  - Is the Red Pitaya powered on and on the network?")
        print("  - Ping the board:  ping", args.host)
        print("  - Is the SCPI server running? Start it from the RP web interface")
        print("    or via SSH: systemctl start redpitaya_scpi")
        sys.exit(1)

    print("Connected.")

    # --- IDN ---
    try:
        idn = rp.idn()
        print(f"IDN response: {idn}")
    except SCPIError as e:
        print(f"WARNING: IDN query failed — {e}")
        print("  Board may be connected but SCPI server is not fully ready.")

    # --- LED blink (optional, may not be supported on all firmware versions) ---
    print("Blinking LED0 three times ...")
    try:
        for _ in range(3):
            rp.set_led(0, True)
            time.sleep(0.3)
            rp.set_led(0, False)
            time.sleep(0.3)
        print("LED blink done.")
    except SCPIError as e:
        print(f"  LED control not available on this firmware ({e}) — that is OK.")

    rp.disconnect()
    print("\nDisconnected. Connection test passed.")


if __name__ == "__main__":
    main()
