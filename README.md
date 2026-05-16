# 🏛️ Sala de Estudo Inteligente

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Arduino](https://img.shields.io/badge/Arduino-ESP32-teal)
![License](https://img.shields.io/badge/License-Academic-lightgrey)

> **Sensorização e Ambiente** | Mestrado em Inteligência Artificial | Universidade do Minho | 2025/26

Sistema distribuído de baixo custo para deteção de ocupação e monitorização de conforto ambiental em salas de estudo universitárias, baseado em ESP32, YOLOv8 e sensores IoT.

---

## 📊 Arquitetura

O sistema é composto por três camadas: sensorização (dois nós ESP32), processamento (YOLOv8 + DeepSORT na cloud) e apresentação (dashboard web + LED local).

```
Camada de Sensorização
┌──────────────┐    ┌──────────────────────────────────────┐
│  Nó de Visão │    │            Nó Ambiental              │
│  ESP32-CAM   │    │  ESP32-S3 DevKitC-1                  │
│  OV2640 2MP  │    │  DHT11 │ MQ-135 │ LM393 │ MSM261S4030│
└──────┬───────┘    └───────────┬──────────────────────────┘
       │  Wi-Fi                │  Wi-Fi
       ▼                       ▼
┌─────────────────────────────────────┐
│     Camada de Processamento         │
│  Firebase Storage + Realtime DB     │
│  YOLOv8 → DeepSORT → Agregação     │
│  API REST                           │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│     Camada de Apresentação          │
│  Dashboard Web │ App Móvel │ LED RGB│
└─────────────────────────────────────┘
```

> 📄 **Artigo:** [Ver PDF do Artigo](docs/SA2026_paper_6906.pdf)

---

## ⚙️ Implementações

### Nó de Visão (ESP32-CAM)

- Captura de imagem a cada 30 segundos via OV2640 (2 MP)
- Transmissão para Firebase Storage via Wi-Fi
- Montagem no teto com orientação aérea
- Eliminação automática das imagens após inferência (privacy by design)

### Nó Ambiental (ESP32-S3 DevKitC-1)

- **DHT11:** temperatura (±2°C) e humidade relativa (±5%)
- **MQ-135:** qualidade do ar (índice relativo, sensor SnO2)
- **LM393 (módulo fotodíodo):** iluminância — saída analógica (intensidade) + saída digital (limiar)
- **MSM261S4030H0:** microfone MEMS digital I2S de 24 bits para nível de ruído (RMS / dB relativo)
- **LED RGB:** feedback visual de conforto (verde/amarelo/vermelho)
- Leitura a cada 30 segundos, envio para Firebase Realtime Database

### Processamento (Python)

- **YOLOv11** (YOLOv8-API compatível) para deteção de pessoas nas imagens — usamos o `yolo11x.pt` (extra-large, máxima precisão)
- **DeepSORT** para rastreamento temporal e estabilidade das contagens entre frames
- A capacidade da sala vem da configuração (`ROOM_TABLES × CHAIRS_PER_TABLE`), não da deteção — o YOLO conta apenas pessoas; as cadeiras só aparecem como debug visual nos frames anotados (resolve o viés do COCO em cadeiras vazias e a oclusão por pessoas sentadas)
- Classificação de ocupação em dois níveis:
  - **3 estados** internos (`livre` / `parcial` / `cheio`) — consumidos pelo firmware do LED
  - **5 estados** públicos (`vazio` / `disponivel` / `parcialmente_ocupado` / `quase_cheio` / `cheio`) — derivados na API a partir da percentagem, para os badges do website e da app
- API REST (Flask) com contrato unificado, mapeando o ID interno da sala (`sala_b1_piso2`) para o ID público da biblioteca (`bg`)

### Dashboard Web e App Móvel

Ambos os clientes consomem o **mesmo endpoint REST** (`/api/rooms/{id}`) servido pelo `processing/api.py` e partilham os mesmos ficheiros estáticos (`libraries.json`, `books.csv`).

- **Website** (`website/`): HTML + JS vanilla, planta da sala em SVG, polling a cada 15 s, fallback para mock quando a API está offline
- **App Android** (`app/`): Kotlin nativo, mesma planta em `Canvas` (`PlantaView`), `ApiClient` com `HttpURLConnection`+`org.json`, geofence de chegada à BG que dispara notificações com a ocupação atual
- Código de cores alinhado: 🟢 vazio, 🟡 parcial, 🔴 cheio

---

## 🔌 Contrato da API REST

`processing/api.py` corre na porta 5000 (`http://localhost:5000` no PC, `http://10.0.2.2:5000` no emulador Android).

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/health` | Sanidade do serviço |
| GET | `/api/rooms` | Lista de salas com sensorização ativa |
| GET | `/api/rooms/{id}` | Snapshot completo (ocupação + ambiente) |
| GET | `/api/rooms/{id}/occupancy` | Apenas ocupação |
| GET | `/api/rooms/{id}/environment` | Apenas dados ambientais |

`{id}` aceita o ID público (`bg`) ou o interno (`sala_b1_piso2`).

Forma da resposta de `/api/rooms/{id}`:

```jsonc
{
  "room_id":        "bg",
  "timestamp":      "2026-05-15T16:24:01",

  // Ocupação
  "count":          1,                       // pessoas detetadas (alias: "people")
  "capacity":       8,
  "tables":         2,
  "chairs_total":   8,
  "chairs_free":    7,
  "occupancy_pct":  12.5,
  "status":         "disponivel",            // 5 níveis para UI
  "status_simple":  "livre",                 // 3 níveis para LED

  // Ambiente — valores numéricos primários
  "temperature":    21.8,                    // °C
  "humidity":       48,                      // %
  "air_quality":    441,                     // ADC 12-bit MQ-135
  "light":          125,                     // ADC 12-bit fotodíodo
  "light_digital":  0,
  "noise_db":       32.5,

  // Ambiente — classes textuais (badges)
  "comfort":            "bom",               // bom | moderado | mau
  "air_quality_class":  "aceitavel",         // bom | aceitavel | necessita_ventilacao | mau
  "light_class":        "adequado",          // bom | adequado | insuficiente | escuro
  "noise":              "baixo"              // baixo | moderado | elevado | muito_elevado
}
```

---

## 🔧 Hardware

### Nó de Visão

| Componente | Qtd. | Função |
|---|---|---|
| ESP32-CAM (AI-Thinker) | 1 | Captura de imagem |
| Programador FTDI (USB-Serial) | 1 | Upload de firmware |

### Nó Ambiental

| Componente | Qtd. | Função |
|---|---|---|
| ESP32-S3 DevKitC-1 | 1 | Microcontrolador |
| DHT11 | 1 | Temperatura e humidade |
| MQ-135 | 1 | Qualidade do ar |
| Módulo fotodíodo c/ LM393 | 1 | Iluminância (analógico + digital) |
| MSM261S4030H0 (microfone I2S MEMS) | 1 | Nível sonoro |
| LED RGB (cátodo comum) + 3× 220Ω | 1 | Feedback visual |
| Breadboard + jumpers | — | Prototipagem |

#### Pinagem (ESP32-S3 DevKitC-1)

| Sinal | GPIO | Notas |
|---|---|---|
| DHT11 DATA | 4 | 1-wire digital, pull-up 10kΩ |
| MQ-135 AOUT | 5 | ADC1_CH4 (analógico) |
| LM393 AOUT (luz) | 6 | ADC1_CH5 (analógico) |
| LM393 DOUT (luz) | 7 | digital — limiar do potenciómetro |
| MSM261 BCLK | 14 | I2S bit clock |
| MSM261 WS / LRCL | 15 | I2S word select |
| MSM261 DOUT / SD | 13 | I2S data in |
| LED RGB — R | 16 | PWM (LEDC ch 0) |
| LED RGB — G | 17 | PWM (LEDC ch 1) |
| LED RGB — B | 18 | PWM (LEDC ch 2) |

> O microfone MSM261S4030H0 alimenta-se a 3.3 V e tem o pino **SEL ligado a GND** (canal esquerdo).

---

## 📏 Limiares de Conforto

| Parâmetro | Sensor | Limiar | Referência |
|---|---|---|---|
| Temperatura | DHT11 | 20–26 °C | ASHRAE 55 |
| Humidade | DHT11 | 30–70% | — |
| Qualidade do ar | MQ-135 | < 800 (ADC bruto 12-bit) | Calibração empírica |
| Iluminância | LM393 fotodíodo | < 2500 (ADC) ou DO=0 | EN 12464-1 |
| Ruído | MSM261S4030H0 (I2S) | < 55 dB relativo | OMS |

---

## 📂 Estrutura do Repositório

```
SA/
├── sensor/                            # Nó Ambiental (PlatformIO, ESP32-S3)
│   └── Sensor_NODE/
│       ├── platformio.ini             #   Configuração do projeto + libs
│       ├── src/
│       │   └── main.cpp               #   DHT11 + MQ-135 + LM393 + I2S + LED RGB
│       ├── include/  lib/  test/
│
├── vision/                            # Nó de Visão (PlatformIO, ESP32-CAM)
│   └── Vision_NODE/
│       ├── platformio.ini
│       ├── src/
│       │   └── main.cpp               #   OV2640: captura + upload Storage
│       ├── include/  lib/  test/
│
├── processing/                        # Pipeline Python
│   ├── detector.py                    #   YOLOv11 + DeepSORT + push de ocupação
│   ├── firebase_sync.py               #   Sincronização Firebase (2 projetos)
│   ├── api.py                         #   API REST (Flask) — contrato unificado
│   ├── config.py                      #   Configurações (sala, YOLO, thresholds)
│   ├── requirements.txt               #   Dependências Python
│   ├── secrets/                       #   ⚠️ NÃO versionar
│   │   ├── vision-credentials.json    #   Service account do projeto Vision
│   │   └── sensor-credentials.json    #   Service account do projeto Sensor
│   └── temp_images/_annotated/        #   Frames com bounding boxes (debug)
│
├── website/                           # Dashboard web (HTML + CSS + JS vanilla)
│   ├── index.html  biblioteca.html
│   ├── js/  data/  style.css
│
├── app/                               # App Android (Kotlin)
│   └── app/src/main/java/pt/uminho/sa/{data,geofence,ui}/
│
├── docs/                              # Documentação
│   ├── SA2026_paper_6906.pdf          #   Artigo (LNCS)
│   ├── wiring_vision.md               #   Esquema de ligações — nó de visão
│   ├── wiring_environmental.md        #   Esquema de ligações — nó ambiental
│   └── firebase_setup.md              #   Guia de configuração Firebase (2 projetos)
│
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🚀 Reprodução

### Pré-requisitos

* **PlatformIO** (VSCode + extensão PlatformIO IDE).
* **Python 3.11+** com pip.
* **Conta Firebase** com Realtime Database e Storage ativados.

### Passos

1. **Clonar o repositório:**
   ```bash
   git clone https://github.com/SEU_USER/SA.git
   cd SA
   ```

2. **Configurar Firebase (dois projetos):**
   - Seguir o guia em [`docs/firebase_setup.md`](docs/firebase_setup.md)
   - Criar `processing/secrets/` e colocar lá:
     - `vision-credentials.json` (service account do projeto **Vision**, com Storage + RTDB)
     - `sensor-credentials.json` (service account do projeto **Sensor**, com RTDB)
   - Confirmar `VISION_DATABASE_URL`, `VISION_STORAGE_BUCKET` e `SENSOR_DATABASE_URL` em `processing/config.py`

3. **Configurar firmware:**
   - Editar `WIFI_SSID`, `WIFI_PASSWORD`, `API_KEY`, `USER_EMAIL`/`USER_PASSWORD` e `DATABASE_URL` em `sensor/src/main.cpp` e em `vision/src/main.cpp`.
   - Compilar e fazer upload com PlatformIO:
     ```bash
     # Nó ambiental (ESP32-S3)
     pio run -d sensor -t upload
     # Nó de visão (ESP32-CAM — requer adaptador USB-TTL, ver docs/wiring_vision.md)
     pio run -d vision -t upload
     ```

4. **Instalar dependências Python:**
   ```bash
   cd processing
   pip install -r requirements.txt
   ```

5. **Iniciar processamento (em terminais separados):**
   ```bash
   python detector.py    # Pipeline YOLO + DeepSORT — pull de imagens, push de ocupação
   python api.py         # API REST (porta 5000) — serve website e app
   ```

6. **Configuração da sala** (`processing/config.py`):
   ```python
   ROOM_TABLES       = 2     # nº de mesas no campo de visão
   CHAIRS_PER_TABLE  = 4     # cadeiras por mesa
   # ROOM_CAPACITY = 8 automaticamente
   ```

7. **Abrir o website:**
   ```bash
   cd website
   python -m http.server 8080
   # Abrir http://localhost:8080
   ```

8. **App Android** (opcional):
   - Abrir `app/` no Android Studio (Koala 2024.1.1+, JDK 17, SDK 34)
   - No emulador, `Config.API_BASE` já aponta para `10.0.2.2:5000`
   - Em telemóvel físico, mudar para o IP do PC na LAN em `app/app/src/main/java/pt/uminho/sa/data/Config.kt`

---

## 🔮 Componente preditivo & Trabalho futuro

A pasta [`processing/ml/`](processing/ml/) contém o esqueleto para análise
preditiva, com comparação de **três métodos** (baseline por hora, Holt-Winters,
LSTM) — ver [`processing/ml/README.md`](processing/ml/README.md).

**No âmbito desta entrega:** previsão de **conforto ambiental** (temperatura,
humidade, qualidade do ar, ruído) a partir do histórico que o Sensor_NODE
escreve em `rooms/<id>/environment/history`. Estas séries são suaves e
periódicas, suficientes para mostrar resultado com poucos dias de dados.

**Deixado como trabalho futuro:**
- **Previsão de ocupação** (`people`/`status`). O scaffold permite-o
  (`forecasting.py --target people`) mas requer **semanas a meses** de
  histórico fiável da sala em operação real — fora do âmbito desta sprint.
- Anomaly detection (LSTM autoencoder).
- Serviço `predictor.py` em loop a escrever `rooms/<id>/predictions/...` no
  Firebase, com painel "próximas 2 h" no website.
- Calibração dos limiares de conforto e do MQ-135 com referência de sonómetro
  e CO₂-meter profissionais.

---

## 👥 Grupo — MIA

| Nome | Nº | Email |
|------|----|-------|
| Luís Miguel Pereira Silva | PG60390 | pg60390@alunos.uminho.pt |
| Pedro Miguel S. A. Urbano dos Reis | PG59908 | pg59908@alunos.uminho.pt |
| Guilherme Lobo Pinto | PG60225 | pg60225@alunos.uminho.pt |
| Pedro Alexandre Silva Gomes | PG60289 | pg60289@alunos.uminho.pt |

---

## 📜 Licença

Este trabalho é de cariz estritamente académico. Universidade do Minho, Escola de Engenharia, Departamento de Informática.
