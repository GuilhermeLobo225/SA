# Esquema de Ligações — Nó Ambiental

## ESP32 DevKit V1

### DHT11 (Temperatura e Humidade)

| DHT11 | ESP32  |
|-------|--------|
| VCC   | 3.3V   |
| DATA  | GPIO 4 |
| GND   | GND    |

> Nota: Usar resistência pull-up de 10kΩ entre DATA e VCC (alguns módulos já a incluem).

### MQ-135 (Qualidade do Ar)

| MQ-135 | ESP32    |
|--------|----------|
| VCC    | 5V (Vin) |
| GND    | GND      |
| AOUT   | GPIO 34  |

> **Importante:** O MQ-135 necessita de 5V e de um período de aquecimento (~24h na primeira utilização, ~5 min nas seguintes). O pino GPIO 34 é input-only, adequado para leitura analógica.

### LDR (Iluminância)

Divisor de tensão com resistência de 10kΩ:

```
3.3V ── LDR ──┬── GPIO 35
              │
             10kΩ
              │
             GND
```

### KY-038 (Nível Sonoro)

| KY-038 | ESP32    |
|--------|----------|
| VCC    | 3.3V     |
| GND    | GND      |
| A0     | GPIO 32  |
| D0     | GPIO 33  |

> O potenciómetro no módulo KY-038 ajusta o limiar da saída digital (D0).

### LED RGB (Cátodo Comum)

| LED RGB  | ESP32 (via 220Ω) |
|----------|-------------------|
| R        | GPIO 25           |
| G        | GPIO 26           |
| B        | GPIO 27           |
| Cátodo   | GND               |

### Resumo de Pinos

| GPIO | Função          | Tipo     |
|------|-----------------|----------|
| 4    | DHT11 DATA      | Digital  |
| 34   | MQ-135 AOUT     | ADC      |
| 35   | LDR             | ADC      |
| 32   | KY-038 A0       | ADC      |
| 33   | KY-038 D0       | Digital  |
| 25   | LED R           | PWM      |
| 26   | LED G           | PWM      |
| 27   | LED B           | PWM      |

### Alimentação

- ESP32 DevKit: USB (5V) ou fonte externa
- MQ-135 requer 5V (usar pino Vin do ESP32)
- Restantes sensores: 3.3V
