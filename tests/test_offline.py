"""
Offline unit tests for ADF4355 driver and ODMR sweep.
These tests require no hardware — only the local modules.
"""

import pytest
import numpy as np
from hardware.utils import calc_registers, verify_frequency
from hardware.adf4355 import ADF4355
from experiments.odmr import ODMRSweep


class TestCalcRegisters:
    """Test register calculation for ADF4355."""

    def test_nv_center_frequency(self):
        """Test calculation at NV zero-field frequency (2.87 GHz)."""
        f_out = 2.87e9
        regs = calc_registers(f_out)

        # Verify register dict structure
        for i in range(13):
            assert f"reg{i}" in regs
            assert isinstance(regs[f"reg{i}"], int)
            assert 0 <= regs[f"reg{i}"] <= 0xFFFFFFFF

        # Verify metadata
        assert "_meta" in regs
        meta = regs["_meta"]
        assert "f_out_target_hz" in meta
        assert "f_out_achieved_hz" in meta
        assert "error_hz" in meta
        assert "INT" in meta
        assert "FRAC1" in meta

        # Check frequency error is reasonable (< 1 Hz for 2.87 GHz)
        assert meta["error_hz"] < 1.0

    def test_sweep_range_boundaries(self):
        """Test frequencies at sweep range limits (2.7–3.0 GHz)."""
        for f_out in [2.7e9, 2.85e9, 2.87e9, 2.90e9, 3.0e9]:
            regs = calc_registers(f_out)
            meta = regs["_meta"]

            # Frequency error should be small
            assert meta["error_hz"] < 1.0

            # INT should be in prescaler range [23, ∞)
            assert meta["INT"] >= 23

    def test_vco_frequency_valid(self):
        """Test that VCO frequency is within spec [3.4, 6.8] GHz."""
        for f_out in [2.7e9, 2.87e9, 3.0e9]:
            regs = calc_registers(f_out)
            meta = regs["_meta"]
            f_vco = meta["f_vco_hz"]

            # RF_DIV = 2, so VCO = 2 × RF output
            assert 3.4e9 <= f_vco <= 6.8e9
            assert abs(f_vco - f_out * 2) < 1  # VCO = RF × RF_DIV

    def test_out_of_range_raises(self):
        """Test that out-of-range frequencies raise ValueError."""
        # Too low (VCO < 3.4 GHz)
        with pytest.raises(ValueError):
            calc_registers(1.0e9)

        # Too high (VCO > 6.8 GHz)
        with pytest.raises(ValueError):
            calc_registers(4.0e9)

    def test_register_control_bits(self):
        """Verify control bits [DB3:DB0] match register number."""
        f_out = 2.87e9
        regs = calc_registers(f_out)

        for i in range(13):
            reg_val = regs[f"reg{i}"]
            control_bits = reg_val & 0xF  # bits [3:0]
            assert control_bits == i, f"reg{i} control bits {control_bits} != {i}"


class TestVerifyFrequency:
    """Test offline frequency verification utility."""

    def test_verify_returns_dict(self, capsys):
        """Test that verify_frequency returns correct structure."""
        regs = verify_frequency(2.87e9, verbose=False)

        # Should match calc_registers output
        for i in range(13):
            assert f"reg{i}" in regs

    def test_verify_verbose_output(self, capsys):
        """Test verbose output formatting."""
        regs = verify_frequency(2.87e9, verbose=True)
        captured = capsys.readouterr()

        # Check that output contains expected strings
        assert "Target" in captured.out
        assert "Achieved" in captured.out
        assert "Error" in captured.out
        assert "GHz" in captured.out
        assert "Register hex values" in captured.out


