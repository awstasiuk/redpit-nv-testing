from socket import socket, AF_INET, SOCK_STREAM, SHUT_RDWR
from struct import pack
import numpy as np


class Client:
    def __init__(self):
        # network socket
        self.socket = None
        # ADC sample rate
        self.adc_rate = 125
        # CIC decimation rate
        self.cic_rate = 50
        # total delay
        self.last_delay = 0
        # read flag of the last event
        self.last_read = 0
        # total number of RX samples
        self.size = 0
        # RX events
        self.evts = []

    def connect(self, host):
        if self.socket is not None:
            return
        try:
            self.socket = socket(AF_INET, SOCK_STREAM)
            self.socket.settimeout(1)
            self.socket.connect((host, 1001))
        except:
            self.disconnect()

    def connected(self):
        return self.socket is not None

    def disconnect(self):
        if self.socket is None:
            return
        try:
            self.socket.shutdown(SHUT_RDWR)
        except:
            pass
        finally:
            self.socket.close()
            self.socket = None

    def send_command(self, code, data):
        if self.socket is None:
            return
        try:
            self.socket.sendall(pack("<Q", int(code) << 60 | int(data)))
        except:
            self.disconnect()

    def set_freqs(self, tx, rx):
        self.send_command(0, int(rx + 0.5) << 30 | int(tx + 0.5))

    def set_rates(self, adc, cic):
        self.adc_rate = adc
        self.cic_rate = cic
        self.send_command(1, cic)

    def set_dac(self, level):
        lvl = int(level / 100.0 * 4095 + 0.5)
        self.send_command(2, lvl)

    def set_level(self, level):
        lvl = int(level / 100.0 * 32766 + 0.5)
        self.send_command(3, lvl)

    def set_pin(self, pin):
        self.send_command(4, pin)

    def clear_pin(self, pin):
        self.send_command(5, pin)

    def clear_events(self):
        self.last_delay = int(self.adc_rate * self.cic_rate * 2.0 + 0.5)
        self.last_read = 0
        self.size = 0
        self.evts.clear()
        self.send_command(6, 0)

    def update_size(self):
        sz = int(self.last_delay / (self.cic_rate * 2.0) + 0.5)
        if sz > 0:
            self.evts.append((self.last_read, sz))
            self.send_command(9, self.last_read << 40 | (sz - 1))
        if self.last_read:
            self.size += sz
        self.last_delay = 0
        self.last_read = 0

    def add_event(self, delay, sync=0, gate=0, read=0, level=0, tx_phase=0, rx_phase=0):
        dly = int(delay * self.adc_rate + 0.5)
        lvl = int(level / 100.0 * 32766 + 0.5)
        txp = int(tx_phase / 360.0 * 0x3FFFFFFF + 0.5)
        rxp = int(rx_phase / 360.0 * 0x3FFFFFFF + 0.5)
        self.send_command(7, lvl << 44 | gate << 41 | sync << 40 | (dly - 1))
        self.send_command(8, rxp << 30 | txp)
        if self.last_read == read:
            self.last_delay += dly
        else:
            self.update_size()
            self.last_delay = dly
            self.last_read = read

    def read_time(self):
        self.update_size()

        time = np.empty(self.size, np.float32)
        keep = 0
        skip = 0

        for read, size in self.evts:
            if read:
                time[keep : keep + size] = np.arange(keep + skip, keep + skip + size)
                keep += size
            else:
                skip += size

        return time * (self.cic_rate * 2.0 / self.adc_rate)

    def read_data(self):
        self.update_size()

        if self.socket is None:
            return None

        data = np.zeros(self.size * 2, np.complex64)
        view = data.view(np.uint8)
        limit = view.size
        offset = 0

        self.send_command(10, self.size)

        while offset < limit:
            try:
                buffer = self.socket.recv(limit - offset)
            except:
                return None
            size = len(buffer)
            if size == 0:
                return None
            view[offset : offset + size] = np.frombuffer(buffer, np.uint8)
            offset += size

        return data
