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

Logging:
  This module logs under the name 'hardware.rp_transport'.
  Set log level to DEBUG to see every command and response.

    import logging
    logging.basicConfig(level=logging.DEBUG)
"""

import io
import logging
import os
import socket
import time

logger = logging.getLogger(__name__)

DAEMON_PORT             = 5025
DAEMON_REMOTE_PATH      = '/tmp/adf4355_daemon.py'
SOCKET_TIMEOUT_S        = 10.0  # seconds before a stalled recv is treated as failure
_DAEMON_CONNECT_RETRIES = 6
_DAEMON_CONNECT_DELAY   = 0.3   # seconds between socket connect attempts


def _daemon_source() -> str:
    here = os.path.dirname(__file__)
    path = os.path.join(here, 'rp_daemon.py')
    try:
        with open(path, 'r') as f:
            return f.read()
    except OSError as exc:
        raise RuntimeError(f"Cannot read daemon script at {path}: {exc}") from exc


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
        self._sockfile                   = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        """SSH to RP, upload daemon, start it, and open the command socket."""
        try:
            import paramiko
        except ImportError as exc:
            raise ImportError(
                "paramiko is required for hardware connectivity: pip install paramiko"
            ) from exc

        self._connect_ssh(paramiko)
        self._upload_daemon()
        self._start_daemon()
        self._connect_socket()

    def _connect_ssh(self, paramiko):
        logger.info("SSH → %s@%s", self._username, self._hostname)
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self._ssh.connect(
                self._hostname,
                username=self._username,
                password=self._password,
            )
        except paramiko.AuthenticationException as exc:
            raise ConnectionError(
                f"SSH authentication failed for {self._username}@{self._hostname}. "
                f"Check REDPITAYA_PASSWORD."
            ) from exc
        except (paramiko.NoValidConnectionsError, OSError) as exc:
            raise ConnectionError(
                f"Cannot reach {self._hostname}. "
                f"Check hostname and network connection."
            ) from exc
        logger.info("SSH connected to %s", self._hostname)

    def _upload_daemon(self):
        logger.info("Uploading daemon → %s", DAEMON_REMOTE_PATH)
        src = _daemon_source()
        try:
            sftp = self._ssh.open_sftp()
            sftp.putfo(io.BytesIO(src.encode()), DAEMON_REMOTE_PATH)
            sftp.chmod(DAEMON_REMOTE_PATH, 0o755)
            sftp.close()
        except Exception as exc:
            raise RuntimeError(
                f"SFTP upload of daemon script failed: {exc}"
            ) from exc
        logger.debug("Daemon uploaded (%d bytes)", len(src))

    def _start_daemon(self):
        cmd = (
            f'pkill -f adf4355_daemon.py 2>/dev/null; '
            f'python3 {DAEMON_REMOTE_PATH} > /tmp/adf4355_daemon.log 2>&1 &'
        )
        logger.info("Starting daemon on RP")
        logger.debug("Remote: %s", cmd)
        try:
            self._ssh.exec_command(cmd)
        except Exception as exc:
            raise RuntimeError(f"Failed to start daemon on RP: {exc}") from exc

    def _connect_socket(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(SOCKET_TIMEOUT_S)

        for attempt in range(1, _DAEMON_CONNECT_RETRIES + 1):
            try:
                logger.debug(
                    "Socket connect attempt %d/%d → %s:%d",
                    attempt, _DAEMON_CONNECT_RETRIES, self._hostname, DAEMON_PORT,
                )
                self._sock.connect((self._hostname, DAEMON_PORT))
                self._sockfile = self._sock.makefile('r')
                logger.info("Daemon socket open on %s:%d", self._hostname, DAEMON_PORT)
                return
            except ConnectionRefusedError:
                if attempt == _DAEMON_CONNECT_RETRIES:
                    raise ConnectionError(
                        f"Daemon on {self._hostname}:{DAEMON_PORT} refused connection "
                        f"after {_DAEMON_CONNECT_RETRIES} attempts. "
                        f"Inspect /tmp/adf4355_daemon.log on the RP for startup errors."
                    )
                logger.debug(
                    "Daemon not ready yet, retrying in %.1f s …", _DAEMON_CONNECT_DELAY
                )
                time.sleep(_DAEMON_CONNECT_DELAY)
            except OSError as exc:
                raise ConnectionError(
                    f"Socket connect to {self._hostname}:{DAEMON_PORT} failed: {exc}"
                ) from exc

    def close(self):
        """Disconnect socket and SSH. The daemon process stays running on the RP."""
        logger.info("Closing transport")
        if self._sock:
            try:
                self._send('QUIT')
                logger.debug("QUIT acknowledged")
            except Exception:
                logger.debug("QUIT failed (connection may already be down)")
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock     = None
            self._sockfile = None
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None
        logger.info("Transport closed")

    # ------------------------------------------------------------------
    # Low-level socket protocol
    # ------------------------------------------------------------------

    def _send(self, line: str) -> str:
        """Send one command line, block until the daemon responds, return the response."""
        logger.debug("→ %s", line)
        try:
            self._sock.sendall((line + '\n').encode())
        except OSError as exc:
            raise ConnectionError(
                f"Lost connection to daemon while sending: {exc}"
            ) from exc

        try:
            resp = self._sockfile.readline()
        except socket.timeout:
            raise ConnectionError(
                f"Daemon did not respond within {SOCKET_TIMEOUT_S:.0f} s. "
                f"It may have crashed — inspect /tmp/adf4355_daemon.log on the RP."
            )
        except OSError as exc:
            raise ConnectionError(
                f"Lost connection to daemon while receiving: {exc}"
            ) from exc

        if not resp:
            raise ConnectionError(
                "Daemon closed the connection unexpectedly. "
                "Inspect /tmp/adf4355_daemon.log on the RP."
            )

        resp = resp.strip()
        logger.debug("← %s", resp)
        return resp

    # ------------------------------------------------------------------
    # ADF4355 commands
    # ------------------------------------------------------------------

    def cmd_init(self, regs: dict, adc_wait_us: int):
        """Send a full power-up initialisation sequence to the daemon."""
        logger.debug("INIT adc_wait=%d µs", adc_wait_us)
        reg_str = ' '.join(f'{regs[f"reg{i}"]:08X}' for i in range(13))
        try:
            resp = self._send(f'INIT {adc_wait_us} {reg_str}')
        except ConnectionError:
            logger.error("INIT failed — daemon connection lost")
            raise
        if resp != 'OK':
            raise RuntimeError(f'ADF4355 INIT rejected by daemon: {resp}')
        logger.debug("INIT OK")

    def cmd_set_frequency(self, regs: dict, adc_wait_us: int):
        """Send an 8-step frequency update sequence to the daemon."""
        r10           = regs['reg10']
        r4_rst_on     = regs['reg4'] | (1 << 4)
        r2            = regs['reg2']
        r1            = regs['reg1']
        r0_no_autocal = regs['reg0'] & ~(1 << 21)
        r4_rst_off    = regs['reg4'] & ~(1 << 4)
        r0            = regs['reg0']

        words    = [r10, r4_rst_on, r2, r1, r0_no_autocal, r4_rst_off, r0]
        word_str = ' '.join(f'{w:08X}' for w in words)

        try:
            resp = self._send(f'FREQ {adc_wait_us} {word_str}')
        except ConnectionError:
            logger.error("FREQ failed — daemon connection lost")
            raise
        if resp != 'OK':
            raise RuntimeError(f'ADF4355 FREQ rejected by daemon: {resp}')
