"""
Online unit tests for ADF4355 driver with Red Pitaya / PyRPL.

These tests require:
  - A running Red Pitaya instance accessible via PyRPL
  - The Red Pitaya hostname/IP and credentials (set via env vars or config)
  - Proper GPIO wiring for SPI lines (CLK, DATA, LE)
  - Ideally, RF output connected to a spectrum analyzer or power meter for verification

Run only when hardware is available and configured.
E.g.: pytest tests/test_online.py -v --redis=<rp_hostname>
"""

import pytest
import numpy as np
import os
from unittest.mock import MagicMock, patch

# These imports will be attempted only if hardware tests are requested
try:
    from pyrpl import Pyrpl

    HAS_PYRPL = True
except ImportError:
    HAS_PYRPL = False

from hardware.adf4355 import ADF4355
from experiments.odmr import ODMRSweep


# Fixtures for hardware setup
@pytest.fixture(scope="session")
def pyrpl_config():
    """Load Red Pitaya hostname and config from environment or config file."""
    hostname = os.getenv("REDPITAYA_HOST", None)
    password = os.getenv("REDPITAYA_PASSWORD", None)
    config_file = os.getenv("REDPITAYA_CONFIG", "pyrpl_config.yml")

    if not hostname:
        pytest.skip("REDPITAYA_HOST not set; skipping online tests")

    return {
        "hostname": hostname,
        "password": password,
        "config": config_file,
    }


@pytest.fixture(scope="session")
def rp_instance(pyrpl_config):
    """Connect to Red Pitaya and return PyRPL instance."""
    if not HAS_PYRPL:
        pytest.skip("pyrpl not installed; skipping online tests")

    try:
        rp = Pyrpl(
            hostname=pyrpl_config["hostname"],
            password=pyrpl_config["password"],
            gui=False,
            config=pyrpl_config["config"],
        )
        yield rp
        rp.close()
    except Exception as e:
        pytest.skip(f"Could not connect to Red Pitaya: {e}")


@pytest.fixture(scope="function")
def synth(rp_instance):
    """Initialize ADF4355 driver on the Red Pitaya instance."""
    synth = ADF4355(rp_instance)
    synth.init(f_init_hz=2.87e9)
    yield synth
    # Cleanup: could add power-down or final frequency here


# Online hardware tests
class TestADF4355HardwareLow:
    """Test low-level ADF4355 SPI communication."""

    def test_pin_setup(self, rp_instance):
        """Verify GPIO pins are configured as outputs."""
        # TODO: Read pin states and verify they are outputs
        pass

    def test_send_word(self, synth):
        """Test that _send_word completes without error."""
        # TODO: Send a test word and verify LE pulse on oscilloscope
        pass

    def test_write_register(self, synth):
        """Test writing a single register."""
        # TODO: Write Reg3 and read back via SPI monitor
        pass


class TestADF4355Initialization:
    """Test full initialization sequence."""

    def test_init_sequence(self, rp_instance):
        """Test that init() completes and synth reaches lock."""
        synth = ADF4355(rp_instance)
        synth.init(f_init_hz=2.87e9)

        # TODO: Poll lock detect pin or measure RF output power
        # TODO: Verify output frequency on spectrum analyzer
        pass

    def test_init_verbose_output(self, synth, capsys):
        """Test that init() prints expected debug info."""
        # TODO: Verify init() output shows correct INT, FRAC1, etc.
        pass


class TestADF4355FrequencyUpdate:
    """Test frequency update (sweep) sequence."""

    def test_set_frequency_single_step(self, synth):
        """Test setting frequency to a new value."""
        # TODO: Set to 2.80 GHz and verify lock within 10 ms
        pass

    def test_set_frequency_sweep(self, synth):
        """Test rapid frequency stepping."""
        # TODO: Step through 10 frequencies 100 ms apart
        # TODO: Verify lock for each step
        pass

    def test_frequency_error_at_limits(self, synth):
        """Test frequency accuracy at sweep range limits."""
        for f_out in [2.7e9, 2.87e9, 3.0e9]:
            # TODO: Set frequency and measure with external equipment
            # TODO: Verify error < 100 kHz
            pass


class TestODMRSweepHardware:
    """Test full CW-ODMR sweep with hardware."""

    def test_sweep_run_mock_counter(self, synth):
        """Test sweep.run() with a mock photon counter."""
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=3.0e9, n_points=31)

        # Mock counter that returns increasing counts
        counter_values = [100 + i for i in range(31)]
        counter_idx = [0]

        def mock_counter():
            val = counter_values[counter_idx[0]]
            counter_idx[0] += 1
            return val

        # TODO: Run sweep and collect counts
        # freqs, counts = sweep.run(mock_counter)
        # TODO: Verify sweep completed without errors
        pass

    def test_sweep_with_real_counter(self, synth):
        """Test sweep.run() with a real photon counter (e.g., via DAQ)."""
        # TODO: Connect photon counter to Red Pitaya ADC
        # TODO: Define counter callback reading ADC
        # TODO: Run sweep and plot result
        pass

    def test_sweep_dwell_time_respected(self, synth):
        """Verify dwell time between frequency steps."""
        # TODO: Measure actual time per frequency point
        # TODO: Verify dwell_s + lock time < measured time < dwell_s + lock time + margin
        pass


class TestLockDetect:
    """Test PLL lock detect monitoring."""

    def test_lock_detect_pin(self, rp_instance):
        """Monitor lock detect output (MUXOUT) from ADF4355."""
        # TODO: Read lock detect pin state after frequency change
        # TODO: Verify it goes high when locked
        pass


class TestRFOutput:
    """Test RF output via external equipment."""

    def test_rf_power_output(self, synth):
        """Verify RF output power level with power meter."""
        synth.set_frequency(2.87e9)

        # TODO: Measure RF power at 2.87 GHz
        # TODO: Verify it matches expected +5 dBm
        pass

    def test_rf_frequency_accuracy(self, synth):
        """Verify RF output frequency on spectrum analyzer."""
        synth.set_frequency(2.87e9)

        # TODO: Measure RF frequency on spectrum analyzer
        # TODO: Verify it matches target within ±100 kHz
        pass

    def test_rf_phase_noise(self, synth):
        """Measure phase noise (optional, requires equipment)."""
        # TODO: Measure phase noise on spectrum analyzer
        # TODO: Verify it meets spec (< -80 dBc/Hz @ 10 kHz offset)
        pass


# Markers for skip/xfail
pytestmark = pytest.mark.skipif(
    not HAS_PYRPL or not os.getenv("REDPITAYA_HOST"),
    reason="PyRPL not installed or Red Pitaya not configured",
)


if __name__ == "__main__":
    # Run online tests
    # E.g.: REDPITAYA_HOST=rp-f0f9ae.local pytest tests/test_online.py -v
    pytest.main([__file__, "-v"])
