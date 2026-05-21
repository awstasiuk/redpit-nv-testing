import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ADF4355Config:
    """
    All user-tunable parameters for an ADF4355 PLL + SPI wiring.
    Derived timing and divider values are computed as properties.
    """

    # Reference input chain
    # Defaults match the EV-ADF4355SD1Z eval board: onboard 122.88 MHz differential
    # TCXO (Vectron VCC6-LAB-122M880000) with R=1, RDIV2=1 → fPFD = 61.44 MHz.
    f_ref_hz: float = 122.88e6  # REFIN frequency (Hz)
    r: int = 1                  # R counter value
    rdiv2: int = 1              # 1 = enable ÷2 flip-flop after R counter → fPFD = 61.44 MHz
    ref_doubler: int = 0        # 1 = enable reference doubler (D bit)
    ref_mode: int = 1           # 0 = single-ended REFIN, 1 = differential (eval board TCXO)

    # Output divider — must be a power of 2 in {1, 2, 4, 8, 16, 32, 64}
    rf_div: int = 2            # ÷2 → VCO runs at 2× RF output, covers NV range

    # GPIO pin assignments (Red Pitaya digital I/O)
    pin_clk: int = 0           # DIO0_P
    pin_data: int = 1          # DIO1_P
    pin_le: int = 2            # DIO2_P

    # Charge pump and RF output settings
    cp_current: int = 0b0010   # charge pump current code; 0b0010 ≈ 0.94 mA (eval board: 5.1 kΩ RSET, ICP = 0.9 mA)
    rf_power: int = 0b11       # output power code; 0b11 = +5 dBm
    bleed_value: int = 4       # negative bleed current; tune up if spur floor is high

    # Calibration timing — datasheet defaults, rarely need changing
    alc_wait: int = 30
    synth_lock_timeout: int = 12

    def __post_init__(self):
        if self.rf_div not in {1, 2, 4, 8, 16, 32, 64}:
            raise ValueError(
                f"rf_div must be a power of 2 in {{1…64}}, got {self.rf_div}"
            )

    # --- Derived properties ---------------------------------------------------

    @property
    def f_pfd(self) -> float:
        """Phase-frequency detector rate (Hz)."""
        return self.f_ref_hz * (1 + self.ref_doubler) / (self.r * (1 + self.rdiv2))

    @property
    def mod1(self) -> int:
        """Fixed primary modulus — always 2^24 for ADF4355."""
        return 2 ** 24

    @property
    def rf_div_bits(self) -> int:
        """3-bit RF_DIV_SEL field: encodes log2(rf_div)."""
        return int(round(math.log2(self.rf_div)))

    @property
    def adc_clk_div(self) -> int:
        """ADC clock divider — ceiling((fPFD/100 kHz − 2) / 4), capped at 255."""
        return min(math.ceil((self.f_pfd / 100e3 - 2) / 4), 255)

    @property
    def vco_band_div(self) -> int:
        """VCO band-selection clock divider — ceiling(fPFD / 2.4 MHz)."""
        return math.ceil(self.f_pfd / 2_400_000)

    @property
    def timeout(self) -> int:
        """Synthesizer timeout value — ceiling(fPFD × 50 µs / ALC_WAIT)."""
        return math.ceil((self.f_pfd * 50e-6) / self.alc_wait)

    @property
    def adc_wait_s(self) -> float:
        """Minimum wait after Reg1 write: 16 ADC clock cycles (seconds)."""
        return 16 / (self.f_pfd / self.adc_clk_div)


# Default config matching the EV-ADF4355SD1Z eval board with its onboard 122.88 MHz TCXO.
DEFAULT_CONFIG = ADF4355Config()


# ---------------------------------------------------------------------------
# Chip-level fixed register values (datasheet §Table 14, must not be changed)
# ---------------------------------------------------------------------------

REG5_FIXED = 0x00800025
REG8_FIXED = 0x102D0428
REG11_FIXED = 0x0061300B


# ---------------------------------------------------------------------------
# Register builders  (each returns a 32-bit int; pure functions, no globals)
# ---------------------------------------------------------------------------

def _build_reg0(INT, autocal=1, prescaler=0):
    word = 0b0000
    word |= (INT & 0xFFFF) << 4
    word |= (prescaler & 1) << 20
    word |= (autocal & 1) << 21
    return word & 0xFFFFFFFF


def _build_reg1(FRAC1):
    word = 0b0001
    word |= (FRAC1 & 0xFFFFFF) << 4
    return word & 0xFFFFFFFF


def _build_reg2(FRAC2, MOD2):
    word = 0b0010
    word |= (MOD2 & 0x3FFF) << 4
    word |= (FRAC2 & 0x3FFF) << 18
    return word & 0xFFFFFFFF


