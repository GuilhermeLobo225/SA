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
┌──────────────┐    ┌──────────────────────────────────┐
│  Nó de Visão │    │         Nó Ambiental             │
│  ESP32-CAM   │    │  ESP32 DevKit V1                 │
│  OV2640 2MP  │    │  DHT11 │ MQ-135 │ LDR │ KY-038  │
└──────┬───────┘    └───────────┬──────────────────────┘
       │  Wi-Fi / MQTT         │  Wi-Fi
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

### Nó Ambiental (ESP32 DevKit V1)

- **DHT11:** temperatura (±2°C) e humidade relativa (±5%)
- **MQ-135:** qualidade do ar (índice relativo, sensor SnO2)
- **LDR:** iluminância (classificação qualitativa por limiares)
- **KY-038:** nível sonoro (intensidade relativa)
- **LED RGB:** feedback visual de conforto (verde/amarelo/vermelho)
- Leitura a cada 30 segundos, envio para Firebase Realtime Database

### Processamento (Python)

- **YOLOv8** para deteção de pessoas nas imagens
- **DeepSORT** para rastreamento temporal e estabilidade das contagens
- Classificação de ocupação: vazio, disponível, parcialmente ocupado, quase cheio, cheio
- Correlação temporal entre dados visuais e ambientais
- API REST (Flask) para exposição dos dados

### Dashboard Web

- Visualização em tempo real da ocupação e conforto ambiental
- Código de cores por sala (verde → vermelho)
- Atualização automática a cada 15 segundos

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
| ESP32 DevKit V1 | 1 | Microcontrolador |
| DHT11 | 1 | Temperatura e humidade |
| MQ-135 | 1 | Qualidade do ar |
| LDR + Resistência 10kΩ | 1 | Iluminância |
| KY-038 | 1 | Nível sonoro |
| LED RGB (cátodo comum) + 3× 220Ω | 1 | Feedback visual |
| Breadboard + jumpers | — | Prototipagem |

---

## 📏 Limiares de Conforto

| Parâmetro | Sensor | Limiar | Referência |
|---|---|---|---|
| Temperatura | DHT11 | 20–26 °C | ASHRAE 55 |
| Humidade | DHT11 | 30–70% | — |
| Qualidade do ar | MQ-135 | < 400 (analógico) | Calibração empírica |
| Iluminância | LDR | ≥ 500 lux equiv. | EN 12464-1 |
| Ruído | KY-038 | < 35 dB(A) equiv. | OMS |

---

## 📂 Estrutura do Repositório

```
SA/
├── firmware/                          # Código Arduino (ESP32)
│   ├── vision_node/                   #   Nó de visão
│   │   └── vision_node.ino            #     ESP32-CAM: captura + upload
│   └── environmental_node/            #   Nó ambiental
│       └── environmental_node.ino     #     Sensores + LED RGB + Firebase
│
├── processing/                        # Pipeline Python
│   ├── detector.py                    #   YOLOv8 + DeepSORT
│   ├── firebase_sync.py               #   Sincronização Firebase
│   ├── api.py                         #   API REST (Flask)
│   ├── config.py                      #   Configurações
│   └── requirements.txt               #   Dependências Python
│
├── dashboard/                         # Interface web
│   ├── index.html                     #   Página principal
│   ├── style.css                      #   Estilos
│   └── app.js                         #   Lógica de atualização
│
├── docs/                              # Documentação
│   ├── SA2026_paper_6906.pdf          #   Artigo (LNCS)
│   ├── wiring_vision.md               #   Esquema de ligações — nó de visão
│   ├── wiring_environmental.md        #   Esquema de ligações — nó ambiental
│   └── firebase_setup.md              #   Guia de configuração Firebase
│
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🚀 Reprodução

### Pré-requisitos

* **Arduino IDE** ou **PlatformIO** instalado.
* **Python 3.11+** com pip.
* **Conta Firebase** com Realtime Database e Storage ativados.

### Passos

1. **Clonar o repositório:**
   ```bash
   git clone https://github.com/SEU_USER/SA.git
   cd SA
   ```

2. **Configurar Firebase:**
   - Seguir o guia em [`docs/firebase_setup.md`](docs/firebase_setup.md)
   - Colocar `firebase_credentials.json` em `processing/`

3. **Configurar firmware:**
   - Editar `WIFI_SSID`, `WIFI_PASSWORD` e credenciais Firebase em ambos os `.ino`
   - Upload para cada ESP32

4. **Instalar dependências Python:**
   ```bash
   cd processing
   pip install -r requirements.txt
   ```

5. **Iniciar processamento:**
   ```bash
   python detector.py    # Pipeline YOLOv8 + DeepSORT
   python api.py         # API REST (porta 5000)
   ```

6. **Abrir dashboard:**
   ```bash
   cd ../dashboard
   python -m http.server 8080
   # Abrir http://localhost:8080
   ```

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
