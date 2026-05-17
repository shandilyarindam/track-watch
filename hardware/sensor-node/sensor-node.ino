// Track-Watch Sensor Node — ESP32-S3
// Samples LM35 + flex + HC-SR04 + PIR, transmits via ESP-NOW to fog gateway

#include <esp_now.h>
#include <esp_wifi.h>
#include <WiFi.h>

#define TRIG_PIN    5
#define ECHO_PIN   18
#define FLEX_PIN   34
#define LM35_PIN   36
#define PIR_PIN    19
#define LED_PIN     2

const unsigned long READ_INTERVAL    = 1000;
const unsigned long BLINK_INTERVAL   = 300;
const float TEMP_OFFSET          = 25.0f;
const int   FLEX_THRESHOLD       = 2200;
const float DISTANCE_THRESHOLD   = 20.0f;
const float TEMP_ALERT_THRESHOLD = 58.0f;

uint8_t fogNodeMAC[] = {0xAC, 0xA7, 0x04, 0x15, 0x04, 0xAC};

// Must match fog node struct — pragma pack for cross-chip byte alignment
#pragma pack(push, 1)
typedef struct {
  uint32_t counter;
  float distance;
  int32_t flexRaw;
  float temp;
  int32_t motion;
} SensorData;
#pragma pack(pop)

SensorData sensorData;

unsigned long counter = 0;
unsigned long lastReading = 0;
unsigned long lastBlink   = 0;
bool ledState = false;

void onDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
}

void setup() {
  Serial.begin(115200);
  delay(250);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(PIR_PIN,  INPUT);
  pinMode(LED_PIN,  OUTPUT);
  digitalWrite(LED_PIN, LOW);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(11, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }
  esp_now_register_send_cb(onDataSent);

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, fogNodeMAC, 6);
  peerInfo.channel = 0;
  peerInfo.encrypt = false;
  esp_now_add_peer(&peerInfo);

  Serial.println("timestamp,distance_cm,flex_raw,temp_C,motion");
}

void loop() {
  unsigned long now = millis();

  if (now - lastReading >= READ_INTERVAL) {
    lastReading = now;
    counter++;

    digitalWrite(TRIG_PIN, LOW); delayMicroseconds(4);
    digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    long duration = pulseIn(ECHO_PIN, HIGH, 35000UL);
    float distance = (duration == 0) ? -1.0f : duration * 0.034 / 2.0;

    int flexRaw = analogRead(FLEX_PIN);

    int adc = analogRead(LM35_PIN);
    float voltage = adc * (3.3f / 4095.0f);
    float temp = (voltage * 100.0f) + TEMP_OFFSET;

    int motion = digitalRead(PIR_PIN);

    sensorData.counter  = counter;
    sensorData.distance = distance;
    sensorData.flexRaw  = flexRaw;
    sensorData.temp     = temp;
    sensorData.motion   = motion;
    esp_now_send(fogNodeMAC, (uint8_t *)&sensorData, sizeof(sensorData));

    Serial.print(counter);           Serial.print(",");
    Serial.print(distance, 1);       Serial.print(",");
    Serial.print(flexRaw);           Serial.print(",");
    Serial.print(temp, 1);           Serial.print(",");
    Serial.println(motion);
  }

  // Blink LED on threshold breach for visual field indication
  digitalWrite(TRIG_PIN, LOW); delayMicroseconds(4);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long dur = pulseIn(ECHO_PIN, HIGH, 30000UL);
  float dist = (dur == 0) ? -1.0f : dur * 0.034 / 2.0;

  int adc_fast = analogRead(LM35_PIN);
  float temp_fast = (adc_fast * 3.3f / 4095.0f * 100.0f) + TEMP_OFFSET;

  bool shouldBlink = false;
  if (dist > 3.0f && dist < DISTANCE_THRESHOLD) shouldBlink = true;
  if (temp_fast > TEMP_ALERT_THRESHOLD) shouldBlink = true;

  if (shouldBlink) {
    if (now - lastBlink >= BLINK_INTERVAL) {
      lastBlink = now;
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState);
    }
  } else {
    digitalWrite(LED_PIN, LOW);
    ledState = false;
  }
}