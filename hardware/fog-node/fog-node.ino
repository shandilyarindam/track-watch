/*
 * ═══════════════════════════════════════════════════════════════════════════
 *  Track-Watch — ESP32-S3 Fog Node Firmware (Cloud Uplink Edition)
 * ═══════════════════════════════════════════════════════════════════════════
 *
 *  Hardware : ESP32-S3 N16R8
 *  Role     : Dual-core fog compute node with WiFi cloud uplink
 *
 *  Core 0   : ESP-NOW receiver callback → pushes raw sensor packets into
 *             a FreeRTOS queue. Never blocks; drops packets on queue-full.
 *
 *  Core 1   : processDataTask — pops from queue, runs data cleaning &
 *             calibration, evaluates edge thresholds, and on anomaly
 *             detection, POSTs telemetry JSON to the FastAPI backend
 *             via HTTP over the local WiFi network.
 *
 *  Network  : WiFi AP+STA mode (WIFI_AP_STA) enables concurrent
 *             ESP-NOW peer reception AND WiFi Station uplink.
 *
 *  Backend  : FastAPI @ http://192.168.1.40:8000/api/telemetry
 *             Expects JSON body matching TelemetryPayload Pydantic schema.
 *
 *  Board    : Arduino ESP32 → ESP32S3 Dev Module
 * ═══════════════════════════════════════════════════════════════════════════
 */

#include <esp_now.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "secrets.h"

// ─────────────────────────────────────────────────────────────────────────
// Network Configuration
// ─────────────────────────────────────────────────────────────────────────
// Credentials are loaded from secrets.h (excluded from version control)

// Constructed endpoint URL
char TELEMETRY_ENDPOINT[128];
void constructEndpoint() {
  sprintf(TELEMETRY_ENDPOINT, "http://%s:%d/api/telemetry", SERVER_IP, SERVER_PORT);
}

// ─────────────────────────────────────────────────────────────────────────
// Packed data structure matching the sensor node exactly
// ─────────────────────────────────────────────────────────────────────────
#pragma pack(push, 1)
typedef struct {
  uint32_t counter;
  float    distance;
  int32_t  flexRaw;
  float    temp;
  int32_t  motion;
} SensorData;
#pragma pack(pop)

// Structure for the cleaned and scaled data
typedef struct {
  uint32_t counter;
  float    distance_cm;
  float    flex_normalized;   // 0.0 (flat) to 100.0 (fully bent)
  float    temp_c;
  bool     anomaly_detected;
} CleanedData;

// ─────────────────────────────────────────────────────────────────────────
// FreeRTOS Handles
// ─────────────────────────────────────────────────────────────────────────
QueueHandle_t sensorQueue;
TaskHandle_t  processingTaskHandle;

// ─────────────────────────────────────────────────────────────────────────
// WiFi Connection Helper — blocking, retries until link is established
// ─────────────────────────────────────────────────────────────────────────
void connectToWiFi() {
  Serial.println();
  Serial.println("───────────────────────────────────────────");
  Serial.print("[WiFi] Connecting to SSID: ");
  Serial.println(WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASS);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    attempts++;
    if (attempts % 20 == 0) {
      Serial.println();
      Serial.println("[WiFi] Still connecting...");
    }
    // Hard-reset WiFi stack after 60 failed attempts (~30s)
    if (attempts >= 60) {
      Serial.println("\n[WiFi] Connection timeout — restarting WiFi stack...");
      WiFi.disconnect(true);
      delay(1000);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      attempts = 0;
    }
  }

  Serial.println();
  Serial.println("[WiFi] ✓ Connected!");
  Serial.print("[WiFi] IP Address : ");
  Serial.println(WiFi.localIP());
  Serial.print("[WiFi] RSSI       : ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
  Serial.print("[WiFi] Channel    : ");
  Serial.println(WiFi.channel());
  Serial.println("───────────────────────────────────────────");
}

