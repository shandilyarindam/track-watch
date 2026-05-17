// Track-Watch Fog Node — ESP32-S3 N16R8
// Dual-core: Core 0 receives ESP-NOW, Core 1 processes + HTTP POST to FastAPI

#include <esp_now.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "secrets.h"

char TELEMETRY_ENDPOINT[128];
void constructEndpoint() {
  sprintf(TELEMETRY_ENDPOINT, "http://%s:%d/api/telemetry", SERVER_IP, SERVER_PORT);
}

// Must match sensor node struct exactly — byte alignment matters across chips
#pragma pack(push, 1)
typedef struct {
  uint32_t counter;
  float    distance;
  int32_t  flexRaw;
  float    temp;
  int32_t  motion;
} SensorData;
#pragma pack(pop)

typedef struct {
  uint32_t counter;
  float    distance_cm;
  float    flex_normalized;   // 0.0 (flat) to 100.0 (fully bent)
  float    temp_c;
  bool     anomaly_detected;
} CleanedData;

QueueHandle_t sensorQueue;
TaskHandle_t  processingTaskHandle;

void connectToWiFi() {
  Serial.println();
  Serial.print("[WiFi] Connecting to ");
  Serial.println(WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    attempts++;
    if (attempts % 20 == 0) {
      Serial.println("\n[WiFi] Still connecting...");
    }
    // ESP32 WiFi stack can wedge after ~30s of failed associations
    if (attempts >= 60) {
      Serial.println("\n[WiFi] Timeout -- restarting WiFi stack");
      WiFi.disconnect(true);
      delay(1000);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      attempts = 0;
    }
  }

  Serial.println();
  Serial.print("[WiFi] Connected. IP: ");
  Serial.print(WiFi.localIP());
  Serial.print("  RSSI: ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
}

// Core 0 ISR — non-blocking, drops on queue-full
void onDataRecv(const uint8_t *mac_addr, const uint8_t *data, int len) {
  SensorData rawPacket;
  memcpy(&rawPacket, data, sizeof(rawPacket));

  if (xQueueSend(sensorQueue, &rawPacket, 0) != pdTRUE) {
    Serial.println("[Core 0] Queue full, dropping packet");
  }
}

// Core 1 task — blocking queue read, threshold eval, HTTP POST on anomaly
void processDataTask(void *pvParameters) {
  SensorData  rawData;
  CleanedData cleanData;

  Serial.print("[Core 1] Worker started on core ");
  Serial.println(xPortGetCoreID());

  for (;;) {
    if (xQueueReceive(sensorQueue, &rawData, portMAX_DELAY) == pdTRUE) {

      // Temperature: clamp wild ADC spikes to baseline
      if (rawData.temp > 85.0f || rawData.temp < 0.0f) {
        cleanData.temp_c = 25.0f;
      } else {
        cleanData.temp_c = rawData.temp;
      }

      // Flex: normalize raw ADC to 0-100% deflection index
      // Baseline calibrated on the specific sensor unit used in dev
      float baseFlat = 330.0f;
      float maxBent  = 150.0f;
      float score = ((baseFlat - (float)rawData.flexRaw) / (baseFlat - maxBent)) * 100.0f;
      cleanData.flex_normalized = constrain(score, 0.0f, 100.0f);

      cleanData.distance_cm = rawData.distance;

      bool isAnomaly = false;
      if (cleanData.flex_normalized > 40.0f) isAnomaly = true;
      if (cleanData.temp_c > 60.0f) isAnomaly = true;
      if (rawData.motion == 1 && cleanData.distance_cm < 100.0f && cleanData.distance_cm > 0)
        isAnomaly = true;

      cleanData.anomaly_detected = isAnomaly;
      cleanData.counter = rawData.counter;

      const char* statusLabel;
      if (cleanData.anomaly_detected) {
        int triggerCount = 0;
        if (cleanData.flex_normalized > 40.0f)  triggerCount++;
        if (cleanData.temp_c > 60.0f)           triggerCount++;
        if (rawData.motion == 1 && cleanData.distance_cm < 100.0f && cleanData.distance_cm > 0)
          triggerCount++;
        statusLabel = (triggerCount >= 2) ? "CRITICAL" : "CAUTION";
      } else {
        statusLabel = "NOMINAL";
      }

      Serial.print("[Core 1] #");
      Serial.print(cleanData.counter);
      Serial.print(" | Temp:");
      Serial.print(cleanData.temp_c, 1);
      Serial.print("C | Defl:");
      Serial.print(cleanData.flex_normalized, 1);
      Serial.print("% | Dist:");
      Serial.print(cleanData.distance_cm, 1);
      Serial.print("cm | ");
      Serial.println(statusLabel);

      if (cleanData.anomaly_detected) {
        Serial.println("[Core 1] ANOMALY -> cloud uplink");

        if (WiFi.status() != WL_CONNECTED) {
          Serial.println("[Core 1] WiFi down, reconnecting");
          connectToWiFi();
        }

        if (WiFi.status() == WL_CONNECTED) {
          HTTPClient http;
          http.begin(TELEMETRY_ENDPOINT);
          http.addHeader("Content-Type", "application/json");
          http.setTimeout(10000);

          // String concat instead of ArduinoJson — fixed 6-field flat payload
          String jsonPayload = "{";
          jsonPayload += "\"packet_id\":" + String(cleanData.counter) + ",";
          jsonPayload += "\"track_section\":\"KM-42-DELHI\",";
          jsonPayload += "\"temperature_c\":" + String(cleanData.temp_c, 2) + ",";
          jsonPayload += "\"deflection_pct\":" + String(cleanData.flex_normalized, 2) + ",";
          jsonPayload += "\"distance_cm\":" + String(cleanData.distance_cm, 2) + ",";
          jsonPayload += "\"status\":\"" + String(statusLabel) + "\"";
          jsonPayload += "}";

          Serial.print("[Core 1] POST -> ");
          Serial.println(TELEMETRY_ENDPOINT);

          int httpResponseCode = http.POST(jsonPayload);

          if (httpResponseCode > 0) {
            Serial.print("[Core 1] HTTP ");
            Serial.println(httpResponseCode);
            if (httpResponseCode == 201) {
              Serial.print("[Core 1] Accepted: ");
              Serial.println(http.getString());
            }
          } else {
            Serial.print("[Core 1] POST failed: ");
            Serial.println(http.errorToString(httpResponseCode));
          }

          http.end();
        } else {
          Serial.println("[Core 1] WiFi unavailable, alert not uploaded");
        }
      } else {
        Serial.println("[Core 1] NOMINAL, no uplink");
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\nTrack-Watch Fog Node");
  Serial.println("ESP32-S3 N16R8 | Dual-Core FreeRTOS\n");

  sensorQueue = xQueueCreate(10, sizeof(SensorData));
  if (sensorQueue == NULL) {
    Serial.println("FATAL: Queue creation failed");
    return;
  }

  // 16KB stack — HTTP client + String ops need headroom
  xTaskCreatePinnedToCore(
    processDataTask,
    "DataProcessor",
    16384,
    NULL,
    1,
    &processingTaskHandle,
    1
  );

  // AP+STA: ESP-NOW on SoftAP interface, WiFi STA for HTTP uplink
  WiFi.mode(WIFI_AP_STA);
  connectToWiFi();
  constructEndpoint();

  if (esp_now_init() != ESP_OK) {
    Serial.println("FATAL: ESP-NOW init failed");
    return;
  }

  esp_now_register_recv_cb(onDataRecv);

  Serial.print("ESP-NOW ready on core ");
  Serial.println(xPortGetCoreID());
  Serial.print("Uplink: ");
  Serial.println(TELEMETRY_ENDPOINT);
  Serial.println("Waiting for sensor packets...\n");
}

void loop() {
  // Core 0 loop unused — all work in ISR callback and Core 1 FreeRTOS task
  vTaskDelete(NULL);
}