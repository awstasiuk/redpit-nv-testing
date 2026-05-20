"""
ADF4355 Microwave Synthesizer Driver for Red Pitaya (PyRPL)
===========================================================
Target application: NV center CW-ODMR frequency sweeps (~2.7–3.0 GHz)

Hardware assumptions
--------------------
- REFIN      : Red Pitaya 125 MHz internal clock (single-ended, REFINA pin)
- fPFD       : 62.5 MHz  (R=1, RDIV2=1 — divide-by-2 flip-flop after R counter)
- RF divider : ÷2        (VCO runs at 2× RF output, i.e. 5.4–6.0 GHz for NV sweep)
- Prescaler  : 4/5       (NMIN = 23; fine for our N values ~86–96)
- SPI lines  : Red Pitaya digital outputs via PyRPL, level-shifted to 1.8 V

Override any of these via ADF4355Config — see hardware/utils.py.
"""

import time

from hardware.utils import ADF4355Config, calc_registers


class ADF4355:
    """
    Low-level ADF4355 driver.  Communicates via bit-banged SPI using
    the Red Pitaya's digital I/O pins through PyRPL.

    Constructing the object does NOT touch hardware — call init() to configure
    GPIO pins and load registers.

    Usage
    -----
        import pyrpl
        rp = pyrpl.Pyrpl(config='', hostname='rp-XXXXXX.local')
        synth = ADF4355(rp)       # safe without hardware
        synth.init()              # first hardware contact: sets up pins + registers
        synth.set_frequency(2.87e9)

    To override pin assignments or reference frequency, pass a custom config:
        cfg = ADF4355Config(pin_clk=3, pin_data=4, pin_le=5, f_ref_hz=100e6)
        synth = ADF4355(rp, config=cfg)
    """

    def __init__(self, pyrpl_obj, config: ADF4355Config = None):
        self._rp = pyrpl_obj
        self._config = config if config is not None else ADF4355Config()
        self._regs = [None] * 13

    # ------------------------------------------------------------------
    # Pin helpers
    # ------------------------------------------------------------------

    def _setup_pins(self):
        """Configure DIO pins as outputs; set CLK and LE idle-low."""
        hk = self._rp.rp.hk
        for pin in (self._config.pin_clk, self._config.pin_data, self._config.pin_le):
            hk.set_pin_direction_dout(pin)
        hk.set_pin_state(self._config.pin_clk, 0)
        hk.set_pin_state(self._config.pin_data, 0)
        hk.set_pin_state(self._config.pin_le, 0)

    def _set_pin(self, pin, val):
        self._rp.rp.hk.set_pin_state(pin, int(bool(val)))

    # ------------------------------------------------------------------
    # SPI transfer
    # ------------------------------------------------------------------

    def _send_word(self, word32: int):
        """
        Shift out a 32-bit word MSB-first.
        Timing: data valid before CLK rising edge; LE pulses high after.
        """
        self._set_pin(self._config.pin_le, 0)

        for bit_idx in range(31, -1, -1):
            bit = (word32 >> bit_idx) & 1
            self._set_pin(self._config.pin_data, bit)
            self._set_pin(self._config.pin_clk, 1)
            self._set_pin(self._config.pin_clk, 0)

        # LE pulse — must be ≥ max(20 ns, 2/fPFD) wide
        # Python GPIO toggles are slow enough that this is guaranteed
        self._set_pin(self._config.pin_le, 1)
        self._set_pin(self._config.pin_le, 0)

    def write_register(self, reg_num: int, value: int):
        """Write a single register by its 32-bit value."""
        self._regs[reg_num] = value
        self._send_word(value)

    # ------------------------------------------------------------------
    # Initialization sequence (power-up, fPFD ≤ 75 MHz path)
    # ------------------------------------------------------------------

    def init(self, f_init_hz: float = 2.87e9):
        """
        Full power-up initialization sequence.
        Writes all 13 registers in the order required by the datasheet,
        then waits for the ADC clock settle time before writing Register 0.

        Parameters
        ----------
        f_init_hz : float
            Starting frequency (default: NV zero-field 2.87 GHz).
        """
        self._setup_pins()
        regs = calc_registers(f_init_hz, self._config)
        meta = regs["_meta"]
        print(f"[ADF4355] Initialising to {meta['f_out_achieved_hz']/1e9:.6f} GHz")
        print(
            f"          INT={meta['INT']}, FRAC1={meta['FRAC1']}, "
            f"FRAC2={meta['FRAC2']}, MOD2={meta['MOD2']}, "
            f"error={meta['error_hz']:.2f} Hz"
        )

        # Datasheet init order: Reg12 → 11 → 10 → 9 → 8 → 7 → 6 → 5 → 4 → 3 → 2 → 1
        for n in [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]:
            self.write_register(n, regs[f"reg{n}"])

        # Wait > 16 ADC_CLK cycles before writing Register 0
        time.sleep(self._config.adc_wait_s * 2)

        # Register 0 with autocalibration enabled
        self.write_register(0, regs["reg0"])

    # ------------------------------------------------------------------
    # Frequency update sequence (for sweep, fPFD ≤ 75 MHz path)
    # ------------------------------------------------------------------

    def set_frequency(self, f_hz: float, wait_lock=True):
        """
        Update output frequency using the datasheet 8-step sequence.

        Steps:
          1. Reg10  (refresh ADC/VTUNE calibration)
          2. Reg4   counter reset ON
          3. Reg2   new FRAC2/MOD2
          4. Reg1   new FRAC1
          5. Reg0   autocalibration OFF
          6. Reg4   counter reset OFF
          7. wait   > 16 ADC_CLK cycles
          8. Reg0   autocalibration ON  ← frequency changes here

        Parameters
        ----------
        f_hz : float
            Target RF output frequency in Hz.
        wait_lock : bool
            If True, sleep for a conservative lock-time estimate after
            the final register write (suitable for CW sweep dwell).
        """
        regs = calc_registers(f_hz, self._config)

        self.write_register(10, regs["reg10"])

        reg4_reset_on = regs["reg4"] | (1 << 4)
        self.write_register(4, reg4_reset_on)

        self.write_register(2, regs["reg2"])
        self.write_register(1, regs["reg1"])

        reg0_no_autocal = regs["reg0"] & ~(1 << 21)
        self.write_register(0, reg0_no_autocal)

        reg4_reset_off = regs["reg4"] & ~(1 << 4)
        self.write_register(4, reg4_reset_off)

        time.sleep(self._config.adc_wait_s * 2)

        self.write_register(0, regs["reg0"])

        if wait_lock:
            # Conservative: 2 ms covers band-select + ALC + PLL settle at 20 kHz BW
            time.sleep(2e-3)
