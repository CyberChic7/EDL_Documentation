# ESP32 — Wireless Bridge

## Platform

**Board:** ESP32 Dev Module (ESP32-WROOM or compatible)  
**IDE:** Arduino IDE with ESP32 board support  
**Role:** Wireless UART-to-UDP bridge between the STM32 and the laptop

---

## Role in the System

The ESP32 has a single, focused responsibility: receive the binary data stream from the
STM32 Black Pill over UART and rebroadcast it as UDP packets over Wi-Fi to the laptop.

It performs no signal processing or data transformation — the 36-byte packets are
validated for the correct header and forwarded unchanged.

```
STM32 Black Pill
      │
      │ UART (57600 baud, TX→GPIO16, RX→GPIO17)
      ▼
   ESP32
      │
      │ UDP broadcast (port 12345) over Wi-Fi
      ▼
   Laptop (Python receiver + web server)
```

---

## Hardware Connections

### UART — STM32 Black Pill

| Signal | ESP32 Pin | STM32 Pin |
|--------|-----------|-----------|
| RX     | GPIO 16 (Serial2 RX) | PA9 (Serial1 TX) |
| TX     | GPIO 17 (Serial2 TX) | PA10 (Serial1 RX) |
| GND    | GND       | GND       |

> Note: Cross-connect TX→RX and RX→TX between the two boards. Ensure both boards
> share a common GND.

---

## Design Decisions

### STA Mode (Station Mode) instead of AP Mode

The ESP32 operates as a **Wi-Fi client (STA)**, joining an existing network rather than
creating its own hotspot. This was a deliberate design choice:

The laptop runs a Python web server alongside the UDP receiver. If the laptop were to
connect to the ESP32's own hotspot (AP mode), it would lose access to the internet and
to the local network, which the web server depends on. By having both the ESP32 and the
laptop join a **common existing Wi-Fi network** (e.g. a mobile hotspot), both devices
remain on the same subnet and can communicate via UDP while the laptop retains full
network access.

### UDP Broadcast

The ESP32 derives the broadcast address dynamically from its own IP address by setting
the last octet to 255 (e.g. `192.168.x.255`). This means the laptop's Python receiver
does not need to know the ESP32's IP — it simply listens on port 12345 on the same
network and receives all broadcast packets automatically.

### Packet Validation

Before forwarding, the ESP32 checks that the first two bytes of every received packet
match the expected header `0x0A 0xFA`. If the header does not match, the packet is
dropped and the UART buffer is flushed to re-align to the next valid packet boundary.
This prevents corrupted or mis-framed packets from reaching the laptop.

---

## Configuration

Before flashing, open the `.ino` file and fill in your network credentials:

```cpp
const char* ssid     = "";   // ← SSID of the shared Wi-Fi network
const char* password = "";   // ← Password of the shared Wi-Fi network
```

Both the ESP32 and the laptop must be connected to **the same network** for UDP
broadcast to work.

---

## Key Parameters

| Parameter | Value |
|-----------|-------|
| UART baud rate (from STM32) | 57600 |
| UART pins | RX = GPIO16, TX = GPIO17 |
| UDP port | 12345 |
| Packet size | 36 bytes |
| Wi-Fi mode | STA (Station) |
| Connection timeout | 20 seconds |

---

## Serial Monitor Output

Connect via USB and open the serial monitor at **115200 baud** to observe connection
status and packet activity:

```
=== ESP32 Starting in STA Mode ===
Connecting to WiFi: <your_ssid>
....
✅ Connected!
IP Address: 192.168.x.xx
Gateway: 192.168.x.1
--- Wireless Bridge Active (STA Mode) ---
UDP Packet Broadcast Sent!
UDP Packet Broadcast Sent!
...
```

If you see `❌ Failed to connect to WiFi!`, double-check the SSID and password in the
code and reflash.
