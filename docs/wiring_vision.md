# Esquema de Ligações — Nó de Visão (Vision_NODE)

## Hardware

- **ESP32-CAM** (AI-Thinker) + módulo OV2640
- **Adaptador USB-TTL** (YP-05, FTDI, CP2102 ou CH340) **com jumper a 5 V**
- **Cabo USB** para o adaptador
- 2 fios fêmea-fêmea (para a ponte IO0↔GND)

> ⚠️ O ESP32-CAM **não tem USB nativo** — o upload é sempre via UART externo.

## Ligações para programação

| YP-05 (USB-TTL) | ESP32-CAM | Notas |
|---|---|---|
| **VCC (5 V)** | 5V | Confirmar jumper do YP-05 em 5 V (NÃO em 3.3 V) |
| **GND** | GND | Massa comum |
| **TXD** | U0R (GPIO 3 / RX) | TX do programador → RX da placa |
| **RXD** | U0T (GPIO 1 / TX) | RX do programador → TX da placa |
| — | **IO0 ↔ GND** | **Ponte só durante o upload** |

## Procedimento de upload

1. Colocar a **ponte IO0–GND** (fio entre GPIO 0 e qualquer pino GND).
2. Ligar o YP-05 ao PC via USB.
3. Premir **RESET** no ESP32-CAM (entra em modo de download).
4. Em PlatformIO, fazer **Upload** (ícone da seta ou `pio run -d vision/Vision_NODE -t upload`).
5. Quando aparecer `Hard resetting via RTS pin` / `Leaving...`:
   - **Remover** a ponte IO0–GND.
   - Premir **RESET** novamente.
6. Abrir o **Serial Monitor** (115200 baud) para ver os logs.

## Ligações em produção (sem programador)

Depois de programado, o ESP32-CAM pode ser alimentado por:

- Adaptador USB-TTL ligado apenas a **VCC (5 V)** e **GND** (TX/RX só servem se quiseres ver os logs).
- Fonte externa 5 V / ≥ 1 A nos pinos **5V** e **GND**.
- **Não** ligar 3.3 V e 5 V em simultâneo.

## Montagem física

- Fixar no teto da sala, com a OV2640 virada para baixo (vista aérea).
- Escolher um ângulo que maximize a cobertura das mesas.
- Garantir cobertura Wi-Fi 2.4 GHz estável no local.
- O **flash LED (GPIO 4)** é desligado por software para não perturbar os utilizadores.

## Resoluções

| Cenário | Frame size | Notas |
|---|---|---|
| Com PSRAM (módulo AI-Thinker padrão) | UXGA 1600×1200 | `BOARD_HAS_PSRAM` ativo |
| Sem PSRAM | SVGA 800×600 | Fallback automático no código |

## Resolução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `Failed to connect / Timed out waiting for packet header` | IO0 não está a GND ou RESET não foi premido | Refazer ponte IO0–GND e premir RESET imediatamente antes do upload |
| `Brownout detector was triggered` | Tensão de 5 V insuficiente (cabo USB fraco) | Usar cabo USB de qualidade ou alimentação externa 5 V / ≥1 A |
| Imagem com cor estranha ou frame errado | PSRAM mal configurada | Confirmar `-D BOARD_HAS_PSRAM` no `platformio.ini` |
| `Camera init failed: 0x20004` | Câmara mal encaixada | Voltar a encaixar o conector flat da OV2640 |
| Reboots constantes | Alimentação fraca | Alimentar com 5 V externo (a saída USB do PC pode não chegar) |
| Upload OK mas não arranca | IO0 ainda ligado a GND | Remover a ponte e premir RESET |
