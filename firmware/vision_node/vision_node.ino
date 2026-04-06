/*
 * Sala de Estudo Inteligente — Nó de Visão
 * ESP32-CAM (AI-Thinker) + OV2640
 *
 * Captura uma imagem a cada 30 segundos e envia para Firebase Storage.
 *
 * Bibliotecas necessárias (Arduino Library Manager):
 *   - Firebase ESP Client (by mobizt)
 *
 * Board: AI Thinker ESP32-CAM
 * Partition Scheme: Huge APP (3MB No OTA / 1MB SPIFFS)
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <Firebase_ESP_Client.h>
#include "addons/TokenHelper.h"
#include "time.h"

// ======================== CONFIGURAÇÃO ========================
// Wi-Fi
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// Firebase
#define API_KEY       "YOUR_FIREBASE_API_KEY"
#define STORAGE_BUCKET "YOUR_PROJECT.appspot.com"
#define DATABASE_URL   "https://YOUR_PROJECT.firebaseio.com"
// Email/password de uma conta de serviço criada no Firebase Auth
#define USER_EMAIL    "esp32cam@smartroom.local"
#define USER_PASSWORD "YOUR_SERVICE_PASSWORD"

// Sala
#define ROOM_ID       "sala_b1_piso2"

// Intervalo de captura (ms)
#define CAPTURE_INTERVAL 30000

// NTP
#define NTP_SERVER "pool.ntp.org"
#define GMT_OFFSET 0
#define DST_OFFSET 3600

// ======================== PINOS ESP32-CAM (AI-Thinker) ========================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

#define FLASH_GPIO_NUM     4

// ======================== VARIÁVEIS GLOBAIS ========================
FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

unsigned long lastCapture = 0;
bool firebaseReady = false;

// ======================== SETUP ========================
void setup() {
  Serial.begin(115200);
  Serial.println("\n[SmartRoom] Nó de Visão — Arranque");

  // Desligar flash LED
  pinMode(FLASH_GPIO_NUM, OUTPUT);
  digitalWrite(FLASH_GPIO_NUM, LOW);

  // Inicializar câmara
  initCamera();

  // Ligar Wi-Fi
  connectWiFi();

  // Sincronizar relógio
  configTime(GMT_OFFSET, DST_OFFSET, NTP_SERVER);
  Serial.println("[NTP] A sincronizar relógio...");
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    delay(500);
  }
  Serial.println("[NTP] Relógio sincronizado.");

  // Inicializar Firebase
  config.api_key = API_KEY;
  config.database_url = DATABASE_URL;
  auth.user.email = USER_EMAIL;
  auth.user.password = USER_PASSWORD;
  config.token_status_callback = tokenStatusCallback;

  Firebase.begin(&config, &auth);
  Firebase.reconnectWiFi(true);

  // Aguardar autenticação
  Serial.print("[Firebase] A autenticar");
  while (!Firebase.ready()) {
    Serial.print(".");
    delay(300);
  }
  Serial.println("\n[Firebase] Pronto.");
  firebaseReady = true;
}

// ======================== LOOP ========================
void loop() {
  if (!firebaseReady) return;

  unsigned long now = millis();
  if (now - lastCapture >= CAPTURE_INTERVAL) {
    lastCapture = now;
    captureAndUpload();
  }

  delay(100);
}

// ======================== FUNÇÕES ========================

void initCamera() {
  camera_config_t cconfig;
  cconfig.ledc_channel = LEDC_CHANNEL_0;
  cconfig.ledc_timer   = LEDC_TIMER_0;
  cconfig.pin_d0       = Y2_GPIO_NUM;
  cconfig.pin_d1       = Y3_GPIO_NUM;
  cconfig.pin_d2       = Y4_GPIO_NUM;
  cconfig.pin_d3       = Y5_GPIO_NUM;
  cconfig.pin_d4       = Y6_GPIO_NUM;
  cconfig.pin_d5       = Y7_GPIO_NUM;
  cconfig.pin_d6       = Y8_GPIO_NUM;
  cconfig.pin_d7       = Y9_GPIO_NUM;
  cconfig.pin_xclk     = XCLK_GPIO_NUM;
  cconfig.pin_pclk     = PCLK_GPIO_NUM;
  cconfig.pin_vsync    = VSYNC_GPIO_NUM;
  cconfig.pin_href     = HREF_GPIO_NUM;
  cconfig.pin_sscb_sda = SIOD_GPIO_NUM;
  cconfig.pin_sscb_scl = SIOC_GPIO_NUM;
  cconfig.pin_pwdn     = PWDN_GPIO_NUM;
  cconfig.pin_reset    = RESET_GPIO_NUM;
  cconfig.xclk_freq_hz = 20000000;
  cconfig.pixel_format = PIXFORMAT_JPEG;

  // Resolução e qualidade
  if (psramFound()) {
    cconfig.frame_size   = FRAMESIZE_UXGA;  // 1600x1200
    cconfig.jpeg_quality = 12;
    cconfig.fb_count     = 2;
  } else {
    cconfig.frame_size   = FRAMESIZE_SVGA;  // 800x600
    cconfig.jpeg_quality = 15;
    cconfig.fb_count     = 1;
  }

  esp_err_t err = esp_camera_init(&cconfig);
  if (err != ESP_OK) {
    Serial.printf("[Câmara] Erro ao inicializar: 0x%x\n", err);
    ESP.restart();
  }

  // Ajustes de imagem para vista aérea
  sensor_t *s = esp_camera_sensor_get();
  s->set_brightness(s, 1);
  s->set_contrast(s, 1);
  s->set_vflip(s, 1);      // Ajustar se câmara montada invertida
  s->set_hmirror(s, 0);

  Serial.println("[Câmara] Inicializada com sucesso.");
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
    Serial.println("\n[WiFi] Falha na ligação. A reiniciar...");
    ESP.restart();
  }
  Serial.printf("\n[WiFi] Ligado. IP: %s\n", WiFi.localIP().toString().c_str());
}

String getTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return "unknown";
  char buf[25];
  strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", &timeinfo);
  return String(buf);
}

void captureAndUpload() {
  Serial.println("[Captura] A capturar imagem...");

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[Captura] Falha ao capturar frame.");
    return;
  }

  String timestamp = getTimestamp();
  String path = String("images/") + ROOM_ID + "/" + timestamp + ".jpg";

  Serial.printf("[Upload] A enviar %s (%d bytes)...\n", path.c_str(), fb->len);

  if (Firebase.Storage.upload(
        &fbdo, STORAGE_BUCKET, fb->buf, fb->len,
        path.c_str(), "image/jpeg")) {
    Serial.println("[Upload] Sucesso.");

    // Registar metadados no Realtime Database
    String dbPath = String("rooms/") + ROOM_ID + "/latest_image";
    Firebase.RTDB.setString(&fbdo, dbPath.c_str(), path.c_str());

    String tsPath = String("rooms/") + ROOM_ID + "/last_capture";
    Firebase.RTDB.setString(&fbdo, tsPath.c_str(), timestamp.c_str());
  } else {
    Serial.printf("[Upload] Erro: %s\n", fbdo.errorReason().c_str());
  }

  esp_camera_fb_return(fb);
}
