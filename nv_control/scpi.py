"""
Red Pitaya SCPI client.

Communicates with the built-in SCPI server (port 5000) over TCP.
No custom firmware required — works with the stock Red Pitaya OS.

SCPI server must be started on the board first:
  systemctl start redpitaya_scpi  (or via the RP web interface)
"""

import socket
import time


SCPI_PORT = 5000
DEFAULT_TIMEOUT = 5.0  # seconds


class SCPIError(Exception):
    pass


class RedPitaya:
    """Thin SCPI socket wrapper for Red Pitaya STEMlab."""

    def __init__(self, host: str, port: int = SCPI_PORT, timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        try:
            self._sock.connect((self.host, self.port))
        except OSError as e:
            self._sock = None
            raise SCPIError(f"Could not connect to {self.host}:{self.port} — {e}") from e

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ------------------------------------------------------------------
    # Low-level send / receive
    # ------------------------------------------------------------------

    def send(self, cmd: str) -> None:
        if not self._sock:
            raise SCPIError("Not connected")
        self._sock.sendall((cmd + "\r\n").encode())

    def recv(self) -> str:
        if not self._sock:
            raise SCPIError("Not connected")
        buf = b""
        while not buf.endswith(b"\r\n"):
            chunk = self._sock.recv(4096)
            if not chunk:
                raise SCPIError("Connection closed by remote")
            buf += chunk
        return buf.decode().strip()

    def query(self, cmd: str) -> str:
        self.send(cmd)
        return self.recv()

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def idn(self) -> str:
        return self.query("*IDN?")

    def reset(self) -> None:
        self.send("*RST")
        time.sleep(0.2)

    # ------------------------------------------------------------------
    # Signal generator — OUT1 / OUT2 (channel index 1 or 2)
    # ------------------------------------------------------------------

    def set_waveform(self, ch: int, shape: str = "SINE") -> None:
        """shape: SINE | SQUARE | TRIANGLE | SAWU | SAWD | PWM | ARBITRARY"""
        self.send(f"SOUR{ch}:FUNC {shape}")

    def set_frequency(self, ch: int, freq_hz: float) -> None:
        self.send(f"SOUR{ch}:FREQ:FIX {freq_hz:.6f}")

    def set_amplitude(self, ch: int, volts: float) -> None:
        """Peak voltage (0–1 V into 50 Ω, 0–2 V unloaded)."""
        self.send(f"SOUR{ch}:VOLT {volts:.4f}")

    def set_offset(self, ch: int, volts: float) -> None:
        self.send(f"SOUR{ch}:VOLT:OFFS {volts:.4f}")

    def set_phase(self, ch: int, degrees: float) -> None:
        self.send(f"SOUR{ch}:PHAS {degrees:.4f}")

    def output_on(self, ch: int) -> None:
        self.send(f"OUTPUT{ch}:STATE ON")

    def output_off(self, ch: int) -> None:
        self.send(f"OUTPUT{ch}:STATE OFF")

    def outputs_off(self) -> None:
        self.output_off(1)
        self.output_off(2)

    # ------------------------------------------------------------------
    # Convenience: configure and enable a channel in one call
    # ------------------------------------------------------------------

    def configure_sine(
        self,
        ch: int,
        freq_hz: float,
        amplitude_v: float = 1.0,
        phase_deg: float = 0.0,
        offset_v: float = 0.0,
    ) -> None:
        self.set_waveform(ch, "SINE")
        self.set_frequency(ch, freq_hz)
        self.set_amplitude(ch, amplitude_v)
        self.set_offset(ch, offset_v)
        self.set_phase(ch, phase_deg)
        self.output_on(ch)

    # ------------------------------------------------------------------
    # Digital I/O (LED, GPIO)
    # ------------------------------------------------------------------

    def set_led(self, index: int, state: bool) -> None:
        """Control on-board LEDs (index 0–7). May not be supported on all firmware."""
        val = 1 if state else 0
        self.send(f"DIG:PIN LED{index},{val}")
