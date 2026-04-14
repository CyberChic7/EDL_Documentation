# Environment Setup Guide — STM32F411CEU6 (Black Pill)

This guide walks through everything needed to go from a fresh machine to a compiled
and flashed Black Pill. Follow the steps in order.

---

## Step 1 — Install Arduino IDE

Download and install Arduino IDE (1.8.x or 2.x) from the official site:
https://www.arduino.cc/en/software

---

## Step 2 — Add STM32 Board Support

Arduino IDE does not include STM32 boards by default. You need to add the STM32duino
board package manually.

1. Open Arduino IDE
2. Go to **File → Preferences**
3. Find the **"Additional boards manager URLs"** field
4. Paste the following URL:
```
   https://github.com/stm32duino/BoardManagerFiles/raw/main/package_stmicroelectronics_index.json
```
5. Click **OK**
6. Go to **Tools → Board → Boards Manager**
7. Search for **STM32** and install the package named **"STM32 MCU based boards"** by STMicroelectronics
8. Wait for the installation to complete — this may take a few minutes

---

## Step 3 — Select the Correct Board

Once the package is installed:

1. Go to **Tools → Board → STM32 MCU based boards → Generic STM32F4 series**
2. Then go to **Tools → Board part number** and select **Generic F411CEUx**

---

## Step 4 — Install Required Libraries

Install the following libraries via **Tools → Manage Libraries**:

| Library | Author | Purpose |
|---------|--------|---------|
| `protocentral_max30001` | ProtoCentral | Driver for the MAX30001 ECG/BioZ AFE chip |
| `Adafruit INA219` | Adafruit | Driver for the INA219 power monitor |

Search for each by name and click Install. Accept any dependency installs when prompted.

---

## Step 5 — Hardware Setup Before Flashing

Before connecting anything, ensure:

- The ST-Link V2 programmer is connected to the Black Pill's SWD header with four wires:

| ST-Link Pin | Black Pill Pin |
|-------------|----------------|
| SWDIO       | DIO            |
| SWCLK       | CLK            |
| GND         | GND            |
| 3.3V        | 3.3V           |

- The two MAX30001 breakout boards are connected to the SPI1 bus as described in `README.md`
- Power is supplied either through the ST-Link 3.3V or via USB — do not power from both simultaneously

---

## Step 6 — Compile the Firmware

1. Open the `.ino` firmware file in Arduino IDE
2. Confirm the board is set to **Generic STM32F4 series → Generic F411CEUx** (Step 3)
3. Click **Verify / Compile** (tick icon)
4. When compilation succeeds, the output console will show a line similar to:
```
   Sketch uses XXXXX bytes ...
   Global variables use XXXXX bytes ...
```
5. Look for the build path in the same console output — it will read something like:
```
   C:\Users\<user>\AppData\Local\Temp\arduino_build_XXXXXX\
```
   The `.hex` file you need for flashing will be inside this folder.

---

## Step 7 — Flash Using STM32 ST-Link Utility

1. Download and install **STM32 ST-Link Utility** from STMicroelectronics if not already installed:
   https://www.st.com/en/development-tools/stsw-link004.html
2. Connect the ST-Link V2 to your PC via USB
3. Open STM32 ST-Link Utility
4. Go to **File → Open File** and navigate to the `.hex` file from Step 6
5. Click **Target → Program & Verify**
6. The utility will flash the board and verify the write
7. The Black Pill will reset automatically and begin streaming packets

---

## Troubleshooting

**Board not detected by ST-Link Utility**
- Check all four SWD wires are seated firmly
- Try pressing and holding the NRST button on the Black Pill while connecting

**Compilation fails with "board not found"**
- Confirm the STM32 board package installed correctly in Step 2
- Try removing and re-adding the board manager URL and reinstalling

**`protocentral_max30001` library not found**
- If it does not appear in the Library Manager, download it directly from
  https://github.com/protocentral/protocentral_max30001 and install via
  **Sketch → Include Library → Add .ZIP Library**

**Serial output is garbled**
- Confirm your serial monitor is set to **230400 baud**
- On some systems the Black Pill needs a moment after reset before USB Serial enumerates — wait 2–3 seconds after flashing before opening the monitor
