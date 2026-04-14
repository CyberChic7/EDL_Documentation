#include <WiFi.h>
#include <WiFiUdp.h>

const char* ssid = "";      // ← Add SSID of the wifi network you want to join
const char* password = ""; // ← Add password of the wifi network you want to join

const uint16_t udpPort = 12345;

WiFiUDP udp;
uint8_t buffer[36];

void setup() {
  Serial.begin(115200);
  Serial2.begin(57600, SERIAL_8N1, 16, 17);   // UART from STM32

  Serial.println("\n=== ESP32 Starting in STA Mode ===");

  WiFi.mode(WIFI_STA);           // Station mode (client)
  WiFi.begin(ssid, password);

  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);

  int timeout = 0;
  while (WiFi.status() != WL_CONNECTED && timeout < 40) {   // 20 seconds timeout
    delay(500);
    Serial.print(".");
    timeout++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ Connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.print("Gateway: ");
    Serial.println(WiFi.gatewayIP());
    Serial.println("--- Wireless Bridge Active (STA Mode) ---");
  } else {
    Serial.println("\n❌ Failed to connect to WiFi!");
    Serial.println("Check SSID and password.");
  }

  udp.begin(udpPort);   // Not strictly needed for sending, but good practice
}

void loop() {
  // Read from STM32 UART
  if (Serial2.available() >= 36) {
    Serial2.readBytes(buffer, 36);

    if (buffer[0] == 0x0A && buffer[1] == 0xFA) {
      // Send UDP packet to broadcast address of current network
      IPAddress broadcastIP = WiFi.localIP();
      broadcastIP[3] = 255;                    // e.g., 192.168.x.255

      udp.beginPacket(broadcastIP, udpPort);
      udp.write(buffer, 36);
      udp.endPacket();

      Serial.println("UDP Packet Broadcast Sent!");
    } else {
      Serial.println("Misaligned packet dropped.");
      while (Serial2.available()) Serial2.read();  // flush
    }
  }

  delay(1);   // Small delay to avoid watchdog issues
}
