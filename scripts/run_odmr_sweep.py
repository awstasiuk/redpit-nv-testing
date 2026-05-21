#!/usr/bin/env python3
"""
Full CW-ODMR sweep — scripted end-to-end run.

Connects to the Red Pitaya, initialises the ADF4355 synthesizer, sweeps
frequency while reading the photodiode via the RP ADC, saves raw data,
and writes a PNG plot.

Usage:
    python scripts/run_odmr_sweep.py

Environment variables (set before running):
    REDPITAYA_HOST      Red Pitaya hostname or IP  (required)
    REDPITAYA_PASSWORD  SSH / PyRPL password        (default: empty)
    REDPITAYA_CONFIG    PyRPL config file path      (default: pyrpl_config.yml)
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Logging — change level to logging.DEBUG to see every socket message
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("odmr_sweep")

# ---------------------------------------------------------------------------
# Configuration — edit these or override with env vars
# ---------------------------------------------------------------------------
HOSTNAME    = os.getenv("REDPITAYA_HOST")
PASSWORD    = os.getenv("REDPITAYA_PASSWORD", "")
RP_CONFIG   = os.getenv("REDPITAYA_CONFIG", "pyrpl_config.yml")

ADC_CHANNEL = 1         # Red Pitaya input (1 = IN1, 2 = IN2)

F_START  = 2.70e9       # sweep start  (Hz)
F_STOP   = 3.00e9       # sweep stop   (Hz)
N_POINTS = 301          # frequency steps
DWELL_S  = 20e-3        # scope integration window per point (seconds)

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress(i: int, freq: float, voltage: float, t0: float):
    elapsed   = time.monotonic() - t0
    remaining = elapsed / (i + 1) * (N_POINTS - i - 1)
    logger.info(
        "  %3d / %d   %8.4f GHz   V = %6.2f mV   "
        "[%ds elapsed, ~%ds remaining]",
        i + 1, N_POINTS, freq / 1e9, voltage * 1e3, int(elapsed), int(remaining),
    )


def _save(freqs: np.ndarray, voltages: np.ndarray) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = DATA_DIR / f"odmr_{stamp}.npz"
    np.savez(
        out_path,
        freqs=freqs, voltages=voltages,
        f_start=F_START, f_stop=F_STOP,
        n_points=N_POINTS, dwell_s=DWELL_S,
        hostname=HOSTNAME,
    )
    logger.info("Data saved → %s", out_path)
    return out_path


def _plot(freqs: np.ndarray, voltages: np.ndarray, save_path: Path):
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(freqs / 1e9, voltages * 1e3, color="steelblue", linewidth=0.9)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Photodiode signal (mV)")
    ax.set_title("CW-ODMR Spectrum")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    fig_path = save_path.with_suffix(".png")
    fig.savefig(fig_path, dpi=150, bbox_inches="tight")
    logger.info("Plot saved  → %s", fig_path)
    plt.show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not HOSTNAME:
        logger.error(
            "REDPITAYA_HOST is not set.\n"
            "  PowerShell : $env:REDPITAYA_HOST = 'rp-XXXXXX.local'\n"
            "  bash/zsh   : export REDPITAYA_HOST=rp-XXXXXX.local"
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Pre-flight: verify all sweep frequencies offline
    # ------------------------------------------------------------------
    logger.info("Pre-flight: validating %d sweep frequencies …", N_POINTS)
    from hardware.utils import calc_registers

    sweep_freqs = np.linspace(F_START, F_STOP, N_POINTS)
    try:
        max_err = max(calc_registers(f)["_meta"]["error_hz"] for f in sweep_freqs)
    except ValueError as exc:
        logger.error("Sweep range is not achievable: %s", exc)
        sys.exit(1)
    logger.info("Max frequency error across sweep: %.4f Hz  ✓", max_err)

    # ------------------------------------------------------------------
    # Connect SPI transport
    # ------------------------------------------------------------------
    from hardware import ADF4355, RPSynthTransport

    logger.info("Connecting SPI transport to %s …", HOSTNAME)
    transport = RPSynthTransport(HOSTNAME, password=PASSWORD)
    try:
        transport.connect()
    except (ConnectionError, RuntimeError) as exc:
        logger.error("SPI transport failed: %s", exc)
        sys.exit(1)

    synth = ADF4355(transport)
    try:
        synth.init(f_init_hz=F_START)
    except Exception as exc:
        logger.error("ADF4355 init failed: %s", exc)
        transport.close()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Connect scope (PyRPL)
    # ------------------------------------------------------------------
    rp = None
    try:
        from pyrpl import Pyrpl  # type: ignore[import-untyped]
        rp = Pyrpl(hostname=HOSTNAME, password=PASSWORD, gui=False, config=RP_CONFIG)
        logger.info("PyRPL scope connected")
    except ImportError:
        logger.error("pyrpl is not installed — cannot read ADC.  Aborting.")
        transport.close()
        sys.exit(1)
    except Exception as exc:
        logger.error("PyRPL connection failed: %s", exc)
        transport.close()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Sweep
    # ------------------------------------------------------------------
    from experiments.odmr import ODMRSweep

    sweep = ODMRSweep(
        synth, rp=rp, adc_channel=ADC_CHANNEL,
        f_start=F_START, f_stop=F_STOP, n_points=N_POINTS, dwell_s=DWELL_S,
    )

    eta = N_POINTS * (DWELL_S + 0.003)
    logger.info(
        "Starting sweep: %.3f – %.3f GHz  |  %d pts  |  %.0f ms/pt  |  ETA ~%.0f s",
        F_START / 1e9, F_STOP / 1e9, N_POINTS, DWELL_S * 1e3, eta,
    )

    freqs, voltages = None, None
    t0 = time.monotonic()
    try:
        for i, freq in enumerate(sweep):
            v = sweep.read_voltage()
            sweep.record(v)
            if (i + 1) % 30 == 0 or i == N_POINTS - 1:
                _progress(i, freq, v, t0)
        freqs, voltages = sweep.result()
    except (ConnectionError, RuntimeError) as exc:
        logger.error("Sweep failed at point %d: %s", i + 1, exc)
    except KeyboardInterrupt:
        logger.warning("Sweep interrupted by user at point %d", i + 1)
        freqs, voltages = sweep.result()  # save whatever we got
    finally:
        transport.close()
        logger.info("Transport closed")

    if freqs is None or len(freqs) == 0:
        logger.error("No data collected — exiting")
        sys.exit(1)

    logger.info(
        "Sweep done: %d points in %.1f s", len(freqs), time.monotonic() - t0
    )

    # ------------------------------------------------------------------
    # Save and plot
    # ------------------------------------------------------------------
    out_path = _save(freqs, voltages)
    _plot(freqs, voltages, out_path)


if __name__ == "__main__":
    main()
