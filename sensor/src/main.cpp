/*
 * Sala de Estudo Inteligente — Nó Ambiental (Sensor_NODE)
 * Placa: ESP32-S3 DevKitC-1
 *
 * Sensores:
 *   - DHT11                    (temperatura + humidade, 1-wire digital)
 *   - MQ-135                   (qualidade do ar, ADC analógico)
 *   - LM393 fotodíodo          (luz: saída digital com potenciómetro + saída analógica)
 *   - MSM261S4030H0            (microfone MEMS I2S de 24 bits — ruído)
 *   - LED RGB cátodo comum     (feedback visual de conforto)
 *
 * Envia leituras a cada READ_INTERVAL ms para Firebase Realtime Database:
 *   /rooms/<ROOM_ID>/environment/current
 *   /rooms/<ROOM_ID>/environment/history (push)
 *
 * Bibliotecas (lib_deps em platformio.ini):
 *   - mobizt/Firebase Arduino Client Library for ESP8266 and ESP32
 *   - adafruit/DHT sensor library
 *   - adafruit/Adafruit Unified Sensor
 */

#include <Arduino.h>
#include <WiFi.h>
#include <Firebase_ESP_Client.h>
#include "addons/TokenHelper.h"
#include "addons/RTDBHelper.h"
#include "DHT.h"
#include "driver/i2s.h"
#include "time.h"
#include <math.h>

// ======================== CONFIGURAÇÃO ========================
// Wi-Fi
#define WIFI_SSID      "luismpso"       
#define WIFI_PASSWORD  "Luis2002"

// Firebase
#define API_KEY       "AIzaSyDMz9JUWG8blDmMw7yqahRcDXvJ5o9uU2A"
#define DATABASE_URL  "https://sensor-node-da140-default-rtdb.europe-west1.firebasedatabase.app/"
// Conta de serviço criada no Firebase Authentication (Email/Password)
#define USER_EMAIL    "esp32env@smartroom.local"
#define USER_PASSWORD "admin123"

// Identificador da sala
#define ROOM_ID       "sala_b1_piso2"

// Intervalo de leitura (ms)
#define READ_INTERVAL          30000UL   // sensores ambientais
#define OCCUPANCY_POLL_INTERVAL 5000UL   // leitura do status de ocupação (LED)

// NTP
#define NTP_SERVER   "pool.ntp.org"
#define GMT_OFFSET   0
#define DST_OFFSET   3600

// ======================== PINOS (ESP32-S3) ========================
// DHT11 — digital seguro
#define DHT_PIN     4
#define DHT_TYPE    DHT11

// MQ-135 — ADC1_CH4
// ⚠️ AO do MQ-135 vai até 5 V; ligar SEMPRE através de divisor de tensão:
//    MQ-135 AO ── R1(10k) ──┬── GPIO 5
//                           R2(10k) ── GND
//   (V_GPIO = V_AO × 1/2 → 5 V máx no AO ≈ 2.5 V no GPIO; ADC máx ≈ 3102/4095)
//   Limiares de gás (AIR_*) calibrados empiricamente após observar o Serial Monitor.
#define MQ135_PIN   5

// LM393 fotodíodo (módulo de luz)
#define LIGHT_A_PIN 6   // saída analógica AO (ADC1_CH5)
#define LIGHT_D_PIN 7   // saída digital DO (limiar do potenciómetro)

// I2S MSM261S4030H0 (microfone MEMS)
#define I2S_MIC_BCK   14   // BCLK / SCK
#define I2S_MIC_WS    15   // LRCLK / WS
#define I2S_MIC_SD    13   // DOUT / SD
#define I2S_PORT      I2S_NUM_0
#define I2S_SAMPLE_RATE 16000
#define I2S_READ_SAMPLES 1024   // janela de amostras para cálculo de RMS

// LED RGB cátodo comum (PWM)
#define LED_R_PIN   16
#define LED_G_PIN   17
#define LED_B_PIN   18

// Canais PWM (LEDC)
#define PWM_FREQ    5000
#define PWM_RES     8
#define CH_R        0
#define CH_G        1
#define CH_B        2

// ======================== LIMIARES ========================
// Temperatura confortável (ASHRAE 55)
#define TEMP_MIN    20.0
#define TEMP_MAX    26.0

