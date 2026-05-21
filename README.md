# redpit-nv — CW-ODMR Control for NV Centers

Python control stack for running continuous-wave optically detected magnetic resonance (CW-ODMR) on NV centers in diamond, using a [Red Pitaya](https://redpitaya.com/) as the controller and an ADF4355 fractional-N PLL synthesizer as the microwave source.

> **Note:** Do not install `pyrpl` via pip — the PyPI release is out of date. Install from source; see [Installation](#installation).

---

## Overview

In a CW-ODMR experiment the microwave frequency is swept across the NV spin resonance (~2.87 GHz at zero field). When the microwave matches the resonance, spin population is transferred and NV fluorescence drops. A photodiode records this dip; its position encodes the local magnetic field and its width encodes spin coherence.

This package handles the full software chain:

```text
Host PC
├── ADF4355 driver  ──────────── calculates PLL registers from target frequency
├── RPSynthTransport (Paramiko) ─ SSHes to RP, uploads + starts SPI daemon
│       └── TCP socket ─────────── one message per frequency step
│
└── pyrpl (PyRPL) ──────────────── scope / ADC readout (photodiode signal)

Red Pitaya ARM
└── rp_daemon.py ────────────────  bit-bangs SPI via /dev/mem
                                    no per-toggle network round-trips
```

The SPI bit-bang loop runs **on the RP's ARM core** — not on the host — so all 60+ GPIO toggles per register word happen locally. The host pays only one TCP round-trip (~1 ms) per frequency step.

---

## Hardware

| Component | Details |
| --- | --- |
| Red Pitaya | STEMlab 125-14 (125 MHz internal clock) |
| Synthesizer | [EV-ADF4355SD1Z](https://www.analog.com/en/resources/evaluation-hardware-and-software/evaluation-boards-kits/EV-ADF4355SD1Z.html) evaluation board |
| Reference | Onboard 122.88 MHz differential TCXO (Vectron VCC6-LAB-122M880000) |
| SPI wiring | E2 Pin 3 (DIO0\_P) = DATA, E2 Pin 5 (DIO1\_P) = CLK, E2 Pin 7 (DIO2\_P) = LE |
| Photodiode | Connected to Red Pitaya IN1 (or IN2) |

The eval board's TCXO gives a PFD of **61.44 MHz** (÷2 after R-counter), which covers the NV sweep range of 2.7–3.0 GHz with the ADF4355 output divider set to ÷2 (VCO at 5.4–6.0 GHz).

---

## Installation

**Requirements:** Python 3.11-3.13, a Red Pitaya on your local network.

```bash
git clone <this-repo>
cd redpit-nv-testing
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Install PyRPL from source (the pip release is stale):

```bash
git clone https://github.com/pyrpl-fpga/pyrpl
pip install -e pyrpl
```

---

## Configuration

All connection details are passed as environment variables — no credentials in code.

| Variable | Required | Description |
| --- | --- | --- |
| `REDPITAYA_HOST` | Yes | Hostname or IP of the Red Pitaya (e.g. `rp-f0f9ae.local`) |
| `REDPITAYA_PASSWORD` | No | SSH / PyRPL password (default: empty) |
| `REDPITAYA_CONFIG` | No | PyRPL config file path (default: `pyrpl_config.yml`) |

**PowerShell:**

```powershell
$env:REDPITAYA_HOST = "rp-f0f9ae.local"
$env:REDPITAYA_PASSWORD = "yourpassword"
```

**bash / zsh:**

```bash
export REDPITAYA_HOST=rp-f0f9ae.local
export REDPITAYA_PASSWORD=yourpassword
```

---

## Quick Start

### Scripted sweep

```bash
python scripts/run_odmr_sweep.py
```

Connects, sweeps 2.70–3.00 GHz in 301 steps, saves data to `data/odmr_<timestamp>.npz`, and writes a PNG plot.

### Interactive notebook

```bash
jupyter lab notebooks/odmr_demo.ipynb
```

Step-by-step walkthrough: pre-flight register verification → hardware connection → sanity sweep → full sweep → Lorentzian fit → save.

### From your own script

```python
import logging
from hardware import ADF4355, RPSynthTransport
from experiments.odmr import ODMRSweep

logging.basicConfig(level=logging.INFO)

# 1 — SPI transport (SSH + on-device daemon)
transport = RPSynthTransport("rp-XXXXXX.local", password="...")
transport.connect()

synth = ADF4355(transport)
synth.init(f_init_hz=2.87e9)

# 2 — Scope / ADC (PyRPL — separate connection)
from pyrpl import Pyrpl
rp = Pyrpl(hostname="rp-XXXXXX.local", password="...", gui=False, config="pyrpl_config.yml")

# 3 — Sweep
sweep = ODMRSweep(synth, rp=rp, adc_channel=1,
                  f_start=2.70e9, f_stop=3.00e9, n_points=301, dwell_s=20e-3)
freqs, voltages = sweep.run()

transport.close()
```

---

## Architecture

```text
redpit-nv-testing/
│
├── hardware/
│   ├── utils.py          # ADF4355Config dataclass + calc_registers() + verify_frequency()
│   ├── adf4355.py        # High-level driver: init() / set_frequency()
│   ├── rp_transport.py   # Host-side: SSH, SFTP upload, daemon socket protocol
│   └── rp_daemon.py      # Runs ON the RP: /dev/mem GPIO, SPI bit-bang, TCP server
│
├── experiments/
│   └── odmr.py           # ODMRSweep: iterator over frequencies, scope ADC readout
│
├── scripts/
│   ├── basic_connect.py  # Smoke-test both connections
│   └── run_odmr_sweep.py # Full scripted sweep with save + plot
│
├── notebooks/
│   └── odmr_demo.ipynb   # Step-by-step interactive demo
│
└── tests/
    ├── test_offline.py   # No hardware — register math, sweep logic, mock scope
    └── test_online.py    # Hardware-in-the-loop stubs (skipped without RP)
```

### Key design choices

**SPI runs on the RP, not the host.**
Driving GPIO via SSH (sysfs or PyRPL socket) costs one network round-trip per pin toggle. At ~1 ms per toggle, a single 32-bit SPI word would take ~64 ms. Instead, `rp_daemon.py` is uploaded at startup and bit-bangs SPI locally via `/dev/mem`, reducing each frequency step to one TCP message.

**Two separate connections.**
`RPSynthTransport` (Paramiko) handles SPI. `pyrpl.Pyrpl` handles the scope. Keeping them separate means a scope transfer doesn't block the synthesizer and vice versa.

**`ADF4355Config` dataclass.**
All hardware constants — reference frequency, divider chain, CP current, GPIO pins — live in one place and derive their timing values as properties. Changing the reference clock automatically recalculates `f_pfd`, `adc_clk_div`, `adc_wait_s`, etc.

---

## Hardware Configuration

Override defaults by passing a custom `ADF4355Config`:

```python
from hardware.utils import ADF4355Config
from hardware import ADF4355

# Example: different reference frequency or pin wiring
cfg = ADF4355Config(
    f_ref_hz   = 125e6,     # external 125 MHz reference instead of onboard TCXO
    ref_mode   = 0,         # 0 = single-ended, 1 = differential
    cp_current = 0b0111,    # 2.50 mA — adjust to match your loop filter design
    pin_clk    = 3,         # DIO3_P
    pin_data   = 4,         # DIO4_P
    pin_le     = 5,         # DIO5_P
)
synth = ADF4355(transport, config=cfg)
```

### Pre-flight frequency check (no hardware needed)

```python
from hardware.utils import verify_frequency
verify_frequency(2.87e9)   # prints register hex values and error
```

---

## Logging

All modules log under their Python module name (`hardware.adf4355`, `hardware.rp_transport`).

```python
import logging

# INFO: lifecycle events (connected, sweep progress, init complete)
logging.basicConfig(level=logging.INFO)

# DEBUG: every socket command and response, register details
logging.basicConfig(level=logging.DEBUG)
```

If the RP daemon crashes during a sweep, the error message will point to `/tmp/adf4355_daemon.log` on the RP for diagnosis.

---

## Tests

Offline tests require no hardware and run in the venv:

```bash
pytest tests/test_offline.py -v
```

Online tests are skipped automatically when `REDPITAYA_HOST` is not set:

```bash
REDPITAYA_HOST=rp-XXXXXX.local pytest tests/test_online.py -v
```
