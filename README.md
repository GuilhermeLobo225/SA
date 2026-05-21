# 📖 Sala de Estudo Inteligente

![Python](https://img.shields.io/badge/Python-3.11-blue)
![ESP32](https://img.shields.io/badge/MCU-ESP32-teal)
![Kotlin](https://img.shields.io/badge/Android-Kotlin-7F52FF)
![Flask](https://img.shields.io/badge/API-Flask-black)
![YOLOv11](https://img.shields.io/badge/Visão-YOLOv11-00BFC4)
![Firebase](https://img.shields.io/badge/Cloud-Firebase-FFCA28)
![License](https://img.shields.io/badge/License-Academic-lightgrey)

> **Sensorização e Ambiente** | Mestrado em Inteligência Artificial | Universidade do Minho | 2025/26

Sistema distribuído de baixo custo para deteção de ocupação e monitorização de conforto ambiental em salas de estudo universitárias, baseado em dois nós ESP32, visão por computador (YOLOv11) e sensores IoT, com dashboard web, app Android e feedback local por LED.

---

## 🏆 Destaques

* **Pipeline end-to-end real:** dois nós ESP32 → Firebase → YOLOv11 → API REST → website + app Android + LED RGB, com um único contrato de dados partilhado por todos os clientes.
* **Ocupação per-mesa/per-cadeira sem hardcode:** o layout da sala (mesas e cadeiras) é **descoberto automaticamente** pelo YOLO na primeira imagem e persistido — a capacidade deixa de depender de configuração manual.
* **Resistente a *seat hogging*:** uma cadeira conta como ocupada por pessoas **ou** por objetos pessoais (mochila, portátil, livro…), refletindo melhor a disponibilidade real.
* **Previsão de conforto ao vivo:** modelos Holt-Winters treinados offline e servidos pela API (`/history`) alimentam painéis de previsão a 60 min no site e na app.
* **Privacy by design:** as imagens da câmara são apagadas após a inferência e vivem num projeto Firebase isolado do dos sensores ambientais.

> 📄 **Relatório:** [Ver PDF do Relatório](docs/report.pdf) · **Artigo (LNCS):** [Ver PDF do Artigo](docs/article.pdf)

---

## 📊 Arquitetura

O sistema organiza-se em três camadas: sensorização (dois nós ESP32), processamento (visão + agregação + previsão na cloud) e apresentação (dashboard web, app móvel e LED local).

```
Camada de Sensorização
┌──────────────┐    ┌──────────────────────────────────────┐
│  Nó de Visão │    │            Nó Ambiental              │
│  ESP32-CAM   │    │  ESP32-S3 DevKitC-1                  │
│  OV2640 2MP  │    │  DHT11 │ MQ-135 │ LM393 │ MSM261S4030│
└──────┬───────┘    └───────────┬──────────────────────────┘
       │  Wi-Fi                │  Wi-Fi
       ▼                       ▼
┌───────────────────────────────────────────────┐
│            Camada de Processamento            │
│  Firebase Storage + Realtime DB (2 projetos)  │
│  YOLOv11 → atribuição per-mesa → agregação    │
│  forecast_service (Holt-Winters) · API REST   │
└──────────────┬────────────────────────────────┘
               ▼
┌───────────────────────────────────────────────┐
│            Camada de Apresentação             │
│  Dashboard Web │ App Android │ LED RGB local  │
└───────────────────────────────────────────────┘
```

---

## ⚙️ Implementações

### Nó de Visão (ESP32-CAM)

- Captura de imagem periódica (≈30 s) via OV2640 (2 MP)
- Transmissão para Firebase Storage via Wi-Fi (projeto **Vision**)
- Montagem no teto com orientação cenital (aérea)
- Eliminação automática das imagens após inferência quando `DELETE_AFTER_INFERENCE=True` (privacy by design)

### Nó Ambiental (ESP32-S3 DevKitC-1)

- **DHT11:** temperatura (±2 °C) e humidade relativa (±5%)
- **MQ-135:** qualidade do ar (índice relativo, sensor SnO₂) — ADC 12-bit
- **LM393 (módulo fotodíodo):** iluminância — saída analógica (intensidade) + saída digital (limiar)
- **MSM261S4030H0:** microfone MEMS digital I2S de 24 bits para nível de ruído (RMS / dB relativo)
- **LED RGB:** feedback visual de conforto/ocupação (verde / amarelo / vermelho)
- Leitura periódica (≈30 s) e envio para o Realtime Database do projeto **Sensor**

### Processamento — Visão e Ocupação (Python)

- **YOLOv11** (`yolo11x.pt`, extra-large) para deteção de pessoas e objetos nas imagens. O *tracking* temporal (DeepSORT) foi **removido**: a captura a 30 s é demasiado esparsa para o tracking trazer benefício, pelo que se usa contagem direta por frame, mais responsiva.
- **Auto-descoberta de layout** (`layout_discovery.py`): na primeira imagem (sala assumida vazia) o YOLO identifica mesas e cadeiras, e a estrutura é persistida em `rooms/<id>/layout` (coordenadas normalizadas [0..1]). Como a câmara é estática, corre uma vez e basta. `ROOM_TABLE_POSITIONS` em `config.py` funciona como *override* manual.
- **Atribuição per-mesa:** cada deteção é associada à mesa mais próxima pela *bottom-center* da bounding box; deteções fora do campo útil são descartadas.
- **Resistência a *seat hogging*:** uma cadeira é marcada como ocupada por uma **pessoa** ou por **objetos** sobre a mesa (mochila, mala, portátil, livro, garrafa). Telemóveis são detetados mas **não** contam para a ocupação (em ângulo cenital são indistinguíveis de cabos/estojos).
- **Capacidade:** vem do **layout descoberto**; as constantes `ROOM_TABLES × CHAIRS_PER_TABLE` em `config.py` são apenas *fallback* (boot inicial / dados sintéticos).
- **Dois níveis de classificação de ocupação:**
  - **3 estados** internos (`livre` / `parcial` / `cheio`) — consumidos pelo firmware do LED
  - **5 estados** públicos (`vazio` / `disponivel` / `parcialmente_ocupado` / `quase_cheio` / `cheio`) — derivados na API a partir da percentagem, para os badges do website e da app
- **API REST (Flask)** com contrato unificado, mapeando o ID interno da sala (`sala_b1_piso2`) para o ID público da biblioteca (`bg`).

### Processamento — Previsão de conforto (Python)

- `forecast_service.py` serve o endpoint `/history`: tenta primeiro um **modelo Holt-Winters persistido** (`ml/models/<target>.pkl`), caindo para refit online (Holt-Winters → suavização exponencial → *naive*) se não houver checkpoint.
- A pasta [`processing/ml/`](processing/ml/) treina e compara três abordagens (Baseline horário, Holt-Winters, LSTM) — ver [`processing/ml/README.md`](processing/ml/README.md).

### Dashboard Web e App Móvel

Ambos os clientes consomem o **mesmo endpoint REST** servido por `processing/api.py` e partilham os mesmos ficheiros estáticos (`libraries.json`, `books.csv`).

- **Website** (`website/`): HTML + JS *vanilla*, planta da sala em SVG (a partir do layout descoberto), polling a cada 15 s, gráfico de histórico + previsão, e *fallback* para mock quando a API está offline.
- **App Android** (`app/`): Kotlin nativo, mesma planta em `Canvas` (`PlantaView`), `ApiClient` com `HttpURLConnection` + `org.json`, gráfico de histórico/previsão (`HistoryChartView`), geofence de chegada à BG e alertas configuráveis em segundo plano (`WorkManager`). Detalhes em [`app/README.md`](app/README.md).
- Código de cores alinhado entre clientes: 🟢 livre, 🟡 parcial, 🔴 cheio

---

## 📈 Componente Preditiva — Resultados

Previsão de **conforto ambiental** a 60 min. Os checkpoints servidos pela API são modelos **Holt-Winters** com sazonalidade diária. As métricas abaixo são as guardadas em `ml/models/*.meta.json`, em *holdout* das últimas 5 h.

| Target | Modelo | MAE | RMSE |
|--------|--------|:---:|:----:|
| Temperatura (°C) | Holt-Winters | 0.28 | 0.32 |
| Humidade (%) | Holt-Winters | 1.57 | 1.90 |
| Qualidade do ar (ADC MQ-135) | Holt-Winters | 557.2 | 602.7 |
| Ruído (dB rel.) | Holt-Winters | 8.65 | 9.69 |

> ⚠️ **Nota de transparência:** o histórico real recolhido cobre apenas algumas horas (insuficiente para Holt-Winters, que precisa de ≥2 ciclos diários, ou LSTM, ≥1 semana). Para demonstrar a componente preditiva, estes modelos foram treinados sobre **14 dias de dados sintéticos** com sazonalidade realista (`ml/seed_csv.py`). O `forecasting.py` compara Baseline / Holt-Winters / LSTM nas mesmas séries. Ver [`processing/ml/README.md`](processing/ml/README.md).

---

## 🔌 Contrato da API REST

`processing/api.py` corre na porta 5000 (`http://localhost:5000` no PC, `http://10.0.2.2:5000` no emulador Android).

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/health` | Sanidade do serviço |
| GET | `/api/rooms` | Lista de salas com sensorização ativa |
| GET | `/api/rooms/{id}` | Snapshot completo (ocupação + ambiente) |
| GET | `/api/rooms/{id}/occupancy` | Apenas ocupação (inclui `table_states`) |
| GET | `/api/rooms/{id}/environment` | Apenas dados ambientais |
| GET | `/api/rooms/{id}/layout` | Layout descoberto (mesas/cadeiras, coords [0..1]) |
| DELETE | `/api/rooms/{id}/layout` | Apaga o layout → força redescoberta na próxima imagem |
| GET | `/api/rooms/{id}/history` | Série recente + previsão curta (`target`, `hours`, `forecast_minutes`) |
| GET | `/api/rooms/{id}/stats` | Agregados (pico/média de ocupação, min/max ambiente) |

`{id}` aceita o ID público (`bg`) ou o interno (`sala_b1_piso2`).

Forma da resposta de `/api/rooms/{id}`:

```jsonc
{
  "room_id":        "bg",
  "timestamp":      "2026-05-15T16:24:01",

  // Ocupação
  "count":          1,                       // nº de LUGARES ocupados (= chairs_occupied)
  "people":         1,                       // nº de pessoas físicas detetadas
  "capacity":       8,
  "tables":         2,
  "chairs_total":   8,
  "chairs_free":    7,
  "chairs_occupied":1,
  "occupancy_pct":  12.5,
  "status":         "disponivel",            // 5 níveis para UI
  "status_simple":  "livre",                 // 3 níveis para LED
  "chair_states":   [ /* {id, occupied, ...} por cadeira */ ],
  "table_states":   [ /* {id, capacity, occupied, free, people, objects, status} */ ],

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

> Nota: `count` representa **lugares ocupados** (= `chairs_occupied`), não pessoas — para a UI mostrar "1/8 ocupados" quando alguém deixa o portátil em pausa. O `people` mantém a contagem de pessoas físicas.

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

> O microfone MSM261S4030H0 alimenta-se a 3.3 V e tem o pino **SEL ligado a GND** (canal esquerdo). Esquemas completos em `sensor/kicad/`, `vision/kicad/` e nos PNGs `*-scheme.png`.

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
├── sensor/                          # Nó Ambiental — firmware ESP32-S3 (PlatformIO)
│   ├── platformio.ini               #   Configuração do projeto + libs
│   ├── src/main.cpp                 #   DHT11 + MQ-135 + LM393 + I2S + LED RGB
│   ├── kicad/                       #   Esquemático + PCB (KiCad)
│   ├── sensor-scheme.png            #   Esquema de ligações
│   └── include/  lib/  test/
│
├── vision/                          # Nó de Visão — firmware ESP32-CAM (PlatformIO)
│   ├── platformio.ini
│   ├── src/main.cpp                 #   OV2640: captura + upload Storage
│   ├── kicad/
│   ├── vision-scheme.png
│   └── include/  lib/  test/
│
├── processing/                      # Pipeline Python
│   ├── detector.py                  #   YOLOv11 + atribuição per-mesa + push de ocupação
│   ├── layout_discovery.py          #   Auto-descoberta de mesas/cadeiras (1ª frame)
│   ├── firebase_sync.py             #   Sincronização Firebase (2 projetos)
│   ├── api.py                       #   API REST (Flask) — contrato unificado
│   ├── forecast_service.py          #   Previsão curta (checkpoint → HW → SES → naive)
│   ├── config.py                    #   Configurações (sala, YOLO, thresholds)
│   ├── requirements.txt
│   ├── reset_history.py             #   Utilitários de manutenção do RTDB
│   ├── reset_layout.py
│   ├── restore_from_csv.py
│   ├── test_firebase.py
│   ├── ml/                          #   Componente preditiva — ver ml/README.md
│   │   ├── forecasting.py           #     Comparação Baseline / Holt-Winters / LSTM
│   │   ├── data_export.py           #     Exporta histórico do Firebase → CSV
│   │   ├── seed_csv.py              #     Gera CSV sintético (treino offline)
│   │   ├── seed_synthetic.py        #     Injeta dados sintéticos no Firebase
│   │   ├── synthetic_models.py      #     Modelos de sazonalidade partilhados
│   │   ├── models/                  #     Checkpoints treinados (.pkl + .meta.json)
│   │   └── requirements-ml.txt
│   ├── secrets/                     #   ⚠️ NÃO versionar (está no .gitignore)
│   │   ├── vision-credentials.json  #     Service account do projeto Vision
│   │   └── sensor-credentials.json  #     Service account do projeto Sensor
│   └── temp_images/_annotated/      #   Frames com bounding boxes (debug, gitignored)
│
├── website/                         # Dashboard web (HTML + CSS + JS vanilla)
│   ├── index.html  biblioteca.html  sobre.html
│   ├── js/                          #   api.js, bibliotecas.js, biblioteca-detalhe.js, mobile-nav.js
│   ├── data/                        #   libraries.json, books.csv
│   └── style.css  logo.png
│
├── app/                             # App Android (Kotlin) — ver app/README.md
│   └── app/src/main/java/pt/uminho/sa/{data,geofence,alerts,ui}/
│
├── docs/                            # Documentação
│   ├── SA2026_report_6906.pdf       #   Relatório (LNCS)
│   ├── SA2026_paper_6906.pdf        #   Artigo (LNCS)
│   ├── setup_firebase.md            #   Guia de configuração Firebase (2 projetos)
│   ├── wiring_environmental.md      #   Esquema de ligações — nó ambiental
│   └── wiring_vision.md             #   Esquema de ligações — nó de visão
│
├── .gitignore
└── README.md
```

---

## 🚀 Reprodução

### Pré-requisitos

* **PlatformIO** (VSCode + extensão PlatformIO IDE).
* **Python 3.11+** com pip.
* **Conta Firebase** com Realtime Database e Storage ativados (dois projetos).

### Passos

1. **Clonar o repositório:**
   ```bash
   git clone https://github.com/SEU_USER/SA.git
   cd SA
   ```

2. **Configurar Firebase (dois projetos):**
   - Seguir o guia em [`docs/setup_firebase.md`](docs/setup_firebase.md)
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
   python detector.py    # Pipeline YOLO — pull de imagens, auto-descoberta de layout, push de ocupação
   python api.py         # API REST (porta 5000) — serve website e app
   ```

6. **Configuração da sala** (`processing/config.py`, apenas *fallback* — em produção a capacidade vem do layout descoberto):
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

## 🔮 Trabalho Futuro

**Já implementado nesta entrega:** previsão de **conforto ambiental** (temperatura, humidade, qualidade do ar, ruído) servida ao vivo pela API e mostrada no site e na app.

**Deixado como trabalho futuro:**
- **Previsão de ocupação** (`people` / `status`). O *scaffold* já o permite (`forecasting.py --target people`), mas a ocupação é muito mais errática que o ambiente e depende de fatores externos (horários, exames, época letiva); um modelo defensável exige **semanas a meses** de histórico real.
- Anomaly detection (LSTM autoencoder).
- Serviço `predictor.py` em loop a escrever `rooms/<id>/predictions/...` no Firebase, com painel "próximas 2 h" no website.
- Calibração dos limiares de conforto e do MQ-135 com referência de sonómetro e CO₂-meter profissionais.

---

## 🎥 Apresentação

Apresentação pública do trabalho: **28 de maio de 2026** (15 min), durante o período de aulas.

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