def _build_reg3(phase_val=1, phase_adjust=0, phase_resync=0, sd_load_reset=0):
    word = 0b0011
    word |= (phase_val & 0xFFFFFF) << 4
    word |= (phase_resync & 1) << 29
    word |= (sd_load_reset & 1) << 30
    word |= (phase_adjust & 1) << 28
    return word & 0xFFFFFFFF


def _build_reg4(
    muxout, ref_mode, ref_doubler, rdiv2, r_counter, double_buf,
    cp_current, ldo_level, pd_polarity, power_down, cp_three_state, counter_reset,
):
    word = 0b0100
    word |= (counter_reset & 1) << 4
    word |= (cp_three_state & 1) << 5
    word |= (power_down & 1) << 6
    word |= (pd_polarity & 1) << 7
    word |= (ldo_level & 1) << 8
    word |= (ref_mode & 1) << 9
    word |= (cp_current & 0xF) << 10
    word |= (double_buf & 1) << 14
    word |= (r_counter & 0x3FF) << 15
    word |= (rdiv2 & 1) << 25
    word |= (ref_doubler & 1) << 26
    word |= (muxout & 0x7) << 27
    return word & 0xFFFFFFFF


def _build_reg6(
    rf_div_bits, feedback_select, bleed_en, gated_bleed, bleed_value,
    mtld, aux_out_en, aux_power, rf_out_en, rf_power,
):
    word = 0b0110
    word |= (rf_power & 0x3) << 4
    word |= (rf_out_en & 1) << 6
    word |= (aux_power & 0x3) << 7
    word |= (aux_out_en & 1) << 9
    word |= (mtld & 1) << 11
    word |= (bleed_value & 0xFF) << 13
    word |= (rf_div_bits & 0x7) << 21
    word |= (feedback_select & 1) << 24
    word |= 0b1010 << 25  # DB28:DB25 reserved = 1010 (datasheet §Table 14)
    word |= (bleed_en & 1) << 29
    word |= (gated_bleed & 1) << 30
    return word & 0xFFFFFFFF


def _build_reg7(le_sync=1, lol=0, ldp=0b11, ldm=0, ld_cycle=0b00):
    word = 0b0111
    word |= (ldm & 1) << 4
    word |= (ldp & 0x3) << 5
    word |= (lol & 1) << 7
    word |= (ld_cycle & 0x3) << 8
    word |= (le_sync & 1) << 25
    word |= 1 << 28  # DB28 = 1 (reserved, must be 1)
    return word & 0xFFFFFFFF


def _build_reg9(vco_band_div, timeout, alc_wait, synth_lock_timeout):
    word = 0b1001
    word |= (synth_lock_timeout & 0x1F) << 4
    word |= (alc_wait & 0x1F) << 9
    word |= (timeout & 0x3FF) << 14
    word |= (vco_band_div & 0xFF) << 24
    return word & 0xFFFFFFFF


def _build_reg10(adc_clk_div, adc_en=1, adc_conv=1):
    word = 0b1010
    word |= (adc_en & 1) << 4
    word |= (adc_conv & 1) << 5
    word |= (adc_clk_div & 0xFF) << 6
    word |= 0b11 << 22  # DB23:DB22 must = 11 (reserved)
    return word & 0xFFFFFFFF


