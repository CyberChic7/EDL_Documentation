# IM-PULSE

## Team Information
**Team name:** IM-PULSE (Group MON-04)

**Team members:**
- Yashvardhan Khandegar — 23B1227
- Sudhindra Sahoo — 23B1312
- Jahnvi Sharma — 23B1926
- Vinay Hariharan — 23B1310
- Krunal Vaghela — 23B1262

## Project Abstract
IM-PULSE is a compact, portable biomedical monitoring device developed in the Electronic Device Lab (EDL) course at IIT Bombay. The system simultaneously acquires ECG and dual Arterial Pulse Waveforms (APW) from bioimpedance (IPG) measurements using six electrodes (chest + foot + abdomen reference). It performs onboard ECG R-peak detection and APW foot detection on an STM32F411 Black Pill, computes Pulse Transit Time (PTT), derives Pulse Wave Velocity (4–10 m/s), and estimates cuffless blood pressure via a pre-trained XGBoost model. Data is wirelessly streamed through an ESP32 bridge to a host laptop, where a PyQt6 desktop GUI provides live plotting and a Flask web dashboard delivers real-time vitals to any device with access to the internet.

The device solves the discomfort and bulkiness of conventional inflatable-cuff BP monitors and traditional ECG/Bio-Z instruments, offering a convenient solution for continuous or frequent cardiac health monitoring for cases where such devices might be inaccesible or unaffordable. This repository contains the complete embedded firmware, host software, hardware documentation, milestone reports.

## Deliverables in This Repository
This repository includes the following deliverables:

- STM32F411 Black Pill firmware for signal acquisition and on-board processing
- ESP32 firmware for wireless UART-to-UDP bridging
- Host-side Python software for desktop visualization and web dashboard delivery
- A pre-trained XGBoost model used for blood-pressure estimation
- Runtime state shared between the desktop app and the web server
- Setup notes and implementation notes for each software component
- Report PDFs documenting project progress (M0–M4)
- Images showing the PCB, CAD model, soldering, printed enclosure, simulation output, and final assembled device

## Repository Structure
### Root directory
- `README.md` — Main project overview and documentation entry point.
- `src/` — Source code and implementation files for the embedded and host software.
- `reports/` — PDF report submissions for the project.
- `others/` — Supporting media and supplementary documentation.

### `src/`
This folder contains the core implementation of the system.

#### `src/Display & Webserver/`
Host-side Python software running on a PC or laptop.

- `display.py` — PyQt6 desktop application, UDP receiver, packet parser, signal-processing engine, live plots, and vitals writer.
- `webserver.py` — Flask web server that reads the vitals state file and serves the browser dashboard.
- `bp_xgboost_model.pkl` — Pre-trained XGBoost model for cuffless blood pressure estimation.
- `vitals_state.json` — Shared JSON state updated by the desktop app and read by the web server.
- `README.md` — Component overview and architecture notes for the host-side software.
- `SETUP.md` — Setup and run instructions for the host-side software.

#### `src/ESP 32/`
ESP32 firmware used as the wireless communication bridge.

- `Firmware.ino` — Arduino sketch for receiving UART data from the STM32 and forwarding it over UDP.
- `README.md` — Overview of the ESP32 role, hardware connections, and design decisions.
- `SETUP.md` — Flashing and setup instructions for the ESP32 module.

#### `src/STM32F411 Black Pill/`
Main embedded firmware for the biomedical acquisition device.

- `Firmware.ino` — Arduino-based STM32 firmware for acquisition, processing, packet creation, and serial transmission.
- `README.md` — Overview of the STM32 role, hardware connections, and processing flow.
- `SETUP.md` — Flashing and setup instructions for the Black Pill board.

### `reports/`
This folder contains the submitted report files for the project.

- `MON-04-M0.pdf`
- `MON-04-M1.pdf`
- `MON-04-M2.pdf`
- `MON-04-M3.pdf`
- `MON-04-M4.pdf`

### `others/`
This folder contains supporting material that documents the physical build and testing process.

#### `others/images/`
Images of the PCB, CAD model, soldering process, enclosure, and final assembled device.
This folder contains PCB images, CAD images, soldering images, the printed box, and the final assembled device.

#### `others/simulation/`
Simulation-related image evidence.


## Notes
- The repository currently uses a mixed hardware/software structure, so the source tree is divided by platform.
- Folder names with spaces have been preserved exactly as they appear in the repository.
