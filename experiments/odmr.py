import time
import math
import numpy as np
from hardware.adf4355 import ADF4355


class ODMRSweep:
    """
    CW-ODMR frequency sweep controller.

    Example
    -------
        sweep = ODMRSweep(synth, f_start=2.7e9, f_stop=3.0e9, n_points=301)
        for freq in sweep:
            counts = counter.read()   # your photon counter call here
            sweep.record(counts)
        spectrum = sweep.result()
    """

    def __init__(
        self,
        synth: ADF4355,
        f_start: float = 2.7e9,
        f_stop: float = 3.0e9,
        n_points: int = 301,
        dwell_s: float = 10e-3,
    ):
        """
        Parameters
        ----------
        synth    : ADF4355 instance
        f_start  : sweep start frequency (Hz)
        f_stop   : sweep stop frequency (Hz)
        n_points : number of frequency steps
        dwell_s  : integration time per point (seconds)
                   Must be > lock time (~2 ms) + your counting window.
        """
        self.synth = synth
        self.freqs = np.linspace(f_start, f_stop, n_points)
        self.dwell_s = dwell_s
        self._counts = []
        self._idx = 0

    def __iter__(self):
        self._counts = []
        self._idx = 0
        return self

    def __next__(self):
        if self._idx >= len(self.freqs):
            raise StopIteration
        f = self.freqs[self._idx]
        self.synth.set_frequency(f, wait_lock=True)
        time.sleep(self.dwell_s)
        self._idx += 1
        return f

    def record(self, count_value):
        """Call this after reading your photon counter at each step."""
        self._counts.append(count_value)

    def result(self):
        """Returns (frequencies_hz, counts) as numpy arrays."""
        return self.freqs[: len(self._counts)], np.array(self._counts)

    def run(self, count_fn):
        """
        Convenience method: run the full sweep automatically.

        Parameters
        ----------
        count_fn : callable
            Zero-argument function that returns a photon count (int or float).
            Will be called once per frequency point after the dwell.

        Returns
        -------
        freqs : np.ndarray  (Hz)
        counts: np.ndarray
        """
        self._counts = []
        for freq in self:
            counts = count_fn()
            self.record(counts)
        return self.result()