def _build_reg12(resync_clock=1):
    word = 0b1100
    word |= 1 << 4   # DB4 must = 1 (reserved)
    word |= 1 << 10  # DB10 must = 1 (reserved)
    word |= (resync_clock & 0xFFFF) << 16
    return word & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calc_registers(f_out_hz: float, config: ADF4355Config = DEFAULT_CONFIG) -> dict:
    """
    Compute all 13 ADF4355 register values for a given RF output frequency.

    Parameters
    ----------
    f_out_hz : float
        Desired RF output frequency in Hz (e.g. 2.87e9 for NV zero-field).
    config : ADF4355Config
        Hardware configuration; defaults to DEFAULT_CONFIG (EV-ADF4355SD1Z eval board,
        122.88 MHz differential TCXO, fPFD = 61.44 MHz, ÷2 output divider).

    Returns
    -------
    dict with keys 'reg0' … 'reg12' (32-bit ints) and '_meta'.

    Raises
    ------
    ValueError if frequency is outside the achievable VCO range.
    """
    f_out_hz = float(f_out_hz)
    f_vco = f_out_hz * config.rf_div

    if not (3.4e9 <= f_vco <= 6.8e9):
        raise ValueError(
            f"VCO frequency {f_vco/1e9:.4f} GHz out of range [3.4, 6.8] GHz "
            f"for RF output {f_out_hz/1e9:.4f} GHz with RF_DIV={config.rf_div}."
        )

    N_exact = f_vco / config.f_pfd
    INT = int(N_exact)

    if INT < 23:
        raise ValueError(f"INT={INT} below minimum of 23 for 4/5 prescaler.")

    frac = N_exact - INT
    FRAC1 = int(frac * config.mod1)
    remainder = frac * config.mod1 - FRAC1

    if remainder < 1e-9:
        MOD2 = 2
        FRAC2 = 0
    else:
        frac_obj = Fraction(remainder).limit_denominator(16383)
        MOD2 = max(2, min(frac_obj.denominator, 16383))
        FRAC2 = max(0, min(frac_obj.numerator, MOD2 - 1))

    N_achieved = INT + (FRAC1 + FRAC2 / MOD2) / config.mod1
    f_achieved = N_achieved * config.f_pfd / config.rf_div
    error_hz = abs(f_achieved - f_out_hz)

    reg0 = _build_reg0(INT, autocal=1, prescaler=0)
    reg1 = _build_reg1(FRAC1)
    reg2 = _build_reg2(FRAC2, MOD2)
    reg3 = _build_reg3(phase_val=1, phase_adjust=0, phase_resync=0, sd_load_reset=0)
    reg4 = _build_reg4(
        muxout=0b110,
        ref_mode=config.ref_mode,
        ref_doubler=config.ref_doubler,
        rdiv2=config.rdiv2,
        r_counter=config.r,
        double_buf=1,
        cp_current=config.cp_current,
        ldo_level=0,
        pd_polarity=1,
        power_down=0,
        cp_three_state=0,
        counter_reset=0,
    )
    reg5 = REG5_FIXED
    reg6 = _build_reg6(
        rf_div_bits=config.rf_div_bits,
        feedback_select=1,
        bleed_en=1,
        gated_bleed=0,
        bleed_value=config.bleed_value,
        mtld=0,
        aux_out_en=0,
        aux_power=0b00,
        rf_out_en=1,
        rf_power=config.rf_power,
    )
    reg7 = _build_reg7(le_sync=1, lol=0, ldp=0b11, ldm=0, ld_cycle=0b00)
    reg8 = REG8_FIXED
    reg9 = _build_reg9(
        config.vco_band_div, config.timeout, config.alc_wait, config.synth_lock_timeout
    )
    reg10 = _build_reg10(config.adc_clk_div, adc_en=1, adc_conv=1)
    reg11 = REG11_FIXED
    reg12 = _build_reg12(resync_clock=1)

    return {
        "reg0": reg0, "reg1": reg1, "reg2": reg2, "reg3": reg3,
        "reg4": reg4, "reg5": reg5, "reg6": reg6, "reg7": reg7,
        "reg8": reg8, "reg9": reg9, "reg10": reg10, "reg11": reg11,
        "reg12": reg12,
        "_meta": {
            "f_out_target_hz": f_out_hz,
            "f_out_achieved_hz": f_achieved,
            "error_hz": error_hz,
            "INT": INT,
            "FRAC1": FRAC1,
            "FRAC2": FRAC2,
            "MOD2": MOD2,
            "RF_DIV": config.rf_div,
            "f_vco_hz": f_vco,
        },
    }


def verify_frequency(
    f_hz: float,
    config: ADF4355Config = DEFAULT_CONFIG,
    verbose: bool = True,
) -> dict:
    """
    Compute and print register values for a target frequency.
    Useful for pre-flight checks without hardware.
    """
    regs = calc_registers(f_hz, config)
    meta = regs["_meta"]

    if verbose:
        print(f"\n{'='*55}")
        print(f"  Target   : {f_hz/1e9:.6f} GHz")
        print(f"  Achieved : {meta['f_out_achieved_hz']/1e9:.9f} GHz")
        print(f"  Error    : {meta['error_hz']:.4f} Hz")
        print(f"  VCO freq : {meta['f_vco_hz']/1e9:.6f} GHz  (÷{config.rf_div})")
        print(f"  INT      : {meta['INT']}")
        print(f"  FRAC1    : {meta['FRAC1']}  (/{config.mod1})")
        print(f"  FRAC2    : {meta['FRAC2']}  /{meta['MOD2']}")
        print(f"  fPFD     : {config.f_pfd/1e6:.3f} MHz")
        print(f"  ADC_DIV  : {config.adc_clk_div}")
        print(f"  ADC wait : {config.adc_wait_s*1e6:.1f} µs  (×2 margin applied)")
        print(f"\n  Register hex values:")
        for n in range(13):
            print(f"    Reg{n:2d} : 0x{regs[f'reg{n}']:08X}")
        print(f"{'='*55}\n")

    return regs
