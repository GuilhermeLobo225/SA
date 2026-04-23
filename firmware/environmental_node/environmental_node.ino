/*
 * Sala de Estudo Inteligente — Nó Ambiental
 * ESP32 DevKit V1
 *
 * Sensores: DHT11, MQ-135, LDR, KY-038, LED RGB
 * Leitura a cada 30 segundos, envio para Firebase Realtime Database.
 *
 * Bibliotecas necessárias (Arduino Library Manager):
 *   - DHT sensor library (by Adafruit)
 *   - Adafruit Unified Sensor
 *   - Firebase ESP Client (by mobizt)
 *
 * Board: ESP32 Dev Module
 */

#include <WiFi.h>
#include <Firebase_ESP_Client.h>
#include "addons/TokenHelper.h"
#include "DHT.h"
#include "time.h"

// ======================== CONFIGURAÇÃO ========================
// Wi-Fi
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// Firebase
#define API_KEY       "YOUR_FIREBASE_API_KEY"
#define DATABASE_URL  "https://YOUR_PROJECT.firebaseio.com"
#define USER_EMAIL    "esp32env@smartroom.local"
#define USER_PASSWORD "YOUR_SERVICE_PASSWORD"

// Sala
#define ROOM_ID       "sala_b1_piso2"

// Intervalo de leitura (ms)
#define READ_INTERVAL 30000

// NTP
#define NTP_SERVER "pool.ntp.org"
#define GMT_OFFSET 0
#define DST_OFFSET 3600

// ======================== PINOS (ATUALIZADO PARA ESP32-S3) ========================
// DHT11 (Pino digital seguro)
#define DHT_PIN   4
#define DHT_TYPE  DHT11

// MQ-135 (Precisa de pino analógico ADC)
#define MQ135_PIN 5 // ADC1_CH4

// Módulo Fotodíodo
#define PHOTO_A_PIN  6  // Saída analógica (ADC1_CH5) para medir a intensidade exata
#define PHOTO_D_PIN  7  // Saída digital (opcional) ligada ao potenciómetro do módulo

// KY-038 (Sensor de som - se ainda fores usar)
#define KY038_A_PIN  8  // Saída analógica (ADC1_CH7)
#define KY038_D_PIN  9  // Saída digital

// LED RGB (Pinos PWM seguros)
#define LED_R_PIN 15
#define LED_G_PIN 16
#define LED_B_PIN 17

// PWM channels para LED (A configuração mantém-se)
#define PWM_FREQ  5000
#define PWM_RES   8
#define CH_R 0
#define CH_G 1
#define CH_B 2

// ======================== LIMIARES ========================
// Temperatura confortável (ASHRAE 55)
#define TEMP_MIN  20.0
#define TEMP_MAX  26.0

// Humidade confortável
#define HUM_MIN   30.0
#define HUM_MAX   70.0

// MQ-135 (valor analógico — calibrar empiricamente)
#define AIR_GOOD      200
#define AIR_MODERATE   400
#define AIR_BAD       600

// LDR (valor analógico — calibrar empiricamente)
#define LIGHT_LOW     500
#define LIGHT_OK      1500

// KY-038 (valor analógico — calibrar empiricamente)
#define NOISE_LOW     200
#define NOISE_MODERATE 500
#define NOISE_HIGH    800

// ======================== VARIÁVEIS GLOBAIS ========================
DHT dht(DHT_PIN, DHT_TYPE);

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig fbConfig;

unsigned long lastRead = 0;
bool firebaseReady = false;

// ======================== SETUP ========================
void setup() {
  Serial.begin(115200);
  Serial.println("\n[SmartRoom] Nó Ambiental — Arranque");

  // Inicializar sensores
  dht.begin();
  pinMode(KY038_D_PIN, INPUT);

  // Inicializar LED RGB
  ledcSetup(CH_R, PWM_FREQ, PWM_RES);
  ledcSetup(CH_G, PWM_FREQ, PWM_RES);
  ledcSetup(CH_B, PWM_FREQ, PWM_RES);
  ledcAttachPin(LED_R_PIN, CH_R);
  ledcAttachPin(LED_G_PIN, CH_G);
  ledcAttachPin(LED_B_PIN, CH_B);
  setLED(0, 0, 255); // Azul = arranque

  // Wi-Fi
  connectWiFi();

  // NTP
  configTime(GMT_OFFSET, DST_OFFSET, NTP_SERVER);
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) delay(500);
  Serial.println("[NTP] Relógio sincronizado.");

  // Firebase
  fbConfig.api_key = API_KEY;
  fbConfig.database_url = DATABASE_URL;
  auth.user.email = USER_EMAIL;
  auth.user.password = USER_PASSWORD;
  fbConfig.token_status_callback = tokenStatusCallback;

  Firebase.begin(&fbConfig, &auth);
  Firebase.reconnectWiFi(true);

  Serial.print("[Firebase] A autenticar");
  while (!Firebase.ready()) {
    Serial.print(".");
    delay(300);
  }
  Serial.println("\n[Firebase] Pronto.");
  firebaseReady = true;

  setLED(0, 255, 0); // Verde = pronto
  delay(1000);
}

