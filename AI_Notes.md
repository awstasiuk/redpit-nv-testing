# AI Notes — NV Center FPGA Control

## Project Goal
Build a Python-based control system for an NV center experiment using a Red Pitaya STEMlab 125-14.
Near-term: tone generation and oscilloscope verification.
Long-term: ODMR, Rabi, T1/T2 measurements via IQ mixing + pulsed sequences + photon counting.

---

## Architecture Decision: Communication Layer

Two viable approaches exist:

### Option A — Red Pitaya SCPI (built-in, no custom firmware)
- Uses the built-in SCPI server over TCP port 5000
- `redpitaya_scpi` Python library or raw socket
- Can generate CW and burst tones immediately, no FPGA reprogramming needed
- Simpler for initial scope tests
- **Limitation:** Pulse timing is software-driven; jitter is ~ms, not µs
- Best for: initial connectivity tests, tone gen, oscilloscope verification

### Option B — Custom Red Pitaya application (as shown in PulsedNMR example)
- Plain TCP socket client on port 1001 with a 64-bit binary command protocol
- Sub-µs pulse timing, hardware-driven event sequences
- Phase-coherent IQ generation at the FPGA level
- **Requirement:** A specific RP application (e.g. Pavel Demin's NMR app) must be installed and
  running on the board. That app includes a custom FPGA bitstream + a server process on port 1001.
  The Python client itself is just a socket client — no changes needed on the PC side.
- Best for: actual NV pulse sequences (Rabi, ODMR, spin echo)

### Decision
Start with **SCPI** for immediate connectivity/scope tests. Migrate to custom firmware once basic
comms are verified and pulse sequence needs demand it. The PulsedNMR client class is the target
design pattern for the custom-firmware layer.

---

## PulsedNMR Protocol Note
`external_examples/PulsedNMR/PulsedNMR.py` is a plain Python TCP socket client — no special
dependencies. It speaks to a Red Pitaya application (e.g. Pavel Demin's NMR app) running on
port 1001. That application is what provides the custom FPGA logic; the Python side is just a client.
Protocol:
- 64-bit little-endian commands; top 4 bits = command code, lower 60 bits = payload
- Commands 0–10 cover: freq, CIC rate, DAC/signal level, GPIO, events, readout
- Returns complex64 I/Q data over the same socket

---

## First Steps Status

- [x] Set up Python environment: `requirements.txt` created; venv `redpit-env` already has numpy/matplotlib/scipy/jupyter
- [x] `nv_control/scpi.py` — raw-socket SCPI client (no extra dependencies); context manager, query, configure_sine helpers
- [x] `scripts/test_connection.py` — connect, IDN query, LED blink, clean disconnect
- [x] `scripts/gen_tone.py` — CW sine on OUT1 (or OUT2), holds until Enter, then cleans up
- [x] `scripts/gen_iq_tones.py` — OUT1/OUT2 as I/Q pair (OUT2 lags OUT1 by 90°); scope XY check
- [ ] Plan custom firmware path for pulse sequences (next phase)

### Running the scripts

```powershell
# Activate venv first
.\redpit-env\Scripts\Activate.ps1

# 1. Test connectivity (replace IP with your board's address)
python scripts/test_connection.py 192.168.1.100

# 2. Generate 1 MHz CW tone on OUT1
python scripts/gen_tone.py 192.168.1.100 --freq 1e6 --amp 1.0

# 3. I/Q pair on OUT1 + OUT2 (verify with 2-ch scope or XY mode)
python scripts/gen_iq_tones.py 192.168.1.100 --freq 1e6 --amp 1.0
```

### SCPI server on Red Pitaya
The SCPI server must be running on the board. Start it via the RP web interface or SSH:
```bash
systemctl start redpitaya_scpi   # on the board over SSH
```

---

## Key Parameters (from PulsedNMR example)
- ADC sample rate: 122.88 MHz (can vary; 125 MHz is nominal)
- CIC decimation: 48 (example)
- TX/RX frequency: 1 MHz (example; NV ESR is ~2.87 GHz so IQ upconversion needed)
- Phase encoding: 30-bit, covers 0–360° as 0–(2^30 - 1)
- Data format: complex64, two channels interleaved (in1 = even, in2 = odd)

---

## NV Center Background
- NV zero-field splitting: ~2.87 GHz (ms=0 ↔ ms=±1)
- Optical readout: 532 nm excitation, ~637–800 nm photoluminescence
- Red Pitaya direct output: 0–60 MHz — needs upconversion for GHz control
- IQ mixing approach: Red Pitaya generates IF at e.g. 10–100 MHz; external LO at ~2.77–2.87 GHz;
  mixer produces sideband at target frequency
- Photon counting: eventually hook into Red Pitaya ADC or dedicated counter card

---

## Changes Log
| Date       | Change |
|------------|--------|
| 2026-05-05 | Initial notes created; surveyed PulsedNMR example; researched best practices |
| 2026-05-05 | Created nv_control/scpi.py, scripts/test_connection.py, gen_tone.py, gen_iq_tones.py, requirements.txt |
