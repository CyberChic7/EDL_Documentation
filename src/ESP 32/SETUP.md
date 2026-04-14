# Environment Setup Guide — ESP32

---

## Step 1 — Install Arduino IDE

If not already installed, download Arduino IDE (1.8.x or 2.x):
https://www.arduino.cc/en/software

---

## Step 2 — Add ESP32 Board Support

Arduino IDE does not include ESP32 boards by default.

1. Open Arduino IDE
2. Go to **File → Preferences**
3. Find the **"Additional boards manager URLs"** field
4. Paste the following URL (add it on a new line if you already have the STM32 URL there):
```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
```
5. Click **OK**
6. Go to **Tools → Board → Boards Manager**
7. Search for **esp32** and install the package named **"esp32"** by Espressif Systems
8. Wait for the installation to complete

---

## Step 3 — Select the Correct Board

1. Go to **Tools → Board → esp32 → ESP32 Dev Module**

No further board-specific settings need to be changed from defaults.

---

## Step 4 — Configure Wi-Fi Credentials

Open the `.ino` file and add your network details:

```cpp
const char* ssid     = "your_network_name";
const char* password = "your_network_password";
```

This must be the **same network your laptop is connected to**. A mobile hotspot works
well for portable use — simply enable hotspot on your phone and connect both the laptop
and the ESP32 to it.

---

## Step 5 — Flash the ESP32

The ESP32 can be flashed directly from Arduino IDE over USB — no external programmer
is needed.

1. Connect the ESP32 to your PC via USB
2. Go to **Tools → Port** and select the COM port that appears for the ESP32
3. Click **Upload** (right arrow icon)
4. Arduino IDE will compile and flash automatically
5. Once complete, open **Tools → Serial Monitor** at **115200 baud**
6. You should see the board connect to Wi-Fi and print its IP address

---

## Troubleshooting

**ESP32 not appearing as a COM port**
- Install the CP2102 or CH340 USB-to-Serial driver depending on your ESP32 board variant
- CP2102 driver: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
- CH340 driver: https://www.wch-ic.com/downloads/CH341SER_EXE.html

**Upload fails with "connecting..." timeout**
- Hold the **BOOT** button on the ESP32 while clicking Upload, release once uploading begins
- Some boards require this to enter download mode

**Wi-Fi connection fails**
- Confirm the SSID and password are correct in the code
- Ensure the network is 2.4 GHz — ESP32 does not support 5 GHz Wi-Fi
- If using a mobile hotspot, make sure it is active before the ESP32 boots
