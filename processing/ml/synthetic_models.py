"""
Modelos sintéticos puros (sem dependências de Firebase).

Extraídos de `seed_synthetic.py` para serem partilhados entre:
  - `seed_synthetic.py`  → injeta no Firebase
  - `seed_csv.py`        → escreve direto para CSV (treino offline de ML)

Funções:
  - `occupancy_at(ts)`           : nº de pessoas esperado a um dado timestamp.
  - `env_at(ts, people)`         : leitura ambiental coerente com hora + ocupação.
  - `occ_payload(ts, people)`    : payload de ocupação no formato Firebase.

Padrão temporal:
  - Temperatura : ciclo diário 20-26 °C (frio de manhã, pico ~15h)
  - Humidade   : ciclo invertido 40-65 % (alta quando temperatura baixa)
  - Ar (MQ-135): degrada quando há mais pessoas (+ ruído gaussiano)
  - Ruído (dB) : segue ocupação linearmente
  - Ocupação   : padrão "biblioteca" — vazia 0-9h, pico 11-13h e 15-18h,
                 vazia 22-24h, dias úteis vs fim-de-semana diferentes

Determinístico se `random.seed(...)` for chamado antes — útil para
reprodutibilidade entre runs.
"""

import math
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (  # noqa: E402
    ROOM_ID, CHAIRS_PER_TABLE, ROOM_TABLES, ROOM_CAPACITY,
)


def occupancy_at(ts: datetime) -> int:
    """Devolve nº de pessoas esperadas naquele timestamp, [0, ROOM_CAPACITY]."""
    h = ts.hour + ts.minute / 60.0
    is_weekend = ts.weekday() >= 5

    if is_weekend:
        base = 1 if 10 <= h <= 19 else 0
    else:
        if   h < 8:                base = 0
        elif h < 11:               base = 1
        elif h < 13:               base = ROOM_CAPACITY      # pico almoço-manhã
        elif h < 14:               base = ROOM_CAPACITY // 2
        elif h < 18:               base = ROOM_CAPACITY - 1  # quase cheio
        elif h < 20:               base = 2
        else:                      base = 0

    noise = random.choice([-1, 0, 0, 0, 1])
    return max(0, min(ROOM_CAPACITY, base + noise))


def env_at(ts: datetime, people: int) -> dict:
    """Devolve uma leitura ambiental sintética coerente com a hora e ocupação."""
    h = ts.hour + ts.minute / 60.0

    # Temperatura: senoide diária 20 ↔ 26 com pico às 15h
    temp_base = 23 + 3 * math.sin(2 * math.pi * (h - 9) / 24)
    temperature = round(temp_base + random.gauss(0, 0.2) + people * 0.15, 1)

    # Humidade: anti-correlacionada com a temperatura, ~40-65%
    humidity = round(55 - (temperature - 23) * 3 + random.gauss(0, 2), 1)
    humidity = max(20.0, min(80.0, humidity))

    # Ar (MQ-135): valor base baixo; degrada com pessoas
    air_raw = int(400 + people * 200 + random.gauss(0, 50))
    air_raw = max(100, min(3500, air_raw))

    # Luz: ADC LM393 (menor=mais luz). Mais luz natural durante o dia.
    if 7 <= h <= 19:
        light_raw = int(800 + random.gauss(0, 100))
    else:
        light_raw = int(3000 + random.gauss(0, 200))

    # Ruído: sobe com pessoas
    noise_db = round(30 + people * 4 + random.gauss(0, 1.5), 1)

    air_class = ("bom" if air_raw < 800
                 else ("aceitavel" if air_raw < 1500
                       else ("necessita_ventilacao" if air_raw < 2500
                             else "mau")))
    light_class = ("bom" if light_raw < 2500
                   else ("insuficiente" if light_raw < 3500 else "escuro"))
    noise_class = ("baixo" if noise_db < 35
                   else ("moderado" if noise_db < 55 else "elevado"))

    bads = sum([
        temperature < 20 or temperature > 26,
        humidity < 30 or humidity > 70,
        air_class in ("mau", "necessita_ventilacao"),
        noise_class == "elevado",
        light_class in ("insuficiente", "escuro"),
    ])
    comfort = "bom" if bads == 0 else ("moderado" if bads <= 2 else "mau")

    return {
        "timestamp":       ts.isoformat(timespec="seconds"),
        "temperature":     temperature,
        "humidity":        humidity,
        "air_quality_raw": air_raw,
        "air_quality":     air_class,
        "light_raw":       light_raw,
        "light_digital":   0 if light_raw < 1500 else 1,
        "light":           light_class,
        "noise_db":        noise_db,
        "noise":           noise_class,
        "comfort":         comfort,
    }


def occ_payload(ts: datetime, people: int) -> dict:
    """Payload de ocupação no formato que o Firebase espera (compat com detector)."""
    tables_used = (people + CHAIRS_PER_TABLE - 1) // CHAIRS_PER_TABLE
    if people <= 0:                  status = "livre"
    elif tables_used < ROOM_TABLES:  status = "livre"
    elif people < ROOM_CAPACITY:     status = "parcial"
    else:                            status = "cheio"

    chair_states, table_states = [], []
    chair_idx = 0
    remaining = people
    for t_i in range(ROOM_TABLES):
        local_occ = min(CHAIRS_PER_TABLE, remaining)
        remaining -= local_occ
        for c_i in range(CHAIRS_PER_TABLE):
            chair_idx += 1
            cid = f"C{chair_idx}"
            chair_states.append({
                "id": cid, "occupied": c_i < local_occ,
                "by": "person" if c_i < local_occ else None,
            })
        table_states.append({
            "id": f"T{t_i + 1}",
            "chairs_total":    CHAIRS_PER_TABLE,
            "chairs_occupied": local_occ,
            "chairs_free":     CHAIRS_PER_TABLE - local_occ,
        })

    return {
        "timestamp":        ts.isoformat(timespec="seconds"),
        "room_id":          ROOM_ID,
        "people":           people,
        "chairs_total":     ROOM_CAPACITY,
        "chairs_free":      max(0, ROOM_CAPACITY - people),
        "chairs_occupied":  people,
        "capacity":         ROOM_CAPACITY,
        "tables":           ROOM_TABLES,
        "occupancy_pct":    round(people / ROOM_CAPACITY * 100, 1),
        "status":           status,
        "chair_states":     chair_states,
        "table_states":     table_states,
    }
