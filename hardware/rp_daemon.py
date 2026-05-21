#!/usr/bin/env python3
"""
ADF4355 SPI daemon — runs on the Red Pitaya ARM core.

Bit-bangs the ADF4355 SPI bus directly via /dev/mem so that all 64+ GPIO
toggles per register word happen locally, with no per-toggle network round-trips.

The host uploads this file via SFTP and starts it over SSH.
It then connects a TCP socket and sends one command per frequency step.

Protocol (newline-terminated text):
  INIT <adc_wait_us> <r0> <r1> ... <r12>
      Full power-up sequence (datasheet order 12→1, wait, 0).
      Register values in uppercase hex, no prefix.

  FREQ <adc_wait_us> <r10> <r4_rst_on> <r2> <r1> <r0_no_autocal> <r4_rst_off> <r0>
      8-step frequency update sequence. Includes ADC wait + 2 ms PLL lock wait.

  QUIT
      Graceful disconnect (daemon stays alive, accepts next connection).

Responses:
  OK       command completed
  ERR msg  something went wrong
"""

import mmap
import os
import socket
import struct
import sys
import time

# ---------------------------------------------------------------------------
# Red Pitaya FPGA housekeeping register map
# Base address for the housekeeping module
# ---------------------------------------------------------------------------
HK_BASE   = 0x40000000
MAP_SIZE  = 4096
DIR_P_OFF = 0x10   # P-pin direction register (bit N = 1 → output)
OUT_P_OFF = 0x18   # P-pin output register

# SPI pin assignments — DIO index into the P-bank (0 = DIO0_P, 1 = DIO1_P, …)
# Must match ADF4355Config.pin_clk / pin_data / pin_le.
#
# Default wiring (E2 expansion connector):
#   E2 Pin 3  DIO0_P  →  DATA (SPI_MOSI / SDI)
#   E2 Pin 5  DIO1_P  →  CLK  (SPI_SCK)
#   E2 Pin 7  DIO2_P  →  LE   (SPI_CS#)
#   Any GND           →  GND
#
# If you rewire, change the three constants below and update ADF4355Config
# on the host to the same values so they stay in sync.
# Only P-bank pins (OUT_P_OFF) are driven here; do not assign N-bank pins
# (E2 even pins 4, 6, 8 …) without adding N-bank register writes.
PIN_CLK  = 1   # DIO1_P  (E2 Pin 5)
PIN_DATA = 0   # DIO0_P  (E2 Pin 3)
PIN_LE   = 2   # DIO2_P  (E2 Pin 7)

BIT_CLK  = 1 << PIN_CLK   # 0x01
BIT_DATA = 1 << PIN_DATA  # 0x02
BIT_LE   = 1 << PIN_LE    # 0x04
MASK_SPI = BIT_CLK | BIT_DATA | BIT_LE

PORT = 5025


def main():
    fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
    mem = mmap.mmap(fd, MAP_SIZE, mmap.MAP_SHARED,
                    mmap.PROT_READ | mmap.PROT_WRITE,
                    offset=HK_BASE)

    def read32(off: int) -> int:
        return struct.unpack_from('<I', mem, off)[0]

    def write32(off: int, val: int):
        struct.pack_into('<I', mem, off, int(val) & 0xFFFFFFFF)

    def setup_pins():
        write32(DIR_P_OFF, read32(DIR_P_OFF) | MASK_SPI)   # set as outputs
        write32(OUT_P_OFF, read32(OUT_P_OFF) & ~MASK_SPI)  # drive all low

    def send_word(word32: int):
        # Latch Enable low before shifting
        out = read32(OUT_P_OFF) & ~MASK_SPI
        write32(OUT_P_OFF, out)

        for bit_idx in range(31, -1, -1):
            bit = (word32 >> bit_idx) & 1
            # Set DATA, CLK low in one write
            out = (out & ~(BIT_CLK | BIT_DATA)) | (bit * BIT_DATA)
            write32(OUT_P_OFF, out)
            # CLK high
            write32(OUT_P_OFF, out | BIT_CLK)

        # Final CLK low, then LE pulse
        out &= ~BIT_CLK
        write32(OUT_P_OFF, out)
        write32(OUT_P_OFF, out | BIT_LE)
        write32(OUT_P_OFF, out & ~BIT_LE)

    setup_pins()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', PORT))
    srv.listen(1)
    print(f'adf4355_daemon listening on :{PORT}', flush=True)

    while True:
        conn, _ = srv.accept()
        try:
            for raw in conn.makefile('r'):
                line = raw.strip()
                if not line:
                    continue
                parts = line.split()
                cmd   = parts[0]

                try:
                    if cmd == 'INIT':
                        # INIT <adc_wait_us> r0 r1 ... r12
                        adc_wait = int(parts[1]) * 1e-6
                        regs = [int(x, 16) for x in parts[2:15]]
                        for n in [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]:
                            send_word(regs[n])
                        time.sleep(adc_wait)
                        send_word(regs[0])
                        conn.sendall(b'OK\n')

                    elif cmd == 'FREQ':
                        # FREQ <adc_wait_us> r10 r4_rst_on r2 r1 r0_no_ac r4_rst_off r0
                        adc_wait = int(parts[1]) * 1e-6
                        words = [int(x, 16) for x in parts[2:9]]
                        send_word(words[0])   # reg10
                        send_word(words[1])   # reg4 counter-reset ON
                        send_word(words[2])   # reg2
                        send_word(words[3])   # reg1
                        send_word(words[4])   # reg0 autocal OFF
                        send_word(words[5])   # reg4 counter-reset OFF
                        time.sleep(adc_wait)
                        send_word(words[6])   # reg0 autocal ON → frequency changes
                        time.sleep(2e-3)      # PLL lock settle
                        conn.sendall(b'OK\n')

                    elif cmd == 'QUIT':
                        conn.sendall(b'OK\n')
                        break

                    else:
                        conn.sendall(f'ERR unknown command: {cmd}\n'.encode())

                except Exception as exc:
                    conn.sendall(f'ERR {exc}\n'.encode())

        except Exception:
            pass
        finally:
            conn.close()


if __name__ == '__main__':
    main()
