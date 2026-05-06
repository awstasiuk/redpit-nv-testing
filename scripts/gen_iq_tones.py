"""
Generate an I/Q tone pair on Red Pitaya OUT1 (I) and OUT2 (Q).

OUT1 and OUT2 are driven at the same frequency with a 90° phase offset between them.
This is the IF signal that will feed an IQ mixer to reach the NV ESR frequency.

  OUT1 (I):  A·cos(2π·f·t)         phase = 0°
  OUT2 (Q):  A·cos(2π·f·t − 90°)   phase = −90° (lags I by 90°)

Usage:
    python scripts/gen_iq_tones.py [host] [options]

Examples:
    python scripts/gen_iq_tones.py 192.168.1.100
    python scripts/gen_iq_tones.py 192.168.1.100 --freq 10e6 --amp 0.5

Scope check:
  - Use a two-channel scope on OUT1 and OUT2
  - Trigger on OUT1; OUT2 should lag by exactly one quarter period (T/4)
  - Lissajous (XY mode) should show a circle if amplitudes are matched
"""

import sys
import argparse

sys.path.insert(0, ".")

from nv_control.scpi import RedPitaya, SCPIError

# Standard IQ convention: Q lags I by 90°
Q_PHASE_DEG = -90.0


def main():
    parser = argparse.ArgumentParser(description="Generate I/Q tone pair on Red Pitaya")
    parser.add_argument("host", nargs="?", default="192.168.1.100")
    parser.add_argument("--freq", type=float, default=1e6, help="IF frequency in Hz (default 1 MHz)")
    parser.add_argument("--amp", type=float, default=1.0, help="Amplitude in V peak, both channels (default 1.0 V)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port} ...")

    try:
        with RedPitaya(args.host, port=args.port) as rp:
            print(f"Connected. IDN: {rp.idn()}")

            print(
                f"\nConfiguring I/Q pair at {args.freq/1e6:.3f} MHz, {args.amp:.3f} V peak:"
            )
            print(f"  OUT1 (I): phase =   0.0°")
            print(f"  OUT2 (Q): phase = {Q_PHASE_DEG:.1f}°  (Q lags I by 90°)")

            rp.configure_sine(ch=1, freq_hz=args.freq, amplitude_v=args.amp, phase_deg=0.0)
            rp.configure_sine(ch=2, freq_hz=args.freq, amplitude_v=args.amp, phase_deg=Q_PHASE_DEG)

            print("\nBoth outputs ON.")
            print("Scope check:")
            print("  - Two-channel: OUT2 should lag OUT1 by T/4")
            print("  - XY mode: should trace a circle (ellipse means amp mismatch or phase error)")
            print("\nPress Enter to stop ...")
            input()

            rp.outputs_off()
            print("Outputs off. Done.")

    except SCPIError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