class TestODMRSweep:
    """Test ODMR sweep iteration and data recording."""

    class MockSynth:
        """Mock ADF4355 synth for testing sweep logic."""

        def __init__(self):
            self.freqs_set = []
            self.last_freq = None

        def set_frequency(self, f_hz, wait_lock=True):
            self.freqs_set.append(f_hz)
            self.last_freq = f_hz

    def test_sweep_iteration(self):
        """Test that sweep correctly iterates over frequencies."""
        synth = self.MockSynth()
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=2.9e9, n_points=5, dwell_s=0.001)

        # Manually iterate
        freqs_received = []
        for freq in sweep:
            freqs_received.append(freq)

        # Should have 5 frequencies
        assert len(freqs_received) == 5

        # Should cover the range
        assert freqs_received[0] == pytest.approx(2.7e9, rel=1e-9)
        assert freqs_received[-1] == pytest.approx(2.9e9, rel=1e-9)

        # Synth should have received all 5 set calls
        assert len(synth.freqs_set) == 5

    def test_record_counts(self):
        """Test recording photon counts."""
        synth = self.MockSynth()
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=2.8e9, n_points=3)

        # Iterate and record counts
        for i, freq in enumerate(sweep):
            sweep.record(100 + i * 10)  # counts: 100, 110, 120

        freqs, counts = sweep.result()
        assert len(freqs) == 3
        assert len(counts) == 3
        assert counts[0] == 100
        assert counts[1] == 110
        assert counts[2] == 120

    def test_run_with_count_fn(self):
        """Test convenience run() method with a mock counter function."""
        synth = self.MockSynth()
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=2.8e9, n_points=5)

        # Mock counter that increments
        counter_values = [50, 100, 75, 90, 120]
        counter_idx = [0]

        def mock_counter():
            val = counter_values[counter_idx[0]]
            counter_idx[0] += 1
            return val

        freqs, counts = sweep.run(mock_counter)

        assert len(freqs) == 5
        assert len(counts) == 5
        assert list(counts) == counter_values

    def test_sweep_freq_array(self):
        """Test that sweep frequency array is correctly spaced."""
        synth = self.MockSynth()
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=2.8e9, n_points=11)

        # Frequencies should be linspace [2.7, 2.75, ..., 2.8] GHz
        expected = np.linspace(2.7e9, 2.8e9, 11)
        np.testing.assert_allclose(sweep.freqs, expected, rtol=1e-12)

    def test_multiple_iterations(self):
        """Test that sweep can be iterated multiple times."""
        synth = self.MockSynth()
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=2.8e9, n_points=3)

        # First sweep
        synth.freqs_set.clear()
        for freq in sweep:
            sweep.record(10)

        first_count = len(synth.freqs_set)

        # Second sweep should restart
        synth.freqs_set.clear()
        for freq in sweep:
            sweep.record(20)

        second_count = len(synth.freqs_set)

        assert first_count == second_count == 3


class TestIntegration:
    """Integration tests combining multiple modules."""

    def test_calc_registers_for_sweep_range(self):
        """Verify registers can be calculated for all sweep points."""
        freqs = np.linspace(2.7e9, 3.0e9, 31)

        for f in freqs:
            regs = calc_registers(f)
            meta = regs["_meta"]
            # Error should be sub-Hz across the range
            assert meta["error_hz"] < 1.0

    def test_sweep_with_calculated_freqs(self):
        """Test sweep iteration with frequency calculation."""

        class SynthWithCalc(
            ODMRSweep.MockSynth if hasattr(ODMRSweep, "MockSynth") else object
        ):
            def __init__(self):
                self.freqs_set = []

            def set_frequency(self, f_hz, wait_lock=True):
                # Verify frequency can be calculated
                regs = calc_registers(f_hz)
                self.freqs_set.append((f_hz, regs))

        synth = SynthWithCalc()
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=3.0e9, n_points=5)

        for freq in sweep:
            pass

        # All 5 frequencies should have valid register sets
        assert len(synth.freqs_set) == 5


if __name__ == "__main__":
    # Run tests with pytest if available
    pytest.main([__file__, "-v"])
