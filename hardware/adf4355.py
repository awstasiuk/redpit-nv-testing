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
"""

from hardware.utils import ADF4355Config, calc_registers
from hardware.rp_transport import RPSynthTransport


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
        regs = calc_registers(f_init_hz, self._config)
        meta = regs['_meta']
        print(f'[ADF4355] Initialising to {meta["f_out_achieved_hz"]/1e9:.6f} GHz')
        print(
            f'          INT={meta["INT"]}, FRAC1={meta["FRAC1"]}, '
            f'FRAC2={meta["FRAC2"]}, MOD2={meta["MOD2"]}, '
            f'error={meta["error_hz"]:.2f} Hz'
        )
        self._transport.cmd_init(regs, self._adc_wait_us())

    def set_frequency(self, f_hz: float):
        """
        Update output frequency using the datasheet 8-step sequence.

        The daemon executes all SPI writes and timing (ADC wait + 2 ms
        PLL lock settle) on the RP; this call blocks until OK is received.

        Parameters
        ----------
        f_hz : Target RF output frequency in Hz.
        """
        regs = calc_registers(f_hz, self._config)
        self._transport.cmd_set_frequency(regs, self._adc_wait_us())