// Humidade relativa confortável
#define HUM_MIN     30.0
#define HUM_MAX     70.0

// MQ-135 (valor ADC bruto — calibrar empiricamente, 12-bit = 0..4095)
#define AIR_GOOD     800
#define AIR_MODERATE 1500
#define AIR_BAD      2500

// Luz (LM393 — quanto menor o valor analógico, mais luz; calibrar)
#define LIGHT_OK     2500   // acima disto = escuro
#define LIGHT_LOW    3500

// Ruído (RMS do I2S, valor estimado em dBFS — calibrar com sonómetro real)
#define NOISE_LOW       35.0
#define NOISE_MODERATE  55.0
#define NOISE_HIGH      70.0

// ======================== VARIÁVEIS GLOBAIS ========================
DHT dht(DHT_PIN, DHT_TYPE);

FirebaseData   fbdo;
FirebaseData   fbdoOccupancy;   // ligação dedicada à leitura de occupancy
FirebaseAuth   auth;
FirebaseConfig fbConfig;

unsigned long lastRead       = 0;
unsigned long lastOccupancy  = 0;
String        lastStatus     = "";
bool          firebaseReady = false;

// ======================== I2S MICROFONE ========================
void i2sMicInit() {
  i2s_config_t i2s_cfg = {
      .mode            = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate     = I2S_SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,        // MSM261 entrega 24 bits dentro de 32
      .channel_format  = I2S_CHANNEL_FMT_ONLY_LEFT,        // SEL=GND => canal esquerdo
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count   = 4,
      .dma_buf_len     = 1024,
      .use_apll        = false,
      .tx_desc_auto_clear = false,
      .fixed_mclk      = 0
  };

  i2s_pin_config_t pin_cfg = {
      .bck_io_num   = I2S_MIC_BCK,
      .ws_io_num    = I2S_MIC_WS,
      .data_out_num = I2S_PIN_NO_CHANGE,
      .data_in_num  = I2S_MIC_SD
  };

  i2s_driver_install(I2S_PORT, &i2s_cfg, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_cfg);
  i2s_zero_dma_buffer(I2S_PORT);
}

// Calcula nível de ruído (dBFS) a partir de uma janela I2S.
float readNoiseDBFS() {
  static int32_t samples[I2S_READ_SAMPLES];
  size_t bytesRead = 0;
  if (i2s_read(I2S_PORT, samples, sizeof(samples), &bytesRead, pdMS_TO_TICKS(200)) != ESP_OK) {
    return -120.0f;
  }
  int n = bytesRead / sizeof(int32_t);
  if (n <= 0) return -120.0f;

  double sumSq = 0.0;
  for (int i = 0; i < n; i++) {
    // MSM261 envia 24 bits MSB-aligned em 32 bits => deslocar 8 bits à direita
    int32_t s = samples[i] >> 8;
    sumSq += (double)s * (double)s;
  }
  double rms = sqrt(sumSq / n);
  if (rms < 1.0) rms = 1.0;
  // 0 dBFS = 2^23 (24-bit full-scale)
  float dbfs = 20.0f * log10f((float)rms / 8388608.0f);
  // Convertemos para um nível "positivo" estilo SPL relativo (offset +94 é típico para MEMS);
  // continua a ser uma estimativa — calibrar com sonómetro real se necessário.
  return dbfs + 94.0f;
}

// ======================== UTILIDADES ========================
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

// ======================== CLASSIFICAÇÕES ========================
String classifyAirQuality(int value) {
  if (value < AIR_GOOD)     return "bom";
  if (value < AIR_MODERATE) return "aceitavel";
  if (value < AIR_BAD)      return "necessita_ventilacao";
  return "mau";
}

String classifyLight(int analogValue, int digitalValue) {
  // No módulo LM393, AO menor = mais luz; DO=0 quando acima do limiar do potenciómetro.
  if (digitalValue == 0) return "bom";
  if (analogValue < LIGHT_OK)  return "adequado";
  if (analogValue < LIGHT_LOW) return "insuficiente";
  return "escuro";
}

