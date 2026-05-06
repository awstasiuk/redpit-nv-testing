"""
Generate a CW sine tone on Red Pitaya OUT1.

Usage:
    python scripts/gen_tone.py [host] [options]

Examples:
    python scripts/gen_tone.py 192.168.1.100
    python scripts/gen_tone.py 192.168.1.100 --freq 10e6 --amp 0.5
    python scripts/gen_tone.py 192.168.1.100 --freq 1e6 --amp 1.0 --ch 2

Output is held until you press Enter, then outputs are turned off cleanly.
Use an oscilloscope on OUT1 (or OUT2) to verify the signal.
"""

import sys
import argparse

sys.path.insert(0, ".")

from nv_control.scpi import RedPitaya, SCPIError


def main():
    parser = argparse.ArgumentParser(description="Generate CW tone on Red Pitaya output")
    parser.add_argument("host", nargs="?", default="192.168.1.100")
    parser.add_argument("--freq", type=float, default=1e6, help="Frequency in Hz (default 1 MHz)")
    parser.add_argument("--amp", type=float, default=1.0, help="Amplitude in V peak (default 1.0 V)")
    parser.add_argument("--offset", type=float, default=0.0, help="DC offset in V (default 0)")
    parser.add_argument("--ch", type=int, choices=[1, 2], default=1, help="Output channel (default 1)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port} ...")

    try:
        with RedPitaya(args.host, port=args.port) as rp:
            print(f"Connected. IDN: {rp.idn()}")

            print(
                f"\nConfiguring OUT{args.ch}: {args.freq/1e6:.3f} MHz, "
                f"{args.amp:.3f} Vpp, offset {args.offset:.3f} V"
            )
            rp.configure_sine(
                ch=args.ch,
                freq_hz=args.freq,
                amplitude_v=args.amp,
                phase_deg=0.0,
                offset_v=args.offset,
            )
            print(f"OUT{args.ch} is ON. Connect scope to OUT{args.ch}.")
            print("\nPress Enter to stop and turn off output ...")
            input()

            rp.output_off(args.ch)
            print(f"OUT{args.ch} off. Done.")

    except SCPIError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
