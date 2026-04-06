# Esquema de Ligações — Nó de Visão

## ESP32-CAM (AI-Thinker)

O módulo ESP32-CAM já integra a câmara OV2640. Não são necessárias ligações externas de sensores.

### Programação (via FTDI USB-Serial)

| FTDI | ESP32-CAM |
|------|-----------|
| GND  | GND       |
| VCC (5V) | 5V    |
| TX   | U0R       |
| RX   | U0T       |
| —    | IO0 → GND (durante upload) |

**Procedimento:**
1. Ligar IO0 ao GND
2. Pressionar RESET
3. Fazer upload do firmware
4. Desligar IO0 do GND
5. Pressionar RESET para executar

### Montagem

- Montar no teto da sala, orientada para baixo
- Ângulo que maximize a cobertura das mesas
- Alimentação via cabo USB (5V) ou fonte externa
- Garantir cobertura Wi-Fi estável no local

### Notas

- O flash LED (GPIO 4) é desligado por software para não perturbar os utilizadores
- Resolução máxima: 1600x1200 (UXGA) com PSRAM
- Sem PSRAM: limitado a 800x600 (SVGA)