String classifyNoise(float dbValue) {
  if (dbValue < NOISE_LOW)      return "baixo";
  if (dbValue < NOISE_MODERATE) return "moderado";
  if (dbValue < NOISE_HIGH)     return "elevado";
  return "muito_elevado";
}

String classifyComfort(float temp, float hum, int air, const String& light, float noise) {
  int score = 0;
  if (temp < TEMP_MIN || temp > TEMP_MAX) score += 2;
  if (hum  < HUM_MIN  || hum  > HUM_MAX)  score += 1;
  if (air > AIR_BAD)      score += 2;
  else if (air > AIR_MODERATE) score += 1;
  if (light == "insuficiente" || light == "escuro") score += 1;
  if (noise > NOISE_HIGH)      score += 2;
  else if (noise > NOISE_MODERATE) score += 1;

  if (score <= 1) return "bom";
  if (score <= 3) return "moderado";
  return "mau";
}

void updateLEDFromComfort(const String& comfort) {
  // (Lógica antiga — mantida por compatibilidade, não é chamada por defeito.)
  if (comfort == "bom")          setLED(0, 255, 0);     // Verde
  else if (comfort == "moderado") setLED(255, 180, 0);  // Amarelo/laranja
  else                            setLED(255, 0, 0);    // Vermelho
}

// Atualiza o LED RGB conforme o estado de ocupação vindo do Firebase:
//   "livre"   → verde   (pelo menos uma mesa livre)
//   "parcial" → amarelo (mesas todas ocupadas mas cadeiras livres)
//   "cheio"   → vermelho (cadeiras todas ocupadas)
void updateLEDFromOccupancy(const String& status) {
  if (status == "livre")        setLED(0, 255, 0);
  else if (status == "parcial") setLED(255, 180, 0);
  else if (status == "cheio")   setLED(255, 0, 0);
  else                          setLED(0, 0, 64);   // azul ténue = sem dados ainda
}

// Lê rooms/<ROOM_ID>/occupancy/status do Firebase e pinta o LED.
// Chamada periodicamente no loop (a cada OCCUPANCY_POLL_INTERVAL).
void pollOccupancyStatus() {
  if (!firebaseReady || !Firebase.ready()) return;

  String path = String("rooms/") + ROOM_ID + "/occupancy/status";
  if (Firebase.RTDB.getString(&fbdoOccupancy, path.c_str())) {
    String status = fbdoOccupancy.stringData();
    if (status != lastStatus) {
      Serial.printf("[Occupancy] Estado atualizado: '%s'\n", status.c_str());
      lastStatus = status;
      updateLEDFromOccupancy(status);
    }
  } else {
    Serial.printf("[Occupancy] Sem leitura: %s\n", fbdoOccupancy.errorReason().c_str());
  }
}

// ======================== LEITURA + ENVIO ========================
void readAndSend() {
  // --- Sensores ---
  float temperature = dht.readTemperature();
  float humidity    = dht.readHumidity();
  int   airQuality  = analogRead(MQ135_PIN);
  int   lightA      = analogRead(LIGHT_A_PIN);
  int   lightD      = digitalRead(LIGHT_D_PIN);
  float noiseDb     = readNoiseDBFS();

  // Validar DHT11
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("[DHT11] Erro de leitura.");
    temperature = -1.0f;
    humidity    = -1.0f;
  }

  // --- Classificações ---
  String airClass   = classifyAirQuality(airQuality);
  String lightClass = classifyLight(lightA, lightD);
  String noiseClass = classifyNoise(noiseDb);
  String comfort    = classifyComfort(temperature, humidity, airQuality, lightClass, noiseDb);
  String timestamp  = getTimestamp();

  // NOTA: o LED já NÃO é controlado pelo conforto local.
  // É controlado por pollOccupancyStatus() que lê rooms/.../occupancy/status do Firebase.

  // --- Log ---
  Serial.println("─────────────────────────────");
  Serial.printf("[%s] Leitura dos sensores:\n", timestamp.c_str());
  Serial.printf("  Temperatura:  %.1f °C\n", temperature);
  Serial.printf("  Humidade:     %.1f %%\n", humidity);
  Serial.printf("  Ar (MQ-135):  %d (%s)\n", airQuality, airClass.c_str());
  Serial.printf("  Luz (LM393):  A=%d D=%d (%s)\n", lightA, lightD, lightClass.c_str());
  Serial.printf("  Ruído (I2S):  %.1f dB (%s)\n", noiseDb, noiseClass.c_str());
  Serial.printf("  Conforto:     %s\n", comfort.c_str());

  if (!firebaseReady || !Firebase.ready()) {
    Serial.println("[Firebase] Não pronto — leitura local apenas.");
    return;
  }

  // --- JSON para Firebase ---
  FirebaseJson json;
  json.set("timestamp",       timestamp);
  json.set("temperature",     temperature);
  json.set("humidity",        humidity);
  json.set("air_quality_raw", airQuality);
  json.set("air_quality",     airClass);
  json.set("light_raw",       lightA);
  json.set("light_digital",   lightD);
  json.set("light",           lightClass);
  json.set("noise_db",        noiseDb);
  json.set("noise",           noiseClass);
  json.set("comfort",         comfort);

  String basePath = String("rooms/") + ROOM_ID + "/environment";

  if (Firebase.RTDB.setJSON(&fbdo, (basePath + "/current").c_str(), &json)) {
    Serial.println("[Firebase] /current OK");
  } else {
    Serial.printf("[Firebase] Erro /current: %s\n", fbdo.errorReason().c_str());
  }

  if (Firebase.RTDB.pushJSON(&fbdo, (basePath + "/history").c_str(), &json)) {
    Serial.println("[Firebase] /history OK");
  } else {
    Serial.printf("[Firebase] Erro /history: %s\n", fbdo.errorReason().c_str());
  }
}