// ─────────────────────────────────────────────────────────────────────────
// Core 0 — ESP-NOW Receiver Callback
// ─────────────────────────────────────────────────────────────────────────
void onDataRecv(const uint8_t *mac_addr, const uint8_t *data, int len) {
  SensorData rawPacket;
  memcpy(&rawPacket, data, sizeof(rawPacket));

  // Push raw data into the queue. Non-blocking (0 ticks wait time)
  // to ensure Core 0 never bottlenecks wireless reception.
  if (xQueueSend(sensorQueue, &rawPacket, 0) != pdTRUE) {
    Serial.println("[Core 0] Warning: Sensor Queue Full! Dropping packet.");
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Core 1 — Processing + Cloud Uplink Task
// ─────────────────────────────────────────────────────────────────────────
void processDataTask(void *pvParameters) {
  SensorData  rawData;
  CleanedData cleanData;

  Serial.print("[Core 1] Worker task started on core: ");
  Serial.println(xPortGetCoreID());

  for (;;) {
    // Block indefinitely (portMAX_DELAY) until a packet is pushed to the queue
    if (xQueueReceive(sensorQueue, &rawData, portMAX_DELAY) == pdTRUE) {

      // ── DATA CLEANING & SCALING LOGIC ──────────────────────────────

      // 1. Clean Temperature: Sanity checks for ambient rail values in India (10°C to 75°C)
      // If a wild analog noise spike occurs, clamp it or flag it.
      if (rawData.temp > 85.0f || rawData.temp < 0.0f) {
        cleanData.temp_c = 25.0f; // Default baseline fallback or rolling average placeholder
      } else {
        cleanData.temp_c = rawData.temp;
      }

      // 2. Scale Flex Sensor: Convert raw values to normalized deflection index (0.0 to 100.0)
      // Assuming a raw baseline of ~330 flat, and decreasing values under tension:
      float baseFlat = 330.0f;
      float maxBent  = 150.0f;
      float score = ((baseFlat - (float)rawData.flexRaw) / (baseFlat - maxBent)) * 100.0f;
      cleanData.flex_normalized = constrain(score, 0.0f, 100.0f);

      // 3. Clean Ultrasonic Distance
      cleanData.distance_cm = rawData.distance;

      // 4. Edge Anomaly / Decision Logic
      // (This is exactly where your trained ML model will evaluate features!)
      bool isAnomaly = false;
      if (cleanData.flex_normalized > 40.0f) isAnomaly = true;                                     // High rail bending structure risk
      if (cleanData.temp_c > 60.0f) isAnomaly = true;                                              // Buckling threat threshold
      if (rawData.motion == 1 && cleanData.distance_cm < 100.0f && cleanData.distance_cm > 0)
        isAnomaly = true;                                                                            // Object on track

      cleanData.anomaly_detected = isAnomaly;
      cleanData.counter = rawData.counter;

      // ── DETERMINE STATUS STRING ────────────────────────────────────
      const char* statusLabel;
      if (cleanData.anomaly_detected) {
        // Classify severity: CRITICAL if multiple triggers, CAUTION otherwise
        int triggerCount = 0;
        if (cleanData.flex_normalized > 40.0f)  triggerCount++;
        if (cleanData.temp_c > 60.0f)           triggerCount++;
        if (rawData.motion == 1 && cleanData.distance_cm < 100.0f && cleanData.distance_cm > 0)
          triggerCount++;

        statusLabel = (triggerCount >= 2) ? "CRITICAL" : "CAUTION";
      } else {
        statusLabel = "NOMINAL";
      }

      // ── LOG CLEANED RESULTS ────────────────────────────────────────
      Serial.println("───────────────────────────────────────────");
      Serial.print("[Core 1] Packet #");
      Serial.print(cleanData.counter);
      Serial.print("  |  Temp: ");
      Serial.print(cleanData.temp_c, 1);
      Serial.print(" C  |  Deflection: ");
      Serial.print(cleanData.flex_normalized, 1);
      Serial.print("%  |  Dist: ");
      Serial.print(cleanData.distance_cm, 1);
      Serial.print(" cm  |  Status: ");
      Serial.println(statusLabel);

      // ── CLOUD UPLINK (only on anomaly) ─────────────────────────────
      // Fire HTTP POST to FastAPI backend when anomaly is detected
      if (cleanData.anomaly_detected) {
        Serial.println("[Core 1] ANOMALY DETECTED → Initiating cloud uplink...");

        // Check WiFi connectivity before attempting POST
        if (WiFi.status() != WL_CONNECTED) {
          Serial.println("[Core 1] WiFi disconnected — attempting reconnect...");
          connectToWiFi();
        }

        if (WiFi.status() == WL_CONNECTED) {
          HTTPClient http;
          http.begin(TELEMETRY_ENDPOINT);
          http.addHeader("Content-Type", "application/json");
          http.setTimeout(10000); // 10 second timeout

          // ── Construct JSON payload matching Pydantic TelemetryPayload schema ──
          //
          //   {
          //     "packet_id":      <uint32_t counter>,
          //     "track_section":  "KM-42-DELHI",
          //     "temperature_c":  <float>,
          //     "deflection_pct": <float>,
          //     "distance_cm":    <float>,
          //     "status":         "CAUTION" | "CRITICAL"
          //   }
          //
          // Using String concatenation for clarity on embedded targets.
          // ArduinoJson is overkill for a fixed 6-field flat payload.

          String jsonPayload = "{";
          jsonPayload += "\"packet_id\":" + String(cleanData.counter) + ",";
          jsonPayload += "\"track_section\":\"KM-42-DELHI\",";
          jsonPayload += "\"temperature_c\":" + String(cleanData.temp_c, 2) + ",";
          jsonPayload += "\"deflection_pct\":" + String(cleanData.flex_normalized, 2) + ",";
          jsonPayload += "\"distance_cm\":" + String(cleanData.distance_cm, 2) + ",";
          jsonPayload += "\"status\":\"" + String(statusLabel) + "\"";
          jsonPayload += "}";

          Serial.print("[Core 1] POST → ");
          Serial.println(TELEMETRY_ENDPOINT);
          Serial.print("[Core 1] Payload: ");
          Serial.println(jsonPayload);

          int httpResponseCode = http.POST(jsonPayload);

          if (httpResponseCode > 0) {
            Serial.print("[Core 1] Server Response: HTTP ");
            Serial.println(httpResponseCode);
            if (httpResponseCode == 201) {
              String responseBody = http.getString();
              Serial.print("[Core 1] ✓ Telemetry accepted: ");
              Serial.println(responseBody);
            } else {
              Serial.print("[Core 1] ⚠ Unexpected status: ");
              Serial.println(http.getString());
            }
          } else {
            Serial.print("[Core 1] ✕ HTTP POST failed, error: ");
            Serial.println(http.errorToString(httpResponseCode));
          }

          http.end();
        } else {
          Serial.println("[Core 1] ✕ WiFi unavailable — alert NOT uploaded.");
        }
      } else {
        Serial.println("[Core 1] Status NOMINAL — no uplink required.");
      }
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Setup — runs on Core 0
// ─────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("═══════════════════════════════════════════════════");
  Serial.println("  Track-Watch Fog Node — Cloud Uplink Edition");
  Serial.println("  Board: ESP32-S3 N16R8  |  Dual-Core FreeRTOS");
  Serial.println("═══════════════════════════════════════════════════");

  // ── Create FreeRTOS Queue ──────────────────────────────────────────
  // Queue stores up to 10 raw sensor data structures as a buffer
  sensorQueue = xQueueCreate(10, sizeof(SensorData));
  if (sensorQueue == NULL) {
    Serial.println("[Setup] FATAL: Error creating FreeRTOS Queue!");
    return;
  }
  Serial.println("[Setup] FreeRTOS queue created (depth=10)");

  // ── Spawn Core 1 Processing Task ──────────────────────────────────
  // Stack increased to 16384 bytes to accommodate HTTP + String ops
  xTaskCreatePinnedToCore(
    processDataTask,
    "DataProcessor",
    16384,        // Stack: 16 KB (HTTP client needs headroom)
    NULL,
    1,            // Priority
    &processingTaskHandle,
    1             // Pinned to Core 1
  );
  Serial.println("[Setup] Core 1 task spawned: DataProcessor (16KB stack)");

  // ── WiFi: AP+STA Mode (concurrent ESP-NOW + WiFi Station) ─────────
  // WIFI_AP_STA allows the ESP-NOW protocol stack to operate on the
  // SoftAP interface while the STA interface connects to the router.
  WiFi.mode(WIFI_AP_STA);
  Serial.println("[Setup] WiFi mode set to AP+STA (ESP-NOW + Station)");

  // Connect to the local WiFi network for HTTP uplink
  connectToWiFi();

  // Construct the telemetry endpoint URL using server IP from secrets.h
  constructEndpoint();

  // ── Initialise ESP-NOW on the AP interface ────────────────────────
  if (esp_now_init() != ESP_OK) {
    Serial.println("[Setup] FATAL: Error initializing ESP-NOW!");
    return;
  }
  Serial.println("[Setup] ESP-NOW initialised successfully");

  // Register the receive callback (fires on Core 0 via WiFi task)
  esp_now_register_recv_cb(onDataRecv);

  Serial.println("───────────────────────────────────────────");
  Serial.print("[Setup] ESP-NOW Gateway ready on Core ");
  Serial.println(xPortGetCoreID());
  Serial.print("[Setup] Uplink target: ");
  Serial.println(TELEMETRY_ENDPOINT);
  Serial.println("[Setup] Waiting for sensor node packets...");
  Serial.println("═══════════════════════════════════════════════════");
}

// ─────────────────────────────────────────────────────────────────────────
// Loop — empty; FreeRTOS handles task scheduling autonomously
// ─────────────────────────────────────────────────────────────────────────
void loop() {
  // Core 0 loop is unused — all work is done in ISR callback (onDataRecv)
  // and the pinned FreeRTOS task on Core 1 (processDataTask).
  vTaskDelete(NULL);
}