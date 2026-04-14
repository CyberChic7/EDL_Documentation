# Software — Biomedical Monitor (Display and Webserver)

## Platform

**Target:** Host PC / Laptop running Python 3.9+  
**OS:** Windows 10/11 (tested); Linux/macOS compatible with minor path adjustments  
**Role in System:** Receives processed ECG and IPG waveform packets with timestamps of peaks and feet respectively, sent over UDP (wirelessly) from the ESP32, processes them into clinically meaningful parameters, displays a real-time desktop GUI, and simultaneously serves a web dashboard accessible over LAN or the internet via ngrok.

---

## Files in This Folder

| File | Purpose |
|------|---------|
| `display.py` | PyQt6 desktop GUI — UDP receiver, packet parser, signal processing engine, live waveform plots, vitals state writer |
| `webserver.py` | Flask web server that reads `vitals_state.json` and serves a browser-based dashboard |
| `bp_xgboost_model.pkl` | Pre-trained XGBoost model for cuffless blood pressure estimation from PTT-derived features |
| `vitals_state.json` | Shared state file — written by `display.py` every ~250 ms, read by `webserver.py` on every browser poll |

---

## System Architecture

```
STM32 Black Pill
  │  SPI (dual MAX30001)
  │  I2C (INA219)
  ▼
ESP32
  │  UDP packets → port 12345 (Wi-Fi)
  ▼
[ display.py  —  PyQt6 Desktop GUI ]
  │  Packet parse (binary framing: 0x0A 0xFA ... 0x0B)
  │  ECG preprocessing + Pan-Tompkins R-peak detection
  │  PTT / PWV / HR from on-board STM32 flags
  │  HRV metrics (SDNN, RMSSD, pNN50) every 5 s
  │  ECG morphology (QRS, PR, QTc, ST) every 5 s
  │  XGBoost BP inference
  │  Live pyqtgraph waveform plots + vital cards
  │
  ▼  atomic JSON write every ~250 ms
[ vitals_state.json ]
  │
  ▼  HTTP /api/vitals (polled every 350 ms by browser)
[ webserver.py  —  Flask + ngrok ]
  │
  ▼
Browser Dashboard (LAN or public ngrok URL)
```

`display.py` and `webserver.py` run **simultaneously** as two independent processes. They communicate entirely through `vitals_state.json` — no sockets or shared memory between them. Either can be restarted independently without affecting the other.

---

## display.py — Desktop GUI and Signal Processing Engine

### What it does

`display.py` is a **PyQt6 desktop application** (class `DualPTT`). It opens a 1400×950 window with live waveform plots and a vital signs panel, while simultaneously doing all signal processing and writing results to `vitals_state.json` for the web dashboard.

#### 1. UDP Receiver

On clicking **"Connect UDP Listener"**, a non-blocking UDP socket is bound to `0.0.0.0:12345`. The ESP32 streams packets to this port over Wi-Fi. A `QTimer` fires every 20 ms to drain the socket buffer.

#### 2. Packet Parser (`PacketParser` class)

Each packet uses a fixed binary framing: two-byte start marker `0x0A 0xFA`, a 29-byte payload, and a stop byte `0x0B` (total 36 bytes). The parser accumulates incoming bytes into an internal buffer and extracts complete packets using `struct.unpack`:

| Payload Offset | Field | Type |
|----------------|-------|------|
| 0–3 | ECG1 sample (Board 1) | int32 LE |
| 4–7 | BioZ1 / APW1 sample (Board 1) | int32 LE |
| 8–11 | ECG2 sample (Board 2) | int32 LE |
| 12–15 | BioZ2 / APW2 sample (Board 2) | int32 LE |
| 16 | Flags byte (R-peak / foot1 / foot2) | uint8 |
| 17–28 | V_bus (V), I_mA, P_mW from INA219 | 3× float32 LE |

The flags byte is set by the STM32's on-board DSP before transmission:
- `FLAG_R_PEAK = 0x01` — this sample coincides with a detected ECG R-peak
- `FLAG_APW1_FOOT = 0x02` — this sample is the foot of APW1 (active IPG channel)
- `FLAG_APW2_FOOT = 0x04` — this sample is the foot of APW2 (passive IPG channel)

#### 3. ECG Signal Processing (`ECGProcessor` class)

**ECG morphology and HRV** (computed on the last 10 s of buffered data, triggered every 5 seconds):
- Heart rate from mean R-R interval; Bradycardia (< 50 bpm) and Tachycardia (> 110 bpm) alerts
- **SDNN** — standard deviation of all R-R intervals in the window
- **RMSSD** — root mean square of successive R-R differences
- **pNN50** — percentage of successive R-R differences exceeding 50 ms
-
#### 4. PTT and PWV Calculation

R-peak and foot positions are read directly from the **flags embedded in each packet by the STM32** — no second foot-detection pass is run on the Python side. For each APW1 foot, the closest following APW2 foot is located and the sample-index difference gives the PTT:

```
PTT (ms) = (APW2_foot_index − APW1_foot_index) / FS × 1000
```

