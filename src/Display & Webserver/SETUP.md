# Setup Guide — Laptop Software (display.py + webserver.py)

This guide walks through everything needed to go from a fresh machine to a running the monitoring session. Follow the steps in order.

---

## Prerequisites

- Python **3.9 or newer** installed and added to PATH
- The STM32 Black Pill firmware already flashed and the ESP32 configured to forward UDP packets to your machine's IP on port 12345
- `pip` available (bundled with Python 3.9+)

Check your versions:
```bash
python --version
pip --version
```


## Step 1 — Install Required Python Packages

```bash
pip install flask pyqtgraph PyQt6 pyserial pyngrok numpy scipy scikit-learn xgboost joblib pandas
```

### Package reference

| Package | Purpose |
|---------|---------|
| `PyQt6` | Desktop GUI framework for `display.py` |
| `pyqtgraph` | Fast real-time waveform plots inside the PyQt6 window |
| `flask` | HTTP web server for the browser dashboard in `webserver.py` |
| `pyngrok` | Creates a public HTTPS ngrok tunnel for remote access |
| `numpy` | Array operations for all signal processing |
| `scipy` | Butterworth / notch filters, `filtfilt`, `medfilt` |
| `pandas` | DataFrame construction for XGBoost feature input |
| `scikit-learn` | Required by the saved XGBoost pipeline |
| `xgboost` | Blood pressure inference model |
| `joblib` | Deserialise `bp_xgboost_model.pkl` |

---

## Step 4 — Configure the UDP Port and Network

`display.py` listens for UDP packets on `0.0.0.0:12345`. The ESP32 must be configured to send packets to your laptop's IP address on port `12345`. No changes to `display.py` are needed unless you want to change the port — in which case update:

```python
# display.py — near the top
UDP_PORT = 12345
```

**Finding your laptop's IP address:**
- **Windows:** Run `ipconfig` in a terminal — look for the IPv4 address of your Wi-Fi adapter
- **Linux / macOS:** Run `ip addr` or `ifconfig`

Ensure your laptop and the ESP32 are on the **same Wi-Fi network**. If you are on a university or corporate network that blocks device-to-device UDP, you may need to use a mobile hotspot instead.

---

## Step 5 — Configure the Electrode Distance

`DISTANCE_M` in `display.py` is the physical distance in metres between the ECG electrode site and the IPG electrode site on the subject. This is used to compute PWV and feeds into BP estimation. The current value is:

```python
# display.py — near the top
DISTANCE_M = 1.35
```

Adjust this if your electrode placement changes. An incorrect value will scale the PWV reading and propagate error into blood pressure estimation.

---

## Step 6 — Set Up ngrok (for Public Dashboard Access)

ngrok exposes the local Flask server to the internet so the dashboard is accessible from any device.

1. Create a free account at [https://ngrok.com](https://ngrok.com)
2. Copy your **Authtoken** from [https://dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)
3. Open `webserver.py` and replace the existing token:

```python
ngrok.set_auth_token("YOUR_TOKEN_HERE")
```

If you only need LAN access and not a public URL, comment out the entire ngrok block in `webserver.py`. The dashboard will still be accessible at `http://<your-laptop-ip>:5000` from any device on the same network.

---

## Step 7 — Verify the Model File

Confirm that `bp_xgboost_model.pkl` is present in the `src/laptop` directory alongside the scripts:

```
src/laptop/
├── display.py
├── webserver.py
├── bp_xgboost_model.pkl     ← must be here
└── vitals_state.json        ← auto-created at runtime; do not pre-create
```

`display.py` looks for the file by the relative path `'bp_xgboost_model.pkl'`. If you run the script from a different working directory, either `cd` into `src/laptop` first or update the path at the top of `display.py`.

---

## Step 8 — Run the Software

Open **two separate terminal windows**, both with the virtual environment activated, both from the `src/laptop` directory.

**Terminal 1 — Start the web server first:**
```bash
python webserver.py
```

Expected console output:
```
======================================================================
  PUBLIC URL (share with anyone):
  → https://xxxx-xx-xx-xxx-xx.ngrok-free.app
======================================================================

PTT Web Dashboard Started
  Local:     http://localhost:5000
  Network:   http://192.168.x.x:5000
  Public:    https://xxxx-xx-xx-xxx-xx.ngrok-free.app
```

Open any of these URLs in a browser. The dashboard shows `● OFFLINE` until data flows.

**Terminal 2 — Start the GUI and signal processor:**
```bash
python display.py
```

A desktop window opens. Click **"Connect UDP Listener"**. Power on the device and ensure the ESP32 is sending packets to your machine's IP on port 12345. Within a few seconds, the desktop GUI and the browser dashboard will both begin showing live data and the badge will change to `● LIVE`.

---

## Troubleshooting

**Desktop window does not open / `ModuleNotFoundError: No module named 'PyQt6'`**
- Confirm the virtual environment is activated and that `PyQt6` and `pyqtgraph` are installed

**"Connect UDP Listener" clicked but no data appears**
- Verify the ESP32 is powered and on the same network as your laptop
- Check that the destination IP in the ESP32 firmware matches your laptop's current IP (this changes if you switch networks)
- On Windows, check that the firewall is not blocking UDP on port 12345 — temporarily disable it to test

**`ModuleNotFoundError` for any other package**
- Run `pip install <package-name>` with the virtual environment active

**ngrok fails: `Your account is limited to 1 simultaneous ngrok agent session`**
- Open [dashboard.ngrok.com](https://dashboard.ngrok.com) → Agents, and terminate any existing sessions

**Dashboard shows `● OFFLINE` even after display.py is running**
- Check that `vitals_state.json` is being created/updated in the `src/laptop` folder
- Both scripts must be run from the same working directory so they resolve the JSON path identically

**Blood pressure shows `---/---`**
- The model requires at least one complete accepted PTT value (in the 160–450 ms range) before it produces output. Wait a few seconds after connecting. If it never appears, confirm `bp_xgboost_model.pkl` is present and that the PTT values being detected are within the valid range (check the "AVERAGE PTT" card in the desktop GUI).

**`vitals_state.json` write errors in console**
- On Windows, this occasionally happens if both processes try to access the file simultaneously. The atomic write includes 5 retries — these errors are usually transient and self-resolving. If they persist, ensure no other program (e.g. a text editor) has the JSON file open.