// ======================== SETUP ========================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[SmartRoom] Sensor_NODE — Arranque");

  // DHT11
  dht.begin();

  // LM393 (digital)
  pinMode(LIGHT_D_PIN, INPUT);

  // I2S microfone
  i2sMicInit();

  // LED RGB
  ledcSetup(CH_R, PWM_FREQ, PWM_RES);
  ledcSetup(CH_G, PWM_FREQ, PWM_RES);
  ledcSetup(CH_B, PWM_FREQ, PWM_RES);
  ledcAttachPin(LED_R_PIN, CH_R);
  ledcAttachPin(LED_G_PIN, CH_G);
  ledcAttachPin(LED_B_PIN, CH_B);
  setLED(0, 0, 255); // Azul = a arrancar

  // Wi-Fi
  connectWiFi();

  // NTP
  configTime(GMT_OFFSET, DST_OFFSET, NTP_SERVER);
  struct tm timeinfo;
  int ntpAttempts = 0;
  while (!getLocalTime(&timeinfo) && ntpAttempts < 20) {
    delay(500);
    ntpAttempts++;
  }
  Serial.println("[NTP] Relógio sincronizado.");

  // Firebase
  fbConfig.api_key      = API_KEY;
  fbConfig.database_url = DATABASE_URL;
  auth.user.email       = USER_EMAIL;
  auth.user.password    = USER_PASSWORD;
  fbConfig.token_status_callback = tokenStatusCallback;

  Firebase.begin(&fbConfig, &auth);
  Firebase.reconnectWiFi(true);

  Serial.print("[Firebase] A autenticar");
  unsigned long fbStart = millis();
  while (!Firebase.ready() && millis() - fbStart < 15000) {
    Serial.print(".");
    delay(300);
  }
  Serial.println();
  firebaseReady = Firebase.ready();
  Serial.printf("[Firebase] %s\n", firebaseReady ? "Pronto." : "Sem autenticação (continua em modo local).");

  setLED(0, 0, 64); // Azul ténue = pronto, à espera do 1.º status de ocupação
  delay(500);
}

// ======================== LOOP ========================
void loop() {
  unsigned long now = millis();

  // Leituras dos sensores ambientais a cada READ_INTERVAL (30 s)
  if (now - lastRead >= READ_INTERVAL || lastRead == 0) {
    lastRead = now;
    readAndSend();
  }

  // Atualização do LED (status de ocupação) a cada OCCUPANCY_POLL_INTERVAL (5 s)
  if (now - lastOccupancy >= OCCUPANCY_POLL_INTERVAL || lastOccupancy == 0) {
    lastOccupancy = now;
    pollOccupancyStatus();
  }

  delay(50);
}
