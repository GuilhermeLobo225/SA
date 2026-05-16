/*
 * Sala de Estudo Inteligente — Nó de Visão (Vision_NODE)
 * Placa: AI Thinker ESP32-CAM (OV2640)
 *
 * Captura uma imagem a cada CAPTURE_INTERVAL e envia para Firebase Storage.
 * Regista o caminho da imagem em /rooms/<ROOM_ID>/latest_image (RTDB).
 *
 * Bibliotecas (lib_deps em platformio.ini):
 *   - mobizt/Firebase Arduino Client Library for ESP8266 and ESP32
 *
 * Esquema de partição recomendado: huge_app.csv
 */

#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <Firebase_ESP_Client.h>
#include "addons/TokenHelper.h"
#include "addons/RTDBHelper.h"
#include "time.h"

// ======================== CONFIGURAÇÃO ========================
// Wi-Fi
#define WIFI_SSID      "luismpso"
#define WIFI_PASSWORD  "Luis2002"

// Firebase
#define API_KEY        "AIzaSyAiJmQoEoeO0JrfeVRpwmQwWVu4mSWOoEg"
#define STORAGE_BUCKET "vision-node-ef817.firebasestorage.app"
// ⚠️ Tens de criar o Realtime Database no Firebase Console e confirmar este URL.
#define DATABASE_URL   "https://vision-node-ef817-default-rtdb.europe-west1.firebasedatabase.app/"
#define USER_EMAIL     "esp32cam@smartroom.local"
#define USER_PASSWORD  "admin123"

// Identificação da sala
#define ROOM_ID        "sala_b1_piso2"

// Intervalo de captura (ms). 15 s dá boa responsividade e ainda dá tempo a
// uploads SVGA num Wi-Fi típico. Subir para 30 s se a rede for fraca.
#define CAPTURE_INTERVAL 15000UL

// NTP
#define NTP_SERVER "pool.ntp.org"
#define GMT_OFFSET  0
#define DST_OFFSET  3600

// ======================== PINOS ESP32-CAM (AI-Thinker) ========================
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22
#define FLASH_GPIO_NUM   4

// ======================== ESTADO GLOBAL ========================
FirebaseData   fbdo;
FirebaseAuth   auth;
FirebaseConfig fbConfig;

unsigned long lastCapture = 0;
bool          firebaseReady = false;

// ======================== PROTÓTIPOS ========================
void initCamera();
void connectWiFi();
String getTimestamp();
void captureAndUpload();

// ======================== SETUP ========================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[SmartRoom] Vision_NODE — Arranque");

  // Desligar flash LED
  pinMode(FLASH_GPIO_NUM, OUTPUT);
  digitalWrite(FLASH_GPIO_NUM, LOW);

  initCamera();
  connectWiFi();

  // NTP
  configTime(GMT_OFFSET, DST_OFFSET, NTP_SERVER);
  Serial.println("[NTP] A sincronizar relógio...");
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
  Serial.printf("[Firebase] %s\n", firebaseReady ? "Pronto." : "Sem autenticação.");
}

// ======================== LOOP ========================
void loop() {
  if (!firebaseReady) {
    delay(500);
    return;
  }

  unsigned long now = millis();
  if (now - lastCapture >= CAPTURE_INTERVAL || lastCapture == 0) {
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

  // Resolução: SVGA (800×600) é mais que suficiente para o YOLO (que redimensiona
  // para 640×640 internamente). Antes usávamos UXGA (1600×1200) mas o ficheiro
  // ficava com ~200 KB, demasiado lento no Wi-Fi → uploads de 60-90 s e
  // intervalos reais de 2 min entre fotos. Com SVGA descemos para ~40-80 KB e
  // uploads de ~5-10 s.
  if (psramFound()) {
    cconfig.frame_size   = FRAMESIZE_SVGA;   // 800x600
    cconfig.jpeg_quality = 12;
    cconfig.fb_count     = 2;
  } else {
    cconfig.frame_size   = FRAMESIZE_VGA;    // 640x480 (fallback ainda mais pequeno)
    cconfig.jpeg_quality = 15;
    cconfig.fb_count     = 1;
  }

  esp_err_t err = esp_camera_init(&cconfig);
  if (err != ESP_OK) {
    Serial.printf("[Câmara] Erro init: 0x%x\n", err);
    ESP.restart();
  }

  sensor_t *s = esp_camera_sensor_get();
  s->set_brightness(s, 1);
  s->set_contrast(s, 1);
  s->set_vflip(s, 1);       // Ajustar conforme montagem
  s->set_hmirror(s, 0);

  Serial.println("[Câmara] Inicializada.");
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
  String path = String("dados_camara/") + ROOM_ID + "/" + timestamp + ".jpg";

  Serial.printf("[Upload] A enviar %s (%u bytes)...\n", path.c_str(), (unsigned)fb->len);

  if (Firebase.Storage.upload(
        &fbdo, STORAGE_BUCKET, fb->buf, fb->len,
        path.c_str(), "image/jpeg")) {
    Serial.println("[Upload] Sucesso.");

    String dbPath = String("rooms/") + ROOM_ID + "/latest_image";
    Firebase.RTDB.setString(&fbdo, dbPath.c_str(), path.c_str());

    String tsPath = String("rooms/") + ROOM_ID + "/last_capture";
    Firebase.RTDB.setString(&fbdo, tsPath.c_str(), timestamp.c_str());
  } else {
    Serial.printf("[Upload] Erro: %s\n", fbdo.errorReason().c_str());
  }

  esp_camera_fb_return(fb);
}
