# IM-PULSE User Manual

**Device Name:** IM-PULSE  
**Version:** Final Prototype (Fully Integrated Embedded System)  

---

## 1. Introduction & Target Audience

**IM-PULSE** is a compact, portable biomedical monitoring device that simultaneously acquires **ECG** and **dual Arterial Pulse Waveforms (APW)** using bioimpedance (IPG) measurements. It calculates real-time **Pulse Transit Time (PTT)**, **Pulse Wave Velocity (PWV)**, **heart rate (HR)**, **cuffless blood pressure (BP)**, and several heart-rate-variability (HRV) and ECG morphology parameters.

**Target Audience**  
This device is designed for **patients who require continuous or frequent cardiac health monitoring outside clinical settings**, especially in situations where a compact, portable solution is preferred over bulky hospital machines. It is ideal for home use, travel, or remote monitoring.

---

## 2. Hardware Overview

- **Enclosure:** 3D-printed compact table-top box containing the STM32F411 Black Pill, ESP32, dual MAX30001 boards, INA219 power monitor, custom PCB, and rechargeable battery pack (2 × 18650 cells with BMS).
- **Power:** Rechargeable via USB-C. Battery status is displayed live on the laptop GUI.
- **On/Off Switch:** Located on the side of the enclosure.
- **Electrode Ports:** Two dedicated ports on the enclosure for the 6-electrode harness.
- **Wireless:** ESP32 acts as a wireless bridge (must be configured to join your chosen Wi-Fi network).

---

## 3. Powering the Device

### 3.1 Charging the Battery
- Connect a USB-C cable to the dedicated charging point.
- The device can be charged while powered off or on.
- Battery status (voltage, current, power) appears on the laptop GUI once connected.

### 3.2 Using the Device (Battery Mode – Truly Portable)
1. Charge the device fully.
2. Flip the **On/Off switch** on the side of the enclosure to **ON**.
3. The device boots automatically and runs without any external power source.

### 3.3 Alternative: USB-Powered Mode
- Connect a USB-C cable from your laptop to either the STM32 or ESP32 port (same method used for programming).
- The device works normally while tethered.

---

## 4. Electrode Placement

1. Power on the device.
2. Plug the **electrode harnesses** into the two dedicated ports on the enclosure.
3. Place the **six electrodes** exactly as shown in the diagram in `reports/MON-04-M4.pdf`, page 5
   - **Chest (proximal APW + ECG):** Two electrodes on the upper chest on subclavian arteries
   - **Left foot (distal APW):** One electrode on the left foot artery.
   - **Abdomen reference:** Two reference electrodes on the abdomen at the doralis pedis.
   - **Right Leg Drive (RLD):** One electrode on the right leg (for noise reduction).

4. Ensure skin is clean and dry. Press electrodes firmly for good contact.

---

## 5. Starting the Monitoring Session (Step-by-Step)

### Prerequisites
- A laptop with Python 3.9 or newer installed.
- The device is powered on (see Section 3).
- Electrodes are correctly placed on the user.

### Step-by-Step Instructions

1. **Create a Wi-Fi hotspot** (recommended: use your phone’s mobile hotspot).  
   The ESP32 has to be configured to automatically join this network (SSID and password to be set in the ESP32 firmware — see `src/ESP 32/README.md` for details).

2. **Connect your laptop** to the **same hotspot/network**.

3. Open a terminal (Command Prompt / PowerShell / Terminal) and navigate to the repository root:

   ```bash
   cd path/to/your/IM-PULSE-repo
   ```

4. Start the Desktop GUI (this is the main interface):

   ```bash
   cd "src/Display & Webserver"
   python display.py
   ```

5. A window will open.  
   Click the “Connect UDP Listener” button.

6. Live monitoring begins within a few seconds:  
   You will see three real-time waveforms:
   - ECG (top)
   - Proximal APW (chest – middle)
   - Distal APW (foot – bottom)

7. Numerical vitals appear on the right side:
   - Heart Rate (bpm)
   - Blood Pressure (SYS/DIA in mmHg)
   - Average PTT (ms)
   - PWV (m/s)
   - Battery status (V / mA / mW)
   - HRV metrics: SDNN, RMSSD, pNN50
   - ECG morphology: QRS, PR, QTc, ST Offset
   - Rhythm status and clinical alerts (if any)

### (Optional) Phone Dashboard

In a second terminal (still inside the `src/Display & Webserver` folder):

```bash
python webserver.py
```

A public URL (ngrok) or local IP will be printed.  
Open that URL on your phone (connected to the same network).  
All waveforms and vitals are now mirrored on your phone.

---

## 6. Understanding the Display

### Desktop GUI (`display.py`) shows:
- Three live waveform plots with markers for R-peaks and APW foot points.
- Vital cards (HR, BP, PTT, PWV).
- Battery information.
- HRV and ECG morphology panel.
- Clinical alerts bar (turns red if anomalies detected).

### Web Dashboard (phone) shows:
- Exactly the same information in a clean browser view.

---

## 7. Shutting Down Safely

- Click “Disconnect” in the GUI.
- Close both terminal windows.
- Flip the On/Off switch to OFF (or unplug USB).
- Gently remove the electrodes.
- Store electrodes in a cool, dry place.

---

## 8. Limitations

- Blood-pressure estimation is trained on a single-subject dataset and may vary between users.
- Foot APW signal can occasionally be noisier than chest signals.
- Device is for demonstration and educational use only.

---

## 9. Troubleshooting

| Problem | Solution |
|---|---|
| No waveforms appear | Ensure device is powered ON, electrodes are attached firmly, and you clicked “Connect UDP Listener”. Check that laptop and ESP32 are on the same Wi-Fi network. |
| Battery status shows 0 % | Charge the device for at least 30 minutes. |
| ESP32 not connecting | Restart the device and the hotspot. Verify SSID/password in ESP32 firmware (see `src/ESP 32/README (1).md`). |
| GUI shows “---/---” for BP | Wait a few seconds after connection — the model needs valid PTT values first. |
| Dashboard stays OFFLINE | Make sure both `display.py` and `webserver.py` are running from the same folder. |
| Poor signal quality | Re-apply electrodes or move away from phone chargers/motors. |

For advanced setup or flashing firmware, refer to the individual `SETUP.md` files in each `src/` subfolder.

---

## 10. Maintenance & Cleaning

- Clean electrodes with alcohol wipes after each use.
- Recharge the battery when GUI shows < 30 %.
- Do not open the enclosure unless you are part of the development team.
- Store the device in a cool, dry place.

---

Thank you for using IM-PULSE!  
For any questions or feedback, contact the team via the GitHub repository.  
Last Updated: April 2026