`FS = 128 Hz`. Only values in the physiologically plausible range 160–450 ms are accepted. The last 50 valid PTT measurements are averaged (rolling deque). PWV is derived as:

```
PWV (m/s) = DISTANCE_M / (PTT_mean / 1000)
```

`DISTANCE_M = 1.35` m is the configured inter-electrode distance (set at the top of the file).

#### 5. Blood Pressure Inference

The XGBoost model receives four features derived from the averaged PTT:

| Feature | Expression |
|---------|------------|
| `PTT` | mean PTT in ms |
| `inv_PTT` | 1 / PTT |
| `inv_PTT2` | 1 / PTT² |
| `ln_PTT` | ln(PTT) |

This feature set captures the nonlinear BP–PTT relationship described in the Milestone 3 report: `BP = a₀ + √(a₁ + a₂/PTT²)`. The model outputs a [systolic, diastolic] array displayed as `"SYS/DIA"`.

#### 6. JSON State Export

Every ~250 ms (`EXPORT_INTERVAL = 0.25 s`) and also immediately after each morphology analysis, all computed values are serialised to `vitals_state.json`. To avoid read/write races with `webserver.py` on Windows, the write uses an **atomic temp-file-then-move** strategy (`tempfile.NamedTemporaryFile` → `shutil.move`) with up to 5 retries on move failure.

Waveform arrays are downsampled to a maximum of 180 points before writing (`step = max(1, len / 180)`) to keep the JSON payload small for the 350 ms browser poll cycle.

#### 7. Desktop GUI Layout

The PyQt6 window contains:
- **Top bar** — Connect/Disconnect UDP button, connection status, live battery readout (V / mA / mW from INA219)
- **Vital cards** — Heart Rate, Blood Pressure (estimated), Pulse Wave Velocity, Average PTT
- **ECG Morphology & HRV panel** — 8-cell grid (SDNN, RMSSD, pNN50, Rhythm, QRS, PR, QTc, ST Offset) with a clinical alerts bar below
- **Three live pyqtgraph waveform plots** (dark theme, X-axis linked):
  - ECG1 — with dashed green vertical markers at each R-peak
  - APW1 (IPG Active / Board 1) — with green scatter dots at detected foot points
  - APW2 (IPG Passive / Board 2) — with green scatter dots at detected foot points
- **Footer** — packet count and buffer duration for debugging

---

## webserver.py — Browser Dashboard

### What it does

`webserver.py` is a lightweight Flask application with two routes:

**`GET /`** — serves the complete dashboard HTML. The entire frontend (HTML, CSS, Chart.js charts, polling JavaScript) is embedded as a single Python string, so no separate template directory is required.

**`GET /api/vitals`** — reads `vitals_state.json` on every request and returns it as JSON with `Cache-Control: no-cache` headers. The browser polls this endpoint every 350 ms and updates all displayed elements accordingly.

The browser dashboard renders:
- Four vital cards: Heart Rate, Blood Pressure, PWV, Average PTT
- Battery panel: voltage, current, power
- ECG morphology & HRV panel mirroring the desktop GUI
- Clinical alerts bar (turns red when flags are present)
- Three live Chart.js waveform charts (ECG, APW1, APW2)
- `OFFLINE` / `LIVE` badge derived from the `connected` field in the JSON

On startup, the server also establishes an **ngrok HTTPS tunnel** to port 5000 and prints the public URL to the console, allowing access from any device without firewall configuration. The ngrok auth token is set near the bottom of the file.

---

## bp_xgboost_model.pkl

A serialised XGBoost multi-output regressor loaded once at startup by `display.py` via `joblib.load()`. Outputs `[systolic, diastolic]` from the four PTT features above. If the file is missing at startup, BP inference is silently skipped and the dashboard shows `---/---`.

---

## vitals_state.json

Auto-created and overwritten continuously by `display.py` at runtime. Do not edit manually while the system is running. Example structure:

```json
{
  "ts": 1712345678.4,
  "connected": true,
  "hr": 72.0,
  "bp": "118/76",
  "pwv": 8.3,
  "ptt": 142.1,
  "v_bus": 7.412,
  "i_ma": 183.2,
  "p_mw": 1357.1,
  "sdnn": 38.1,
  "rmssd": 29.4,
  "pnn50": 14.2,
  "reg": "Regular",
  "qrs": 92.0,
  "pr": 158.0,
  "qtc": 412.0,
  "st": 0.012,
  "alerts": [],
  "wave_ecg": [ ... ],
  "wave_apw1": [ ... ],
  "wave_apw2": [ ... ],
  "markers_r": [ ... ],
  "markers_f1": [ ... ],
  "markers_f2": [ ... ]
}
```

---

## Running the Software

Run both scripts in **separate terminals**. 

**Terminal 1:**
```bash
python webserver.py
```
Copy the ngrok URL printed to the console and open it in any browser.

**Terminal 2:**
```bash
python display.py
```
A desktop window opens. Click **"Connect UDP Listener"**. Ensure the ESP32 is powered and configured to send UDP packets to port `12345` on your machine's IP. The browser `LIVE` badge lights up once the first valid packet arrives.

See `SETUP.md` for full environment setup instructions including package installation.
