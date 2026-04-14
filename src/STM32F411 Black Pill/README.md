# STM32F411CEU6 (Black Pill) — Firmware

## Platform

**MCU:** STM32F411CEU6 — "Black Pill" development board  
**Core:** ARM Cortex-M4F @ 100 MHz  
**RAM:** 128 KB SRAM  
**Flash:** 512 KB  
**IDE used for development:** Arduino IDE (with STM32duino board support package)  
**Flashing tool:** STM32 ST-Link Utility  

---

## Role in the System

This firmware is the central acquisition and processing engine of the device. It:

- Drives **two MAX30001 AFE chips** simultaneously over SPI to acquire ECG and Bioimpedance (BioZ/IPG) waveforms at 128 Hz
- Runs **onboard DSP algorithms** (Pan-Tompkins R-peak detection, APW foot detection) in real time to timestamp cardiac events
- Reads **power telemetry** from an INA219 sensor over I2C
- Packages all data into a structured binary serial packet and forwards it to the **ESP32** over UART (Serial1 at 57600 baud), which then relays it wirelessly to the laptop

The laptop-side Python software receives this stream, decodes the packets, and computes PTT and blood pressure estimates. It displays them and also runs a webserver so that this information can be accessed by any device with access to the internet.

---

## Hardware Connections

### SPI — MAX30001 (both chips share SPI1 bus)

| Signal | STM32 Pin |
|--------|-----------|
| SCK    | PA5       |
| MISO   | PA6       |
| MOSI   | PA7       |
| CS1 (Chip 1 — ECG1 + BioZ1) | PA0 |
| CS2 (Chip 2 — ECG2 + BioZ2) | PB0 |

Both chips share the same SPI bus. The firmware enforces strict CS discipline — the inactive chip's CS is always driven HIGH before asserting the active chip's CS.

### I2C — INA219 Power Monitor

Connected on the default Arduino Wire I2C bus of the Black Pill. Refer to STM32F411CEU6 pinout for SDA/SCL pin mapping. The INA219 measures bus voltage, current, and power from the 5V supply rail and appends these readings to every transmitted packet.

### UART — ESP32

| Signal  | STM32 Pin |
|---------|-----------|
| TX (Serial1) | PA9  |
| RX (Serial1) | PA10 |

Baud rate: **57600**. The STM32 also echoes the same packet stream over USB Serial at **230400 baud** for direct laptop debugging when connected via USB.


```


## Firmware Overview

### Sampling

Both chips are polled at **128 Hz** (8 ms period). ECG and BioZ samples are read alternately per chip on each tick (every other tick reads BioZ) to avoid SPI contention. Raw samples are stored in 1024-sample circular ring buffers.

### DSP Pipeline

#### Pan-Tompkins R-Peak Detection (ECG1)
A sample-by-sample implementation of the Pan-Tompkins algorithm runs on the ECG1 stream:
1. **High-pass + Low-pass filter** — removes baseline wander and high-frequency noise
2. **Derivative** — enhances the steep QRS slope
3. **Squaring** — makes all values positive and amplifies large slopes
4. **Moving window integration** (19-sample / ~150 ms window) — aggregates QRS energy into a smooth peak
5. **Adaptive threshold** (mean + 1.5σ) — fires an R-peak event with a 32-sample refractory period

#### APW1 Foot Detection — Cubic Polynomial Fit (BioZ1, ECG-triggered)
On each R-peak detection, a search window equal to 50% of the previous beat length is opened on the BioZ1 ring buffer. The window is divided into 10 segments; least-squares lines are fitted to adjacent segments and their intersections are computed. A cubic polynomial is fitted to these intersection points, and its minimum gives the foot of the proximal APW. This method (based on Kazanavicius 2005) is robust to noise and avoids the instability of pure derivative methods.

#### APW2 Foot Detection — Asymmetric Morphological V-Shape (BioZ2, self-triggered)
The distal IPG foot detector runs independently without needing an ECG trigger. It maintains a 25-sample (187 ms) sliding window on the BioZ2 stream and looks for an asymmetric V-shape: a slow left-side drop (diastolic run-off) followed by a sharp right-side rise (systolic upstroke). Both sides must clear adaptive amplitude thresholds derived from a running EMA variance estimate. A 40-sample refractory period (~310 ms) prevents double detection.

### Packet Format

Every 8 ms, a 36-byte packet is transmitted:

```
Header  [5 bytes]: 0x0A 0xFA 0x1D 0x00 0x02
Payload [29 bytes]:
  ECG1   [4 bytes, little-endian int32]
  BioZ1  [4 bytes, little-endian int32]
  ECG2   [4 bytes, little-endian int32]
  BioZ2  [4 bytes, little-endian int32]
  flags  [1 byte]: bit0=R-peak  bit1=APW1-foot  bit2=APW2-foot
  INA219 Vbus    [4 bytes, float]
  INA219 Current [4 bytes, float]
  INA219 Power   [4 bytes, float]
Footer  [2 bytes]: 0x00 0x0B
```

