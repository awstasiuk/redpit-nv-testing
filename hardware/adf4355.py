"""
ADF4355 Microwave Synthesizer Driver
=====================================
Target application: NV center CW-ODMR frequency sweeps (~2.7–3.0 GHz)

Communication
-------------
SPI bit-banging runs on the Red Pitaya ARM core via rp_daemon.py.
The host sends one TCP message per frequency step; the daemon executes
the full multi-write SPI sequence locally with no per-toggle round-trips.

See hardware/rp_transport.py for the connection setup.
See hardware/rp_daemon.py for the on-device SPI implementation.

Logging:
  This module logs under the name 'hardware.adf4355'.
  INFO shows init/frequency events; DEBUG shows register details.
"""

import logging

from hardware.utils import ADF4355Config, calc_registers
from hardware.rp_transport import RPSynthTransport

logger = logging.getLogger(__name__)


class ADF4355:
    """
    High-level ADF4355 driver.

    Calculates register values from a target frequency and delegates
    the SPI writes to RPSynthTransport (which runs the bit-bang loop
    on the Red Pitaya itself via rp_daemon.py).

    Usage
    -----
        transport = RPSynthTransport('rp-XXXXXX.local', password='...')
        transport.connect()

        synth = ADF4355(transport)
        synth.init()                   # power-up sequence at 2.87 GHz
        synth.set_frequency(2.87e9)    # update during sweep

    To override hardware constants (ref frequency, pins, CP current …):
        cfg = ADF4355Config(f_ref_hz=125e6, cp_current=0b0111)
        synth = ADF4355(transport, config=cfg)
    """

    def __init__(self, transport: RPSynthTransport, config: ADF4355Config = None):
        self._transport = transport
        self._config    = config if config is not None else ADF4355Config()

    def _adc_wait_us(self) -> int:
        """ADC wait with 2× margin, converted to integer microseconds."""
        return int(self._config.adc_wait_s * 2 * 1e6)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init(self, f_init_hz: float = 2.87e9):
        """
        Full power-up initialisation sequence.

        Writes all 13 registers in the datasheet-required order (12→1),
        waits for the ADC clock to settle, then writes register 0 with
        autocalibration enabled.

        Parameters
        ----------
        f_init_hz : float
            Starting frequency in Hz (default: NV zero-field 2.87 GHz).
        """
        logger.info("Initialising ADF4355 to %.6f GHz", f_init_hz / 1e9)
        try:
            regs = calc_registers(f_init_hz, self._config)
        except ValueError as exc:
            logger.error("Frequency %.6f GHz out of range: %s", f_init_hz / 1e9, exc)
            raise

        meta = regs['_meta']
        logger.info(
            "Achieved %.9f GHz  (error %.2f Hz)",
            meta['f_out_achieved_hz'] / 1e9, meta['error_hz'],
        )
        logger.debug(
            "INT=%d  FRAC1=%d  FRAC2=%d  MOD2=%d  fPFD=%.3f MHz  adc_wait=%d µs",
            meta['INT'], meta['FRAC1'], meta['FRAC2'], meta['MOD2'],
            self._config.f_pfd / 1e6, self._adc_wait_us(),
        )

        try:
            self._transport.cmd_init(regs, self._adc_wait_us())
        except (ConnectionError, RuntimeError) as exc:
            logger.error("ADF4355 init failed: %s", exc)
            raise

        logger.info("ADF4355 init complete")

    def set_frequency(self, f_hz: float):
        """
        Update output frequency using the datasheet 8-step sequence.

        The daemon executes all SPI writes and timing (ADC wait + 2 ms
        PLL lock settle) on the RP; this call blocks until OK is received.

        Parameters
        ----------
        f_hz : Target RF output frequency in Hz.
        """
        logger.debug("set_frequency → %.6f GHz", f_hz / 1e9)
        try:
            regs = calc_registers(f_hz, self._config)
        except ValueError as exc:
            logger.error("Frequency %.6f GHz out of range: %s", f_hz / 1e9, exc)
            raise

        try:
            self._transport.cmd_set_frequency(regs, self._adc_wait_us())
        except (ConnectionError, RuntimeError) as exc:
            logger.error("set_frequency failed at %.6f GHz: %s", f_hz / 1e9, exc)
            raise
