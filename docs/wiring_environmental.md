# Esquema de Ligações — Nó Ambiental (Sensor_NODE)

## Hardware

- **ESP32-S3 DevKitC-1** (USB nativo, sem programador externo)
- **DHT11** — temperatura + humidade
- **MQ-135** — qualidade do ar
- **LM393 (módulo fotodíodo)** — iluminância
- **MSM261S4030H0** — microfone MEMS I2S
- **LED RGB cátodo comum** + 3 × 220 Ω
- Breadboard + jumpers

## Barramentos de alimentação

> ⚠️ **MSM261** alimenta-se a **3.3 V**. Ligar a 5 V queima-o.
> ⚠️ **MQ-135** alimenta-se a **5 V**. A 3.3 V não aquece o sensor o suficiente.

## Tabela de ligações

| Módulo | Pino do módulo | Pino do ESP32-S3 | Notas |
|---|---|---|---|
| **DHT11** | VCC | 3V3 | módulo com pull-up interno |
| | GND | GND | |
| | DATA | **GPIO 4** | digital, 1-wire |
| **MQ-135** | VCC | **5V (VIN/VBUS)** | precisa de 5 V para aquecer |
| | GND | GND | |
| | AO | **através de divisor de tensão → GPIO 5** | ⚠️ ver secção dedicada abaixo |
| | DO | (não ligar) | só serve para alarme via potenciómetro |
| **LM393 (fotodíodo)** | VCC | 3V3 | |
| | GND | GND | |
| | AO | **GPIO 6** | ADC1_CH5 — intensidade analógica |
| | DO | **GPIO 7** | digital — limiar do potenciómetro |
| **MSM261S4030H0** | VDD / VCC | **3V3** | ⚠️ **NUNCA 5 V** |
| | GND | GND | |
| | L/R (ou SEL) | GND | canal esquerdo |
| | BCLK / CLK / SCK | **GPIO 14** | I2S bit clock |
| | WS / LRCL | **GPIO 15** | I2S word select |
| | DATA / SD / DOUT | **GPIO 13** | I2S data input |
| **LED RGB** | Cátodo (perna longa) | GND | |
| | R | **GPIO 16** via 220 Ω | PWM (LEDC ch 0) |
| | G | **GPIO 17** via 220 Ω | PWM (LEDC ch 1) |
| | B | **GPIO 18** via 220 Ω | PWM (LEDC ch 2) |

## Resumo por GPIO

| GPIO | Função | Tipo | Direção |
|---|---|---|---|
| 4 | DHT11 DATA | Digital | I/O |
| 5 | MQ-135 AO | ADC1_CH4 | Input |
| 6 | LM393 AO | ADC1_CH5 | Input |
| 7 | LM393 DO | Digital | Input |
| 13 | MSM261 DATA | I2S | Input |
| 14 | MSM261 BCLK | I2S | Output |
| 15 | MSM261 WS | I2S | Output |
| 16 | LED R | PWM | Output |
| 17 | LED G | PWM | Output |
| 18 | LED B | PWM | Output |

## Divisor de tensão para o MQ-135 (obrigatório)

A saída AO do MQ-135 pode chegar a **5 V** (alimentado a 5 V), enquanto o ADC do ESP32-S3 só aceita até **3.3 V**. Sem divisor há risco de queimar o pino do ESP32.

**Esquema:**

```
   MQ-135 AO ── R1 (10 kΩ) ──┬── GPIO 5 do ESP32-S3
                             │
                            R2 (10 kΩ)
                             │
                            GND
```

**Cálculo:** V_GPIO = V_AO × R2 / (R1 + R2) = V_AO × 1/2

- AO = 5 V (pior caso) → GPIO = 2.5 V ✅ (com folga até ao limite de 3.3 V)
- AO = 0 V → GPIO = 0 V

**Pares de resistências aceitáveis:**

| R1 | R2 | V_GPIO máx | Notas |
|---|---|---|---|
| **10 kΩ** | **10 kΩ** | **2.50 V** | escolhido — mais seguro, ~76% da gama do ADC |
| 10 kΩ | 20 kΩ | 3.33 V | alternativa — usa toda a gama, no limite |
| 1 kΩ | 2 kΩ | 3.33 V | igual proporção, baixa impedância |

> **Truque:** se só tiveres resistências de 10 kΩ, faz R2 = duas de 10 kΩ em série (= 20 kΩ).

**No código** (`main.cpp`), para converter ADC → volts reais no AO:
```cpp
float v_gpio = analogRead(MQ135_PIN) * (3.3f / 4095.0f);
float v_ao   = v_gpio * 2.0f;   // (R1+R2)/R2 = 20/10 = 2
```

Para o resto dos sensores analógicos (LM393) **não é necessário** divisor porque alimentamos a 3.3 V.

## Notas práticas

- O **MQ-135** precisa de **~24 horas de aquecimento** na 1.ª utilização e **~5–10 min** em cada arranque. Não calibres valores antes desse período.
- O **DHT11** demora ~1 segundo a estabilizar entre leituras. O firmware já lê apenas a cada 30 s.
- Para o microfone MSM261, a qualidade do sinal melhora se o pino L/R estiver mesmo a GND (não deixar a flutuar) e se houver desacoplamento (100 nF entre VDD e GND).
- O **LED RGB cátodo comum** distingue-se do ânodo comum: cátodo → pino comum vai a GND; ânodo → pino comum vai a VCC. Se o LED não acender, podes ter o tipo errado — testa invertendo a perna comum entre GND e 3V3.

## Procedimento de teste por etapas

Recomendado para ir validando passo a passo:

1. Liga **apenas o DHT11** → compila e faz upload → confirma no Serial Monitor que a temperatura e humidade aparecem corretas.
2. Adiciona o **MQ-135** → confirma que `air_quality_raw` muda quando aproximas uma fonte de gás (álcool, isqueiro fechado).
3. Adiciona o **LM393** → confirma que `light_raw` muda ao tapar/iluminar o sensor.
4. Adiciona o **MSM261** → confirma que `noise_db` sobe ao falares perto.
5. Adiciona o **LED RGB** → confirma que muda de cor consoante o conforto.

## Resolução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `[DHT11] Erro de leitura.` (NaN) | Sensor mal ligado ou tipo errado | Confirmar VCC=3.3V e DATA em GPIO 4; usar `DHT11`, não `DHT22` |
| `air_quality_raw` sempre próximo de 0 ou 4095 | MQ-135 não está a receber 5 V | Confirmar VCC ao pino **VIN** ou **5V** |
| `noise_db` sempre próximo de -120 ou ruído branco constante | Pinos I2S trocados ou L/R flutuante | Verificar BCLK/WS/DATA e que L/R está a GND |
| LED RGB sempre apagado | Tipo de LED errado (ânodo comum) | Trocar o pino comum de GND para 3V3 |
| ESP32-S3 reinicia em loop | Consumo total > capacidade USB | Usar fonte de alimentação externa 5 V / 2 A |
| Não aparece como porta COM | Cabo USB só de alimentação | Trocar para cabo USB-C de dados |

## Alimentação final

- Em laboratório/testes: **cabo USB-C** ligado ao PC pela porta **USB** (não a UART) do ESP32-S3 DevKitC-1 — esta é a que tem regulador integrado e é detetada como porta COM.
- Em produção: carregador USB-C 5 V / ≥ 1 A.
