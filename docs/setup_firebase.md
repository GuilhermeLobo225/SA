# Configuração do Firebase

O sistema usa **dois projetos Firebase separados** para isolar responsabilidades e cumprir o requisito de *privacy by design* (as imagens da câmara ficam noutra base de dados que não a dos sensores ambientais):

| Projeto | Serviços | Conteúdo |
|---|---|---|
| **Vision** (`vision-node-…`) | Storage + Realtime DB | Imagens da ESP32-CAM + ponteiro para a última imagem |
| **Sensor** (`sensor-node-…`) | Realtime DB | Leituras ambientais, ocupação calculada, estado do LED |

O fluxo é:

```
ESP32-CAM  ─────────►  Vision Storage  ◄─────  detector.py (lê e apaga)
                              │
                              ▼
                       Vision RTDB
                       (latest_image path)

Sensor ESP32  ────────►  Sensor RTDB  ◄──────  detector.py (escreve ocupação)
                              ▲
                              │
                              └──────────────  api.py (lê e expõe REST)
```

## 1. Criar os projetos

Para cada projeto (repetir os passos):

1. Ir a [Firebase Console](https://console.firebase.google.com/) → **Adicionar projeto**
2. Nomear `vision-node` e `sensor-node` (os IDs reais incluem um sufixo automático)
3. Desativar Google Analytics (opcional para protótipo)

## 2. Ativar serviços em cada projeto

### Projeto **Vision**

**Realtime Database**
1. Build → Realtime Database → Create Database
2. Região: `europe-west1`
3. Iniciar em **test mode**
4. Tomar nota do URL (ex.: `https://vision-node-XXXX-default-rtdb.europe-west1.firebasedatabase.app`)

**Storage**
1. Build → Storage → Get Started
2. **test mode**
3. Tomar nota do bucket (ex.: `vision-node-XXXX.firebasestorage.app`)

**Authentication**
1. Build → Authentication → Get Started → Email/Password ✔
2. Add user: `esp32cam@smartroom.local` com password forte

### Projeto **Sensor**

**Realtime Database**
1. Igual ao Vision (região `europe-west1`, test mode)
2. Tomar nota do URL (ex.: `https://sensor-node-XXXX-default-rtdb.europe-west1.firebasedatabase.app`)

**Authentication**
1. Email/Password ✔
2. Add user: `esp32env@smartroom.local`

## 3. Credenciais

### Para os ESP32 (firmware)

Em cada `main.cpp`:

```cpp
#define API_KEY        "AIzaSy..."                         // Project Settings → General → Web API Key
#define DATABASE_URL   "https://...firebasedatabase.app"   // RTDB do respetivo projeto
#define STORAGE_BUCKET "vision-node-XXXX.firebasestorage.app"  // só no Vision_NODE
#define USER_EMAIL     "esp32cam@smartroom.local"           // ou esp32env@
#define USER_PASSWORD  "..."
```

Cada nó vai ao **seu** projeto:

- `vision/src/main.cpp` → projeto **Vision** (Storage + RTDB)
- `sensor/src/main.cpp` → projeto **Sensor** (apenas RTDB)

### Para o Python (`processing/`)

Em cada projeto: **Project Settings → Service Accounts → Generate New Private Key**

Guardar os ficheiros em `processing/secrets/` (criar a pasta):

```
processing/secrets/
  vision-credentials.json    ← do projeto Vision
  sensor-credentials.json    ← do projeto Sensor
```

> ⚠️ **Estes ficheiros NUNCA podem ir para o git.** O `.gitignore` já tem `processing/secrets/`.

Os caminhos e URLs estão configurados em `processing/config.py`:

```python
VISION_CREDENTIALS    = ".../secrets/vision-credentials.json"
VISION_STORAGE_BUCKET = "vision-node-XXXX.firebasestorage.app"
VISION_DATABASE_URL   = "https://vision-node-XXXX-default-rtdb.europe-west1.firebasedatabase.app"

SENSOR_CREDENTIALS    = ".../secrets/sensor-credentials.json"
SENSOR_DATABASE_URL   = "https://sensor-node-XXXX-default-rtdb.europe-west1.firebasedatabase.app"
```

## 4. Regras de segurança (produção)

### Vision — RTDB
```json
{
  "rules": {
    "rooms": {
      ".read":  "auth != null",
      ".write": "auth != null"
    }
  }
}
```

### Vision — Storage
```
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    match /images/{allPaths=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```

### Sensor — RTDB
```json
{
  "rules": {
    "rooms": {
      ".read":  true,                      // o website lê via a API local; pode ficar público
      ".write": "auth != null"
    }
  }
}
```

## 5. Estrutura da Base de Dados

### Projeto Vision (RTDB)

```
rooms/
  sala_b1_piso2/
    latest_image: "images/sala_b1_piso2/20260515_153334.jpg"
    last_capture: "20260515_153334"
```

E o Storage:

```
images/
  sala_b1_piso2/
    20260515_153334.jpg
    20260515_153404.jpg
    ...
```

(O `detector.py` apaga cada imagem depois de a processar, se `DELETE_AFTER_INFERENCE=True` em `config.py`.)

### Projeto Sensor (RTDB)

```
rooms/
  sala_b1_piso2/
    occupancy/
      current/
        room_id:        "sala_b1_piso2"
        timestamp:      "2026-05-15T16:24:01"
        people:         1
        chairs_total:   8
        chairs_free:    7
        capacity:       8
        tables:         2
        occupancy_pct:  12.5
        status:         "livre"           # livre | parcial | cheio (3 estados — LED)
      history/
        -abc.../  (snapshots históricos)
      status:           "livre"           # cópia simples, lida pelo Sensor_NODE para o LED
    environment/
      current/
        timestamp:        "2026-05-15T16:24:00"
        temperature:      21.8            # °C (DHT11)
        humidity:         48              # %  (DHT11)
        air_quality_raw:  441             # ADC 12-bit
        air_quality:      "aceitavel"     # bom | aceitavel | necessita_ventilacao | mau
        light_raw:        125             # ADC 12-bit (fotodíodo)
        light_digital:    0               # 0/1 (limiar do potenciómetro do LM393)
        light:            "adequado"      # bom | adequado | insuficiente | escuro
        noise_db:         32.5            # dB relativo (MSM261 I2S)
        noise:            "baixo"         # baixo | moderado | elevado | muito_elevado
        comfort:          "bom"           # bom | moderado | mau
      history/
        -def.../
```

> A `api.py` lê estes campos do projeto Sensor, **achata-os** num único objeto JSON e devolve-os ao frontend (website + app) — ver contrato no `README.md` raiz.
