import numpy as np
from hardware.adf4355 import ADF4355


class ODMRSweep:
    """
    CW-ODMR frequency sweep controller.

    Reads the NV fluorescence signal from a photodiode connected to the
    Red Pitaya analog input (IN1 or IN2). At each frequency point the
    scope is triggered for dwell_s seconds; the mean voltage of that
    acquisition window is the measurement.

    Example
    -------
        sweep = ODMRSweep(synth, rp, adc_channel=1,
                          f_start=2.7e9, f_stop=3.0e9, n_points=301)
        freqs, voltages = sweep.run()

        # Or drive manually:
        for freq in sweep:
            voltage = sweep.read_voltage()
            sweep.record(voltage)
        freqs, voltages = sweep.result()
    """

    def __init__(
        self,
        synth: ADF4355,
        rp=None,
        adc_channel: int = 1,
        f_start: float = 2.7e9,
        f_stop: float = 3.0e9,
        n_points: int = 301,
        dwell_s: float = 10e-3,
    ):
        """
        Parameters
        ----------
        synth       : ADF4355 instance
        rp          : PyRPL Pyrpl instance; required for ADC acquisition.
                      If None, only manual record() / run(read_fn=...) work.
        adc_channel : Red Pitaya analog input channel (1 = IN1, 2 = IN2)
        f_start     : sweep start frequency (Hz)
        f_stop      : sweep stop frequency (Hz)
        n_points    : number of frequency steps
        dwell_s     : scope acquisition window per point (seconds).
                      Must be > PLL lock time (~2 ms).
        """
        self.synth = synth
        self._rp = rp
        self._adc_channel = adc_channel
        self.freqs = np.linspace(f_start, f_stop, n_points)
        self.dwell_s = dwell_s
        self._signal = []
        self._idx = 0

    # ------------------------------------------------------------------
    # ADC acquisition
    # ------------------------------------------------------------------

    def _acquire_voltage(self) -> float:
        """
        Trigger a Red Pitaya scope acquisition of duration dwell_s and
        return the mean voltage on the configured ADC channel.

        The scope is retriggered on every call so dwell_s controls the
        integration window directly.
        """
        if self._rp is None:
            raise RuntimeError(
                "rp (PyRPL instance) is required for ADC acquisition. "
                "Pass rp= when constructing ODMRSweep, or use run(read_fn=...)."
            )
        scope = self._rp.rp.scope
        scope.duration = self.dwell_s
        scope.trigger_source = "immediately"
        ch1, ch2 = scope.curve()
        data = ch1 if self._adc_channel == 1 else ch2
        return float(np.mean(data))

    def read_voltage(self) -> float:
        """Acquire and return mean photodiode voltage for the current point."""
        return self._acquire_voltage()

    # ------------------------------------------------------------------
    # Iterator
    # ------------------------------------------------------------------

    def __iter__(self):
        self._signal = []
        self._idx = 0
        return self

    def __next__(self):
        if self._idx >= len(self.freqs):
            raise StopIteration
        f = self.freqs[self._idx]
        self.synth.set_frequency(f)
        # Timing is provided by the scope acquisition in _acquire_voltage(),
        # not a separate sleep, so the caller should call read_voltage() or
        # record() immediately after receiving each frequency.
        self._idx += 1
        return f

    # ------------------------------------------------------------------
    # Data recording
    # ------------------------------------------------------------------

    def record(self, voltage: float):
        """Manually record a signal value (V or any scalar) for the current point."""
        self._signal.append(voltage)

    def result(self):
        """Returns (frequencies_hz, voltages) as numpy arrays."""
        return self.freqs[: len(self._signal)], np.array(self._signal)

    # ------------------------------------------------------------------
    # Convenience run
    # ------------------------------------------------------------------

    def run(self, read_fn=None):
        """
        Run the full sweep automatically.

        Parameters
        ----------
        read_fn : callable, optional
            Zero-argument function returning a float. If provided, it is
            called instead of the built-in ADC acquisition — useful for
            offline testing or alternative readout hardware.
            If None, reads from the Red Pitaya ADC (requires rp).

        Returns
        -------
        freqs    : np.ndarray  (Hz)
        voltages : np.ndarray  (V)
        """
        acquire = read_fn if read_fn is not None else self._acquire_voltage
        self._signal = []
        for _ in self:
            self._signal.append(acquire())
        return self.result()