// ======================== LOOP ========================
void loop() {
  if (!firebaseReady) return;

  unsigned long now = millis();
  if (now - lastRead >= READ_INTERVAL) {
    lastRead = now;
    readAndSend();
  }

  delay(100);
}

// ======================== FUNÇÕES ========================

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[WiFi] A ligar");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[WiFi] Falha. A reiniciar...");
    ESP.restart();
  }
  Serial.printf("\n[WiFi] Ligado. IP: %s\n", WiFi.localIP().toString().c_str());
}

void setLED(uint8_t r, uint8_t g, uint8_t b) {
  ledcWrite(CH_R, r);
  ledcWrite(CH_G, g);
  ledcWrite(CH_B, b);
}

String getTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return "unknown";
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &timeinfo);
  return String(buf);
}

// Classificação qualitativa do conforto
String classifyComfort(float temp, float hum, int air, int light, int noise) {
  int score = 0; // 0 = bom, incrementa com problemas

  if (temp < TEMP_MIN || temp > TEMP_MAX) score += 2;
  if (hum < HUM_MIN || hum > HUM_MAX) score += 1;
  if (air > AIR_BAD) score += 2;
  else if (air > AIR_MODERATE) score += 1;
  if (light < LIGHT_LOW) score += 1;
  if (noise > NOISE_HIGH) score += 2;
  else if (noise > NOISE_MODERATE) score += 1;

  if (score <= 1) return "bom";
  if (score <= 3) return "moderado";
  return "mau";
}

void updateLEDFromComfort(String comfort) {
  if (comfort == "bom") {
    setLED(0, 255, 0);       // Verde
  } else if (comfort == "moderado") {
    setLED(255, 180, 0);     // Amarelo/laranja
  } else {
    setLED(255, 0, 0);       // Vermelho
  }
}

String classifyAirQuality(int value) {
  if (value < AIR_GOOD) return "bom";
  if (value < AIR_MODERATE) return "aceitavel";
  if (value < AIR_BAD) return "necessita_ventilacao";
  return "mau";
}

String classifyNoise(int value) {
  if (value < NOISE_LOW) return "baixo";
  if (value < NOISE_MODERATE) return "moderado";
  return "elevado";
}

String classifyLight(int value) {
  if (value < LIGHT_LOW) return "insuficiente";
  if (value < LIGHT_OK) return "adequado";
  return "bom";
}

void readAndSend() {
  // Ler sensores
  float temperature = dht.readTemperature();
  float humidity    = dht.readHumidity();
  int   airQuality  = analogRead(MQ135_PIN);
  int   light       = analogRead(LDR_PIN);
  int   noise       = analogRead(KY038_A_PIN);
  int   noiseDigital = digitalRead(KY038_D_PIN);

  // Validar DHT11
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("[DHT11] Erro de leitura.");
    temperature = -1;
    humidity = -1;
  }

  // Classificações
  String airClass   = classifyAirQuality(airQuality);
  String noiseClass = classifyNoise(noise);
  String lightClass = classifyLight(light);
  String comfort    = classifyComfort(temperature, humidity, airQuality, light, noise);
  String timestamp  = getTimestamp();

  // Atualizar LED
  updateLEDFromComfort(comfort);

  // Log serial
  Serial.println("─────────────────────────────");
  Serial.printf("[%s] Leitura dos sensores:\n", timestamp.c_str());
  Serial.printf("  Temperatura:  %.1f °C\n", temperature);
  Serial.printf("  Humidade:     %.1f %%\n", humidity);
  Serial.printf("  Qualidade ar: %d (%s)\n", airQuality, airClass.c_str());
  Serial.printf("  Luz:          %d (%s)\n", light, lightClass.c_str());
  Serial.printf("  Ruído:        %d (%s) [D: %d]\n", noise, noiseClass.c_str(), noiseDigital);
  Serial.printf("  Conforto:     %s\n", comfort.c_str());

  // Enviar para Firebase
  String basePath = String("rooms/") + ROOM_ID + "/environment";

  FirebaseJson json;
  json.set("timestamp", timestamp);
  json.set("temperature", temperature);
  json.set("humidity", humidity);
  json.set("air_quality_raw", airQuality);
  json.set("air_quality", airClass);
  json.set("light_raw", light);
  json.set("light", lightClass);
  json.set("noise_raw", noise);
  json.set("noise", noiseClass);
  json.set("noise_digital", noiseDigital);
  json.set("comfort", comfort);

  // Atualizar dados atuais
  if (Firebase.RTDB.setJSON(&fbdo, (basePath + "/current").c_str(), &json)) {
    Serial.println("[Firebase] Dados atuais enviados.");
  } else {
    Serial.printf("[Firebase] Erro: %s\n", fbdo.errorReason().c_str());
  }

  // Guardar no histórico (push)
  String histPath = basePath + "/history";
  if (Firebase.RTDB.pushJSON(&fbdo, histPath.c_str(), &json)) {
    Serial.println("[Firebase] Histórico registado.");
  } else {
    Serial.printf("[Firebase] Erro histórico: %s\n", fbdo.errorReason().c_str());
  }
}
