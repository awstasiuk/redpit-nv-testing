"""
Host-side transport for the ADF4355 SPI daemon running on the Red Pitaya.

Startup sequence (call connect()):
  1. SSH into the RP via Paramiko.
  2. Upload rp_daemon.py to /tmp/ via SFTP.
  3. Start the daemon in the background.
  4. Open a TCP socket to the daemon's command port.

During sweeps:
  One socket message per frequency step.  The daemon bit-bangs SPI
  locally on the RP ARM core — no per-toggle network round-trips.
"""

import io
import os
import socket
import time


DAEMON_PORT        = 5025
DAEMON_REMOTE_PATH = '/tmp/adf4355_daemon.py'


def _daemon_source() -> str:
    here = os.path.dirname(__file__)
    with open(os.path.join(here, 'rp_daemon.py'), 'r') as f:
        return f.read()


class RPSynthTransport:
    """
    Manages SSH connection, daemon lifecycle, and socket protocol
    for the ADF4355 SPI daemon on the Red Pitaya.

    Usage
    -----
        transport = RPSynthTransport('rp-XXXXXX.local', password='...')
        transport.connect()
        # pass to ADF4355(transport)
        transport.close()
    """

    def __init__(self, hostname: str, password: str = '', username: str = 'root'):
        self._hostname = hostname
        self._password = password
        self._username = username
        self._ssh:  object | None        = None  # paramiko.SSHClient
        self._sock: socket.socket | None = None
        self._sockfile = None

    def connect(self):
        """SSH to RP, upload daemon, start it, and open the command socket."""
        try:
            import paramiko
        except ImportError as exc:
            raise ImportError("paramiko is required for hardware connectivity: pip install paramiko") from exc

        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(
            self._hostname,
            username=self._username,
            password=self._password,
        )

        # Upload daemon script
        src  = _daemon_source()
        sftp = self._ssh.open_sftp()
        sftp.putfo(io.BytesIO(src.encode()), DAEMON_REMOTE_PATH)
        sftp.chmod(DAEMON_REMOTE_PATH, 0o755)
        sftp.close()

        # Kill any stale instance, start fresh in background
        self._ssh.exec_command(
            f'pkill -f adf4355_daemon.py 2>/dev/null; '
            f'python3 {DAEMON_REMOTE_PATH} > /tmp/adf4355_daemon.log 2>&1 &'
        )
        time.sleep(0.5)  # give daemon time to bind its socket

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self._hostname, DAEMON_PORT))
        self._sockfile = self._sock.makefile('r')
        print(f'[RPSynthTransport] daemon connected on {self._hostname}:{DAEMON_PORT}')

    # ------------------------------------------------------------------
    # Low-level socket protocol
    # ------------------------------------------------------------------

    def _send(self, line: str) -> str:
        """Send a command line and return the daemon's response."""
        self._sock.sendall((line + '\n').encode())
        return self._sockfile.readline().strip()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def cmd_init(self, regs: dict, adc_wait_us: int):
        """
        Full power-up initialisation sequence.
        regs : dict with keys 'reg0'…'reg12' (32-bit ints).
        """
        reg_str = ' '.join(f'{regs[f"reg{i}"]:08X}' for i in range(13))
        resp = self._send(f'INIT {adc_wait_us} {reg_str}')
        if resp != 'OK':
            raise RuntimeError(f'ADF4355 INIT failed: {resp}')

    def cmd_set_frequency(self, regs: dict, adc_wait_us: int):
        """
        8-step frequency update sequence.
        regs : dict with keys 'reg0'…'reg12'.
        The transport computes the modified reg0/reg4 variants here so the
        daemon stays register-value agnostic.
        """
        r10           = regs['reg10']
        r4_rst_on     = regs['reg4'] | (1 << 4)
        r2            = regs['reg2']
        r1            = regs['reg1']
        r0_no_autocal = regs['reg0'] & ~(1 << 21)
        r4_rst_off    = regs['reg4'] & ~(1 << 4)
        r0            = regs['reg0']

        words    = [r10, r4_rst_on, r2, r1, r0_no_autocal, r4_rst_off, r0]
        word_str = ' '.join(f'{w:08X}' for w in words)
        resp = self._send(f'FREQ {adc_wait_us} {word_str}')
        if resp != 'OK':
            raise RuntimeError(f'ADF4355 FREQ failed: {resp}')

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Disconnect socket and close SSH session. Daemon stays running."""
        if self._sock:
            try:
                self._send('QUIT')
            except Exception:
                pass
            self._sock.close()
            self._sock = None
            self._sockfile = None
        if self._ssh:
            self._ssh.close()
            self._ssh = None
