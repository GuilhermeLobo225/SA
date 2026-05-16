"""
Injecta histórico SINTÉTICO no Firebase para alimentar a demo do ML.

USO ACADÉMICO APENAS — para que o `forecasting.py` tenha série suficientemente
longa e variada para mostrar o LSTM a ganhar sobre o baseline. Documenta-se no
relatório como "dados simulados com sazonalidade diária realista".

Padrão gerado:
  - Temperatura : ciclo diário 20-26 °C (frio de manhã, pico ~15h)
  - Humidade   : ciclo invertido 40-65 % (alta quando temperatura baixa)
  - Ar (MQ-135): degrada quando há mais pessoas (+ ruído gaussiano)
  - Ruído (dB) : segue ocupação linearmente
  - Ocupação   : padrão "biblioteca" — vazia 0-9h, pico 11-13h e 15-18h,
                 vazia 22-24h, dias úteis vs fim-de-semana diferentes

Uso:
    python ml/seed_synthetic.py --days 14            # 2 semanas de histórico
    python ml/seed_synthetic.py --days 7 --dry-run   # ver o que seria escrito
"""

import argparse
import logging
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ROOM_ID, CHAIRS_PER_TABLE, ROOM_TABLES, ROOM_CAPACITY  # noqa: E402
from firebase_sync import FirebaseSync  # noqa: E402
from firebase_admin import db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("seed_synthetic")

random.seed(42)


# ============================================================
# Modelos sintéticos
# ============================================================
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
    if   7 <= h <= 19: light_raw = int(800 + random.gauss(0, 100))     # claro
    else:              light_raw = int(3000 + random.gauss(0, 200))    # escuro

    # Ruído: sobe com pessoas
    noise_db = round(30 + people * 4 + random.gauss(0, 1.5), 1)

    # Classes
    air_class   = "bom" if air_raw < 800 else ("aceitavel" if air_raw < 1500
                                                else ("necessita_ventilacao" if air_raw < 2500
                                                      else "mau"))
    light_class = "bom" if light_raw < 2500 else ("insuficiente" if light_raw < 3500
                                                   else "escuro")
    noise_class = "baixo" if noise_db < 35 else ("moderado" if noise_db < 55
                                                  else "elevado")

    # Conforto agregado
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
    tables_used = (people + CHAIRS_PER_TABLE - 1) // CHAIRS_PER_TABLE
    if people <= 0:                  status = "livre"
    elif tables_used < ROOM_TABLES:  status = "livre"
    elif people < ROOM_CAPACITY:     status = "parcial"
    else:                            status = "cheio"
    return {
        "timestamp":     ts.isoformat(timespec="seconds"),
        "room_id":       ROOM_ID,
        "people":        people,
        "chairs_total":  ROOM_CAPACITY,
        "chairs_free":   max(0, ROOM_CAPACITY - people),
        "capacity":      ROOM_CAPACITY,
        "tables":        ROOM_TABLES,
        "occupancy_pct": round(people / ROOM_CAPACITY * 100, 1),
        "status":        status,
    }


# ============================================================
# Escrita
# ============================================================
def push_batch(app, path: str, items: list[dict], dry: bool):
    if dry:
        log.info("[dry-run] %d itens NÃO escritos em %s", len(items), path)
        return
    ref = db.reference(path, app=app)
    for it in items:
        ref.push().set(it)


# ============================================================
# Main
# ============================================================
def main(days: int, step_minutes: int, dry: bool) -> int:
    sync = FirebaseSync()
    now = datetime.now().replace(second=0, microsecond=0)
    start = now - timedelta(days=days)

    env_items, occ_items = [], []
    cur = start
    while cur < now:
        people = occupancy_at(cur)
        env_items.append(env_at(cur, people))
        occ_items.append(occ_payload(cur, people))
        cur += timedelta(minutes=step_minutes)

    log.info("Gerados %d pontos ambientais + %d pontos de ocupação", len(env_items), len(occ_items))
    log.info("Intervalo: %s → %s (passo %d min)", start, now, step_minutes)

    push_batch(sync.sensor_app, f"rooms/{ROOM_ID}/environment/history", env_items, dry)
    log.info("Escrito environment/history (%d itens)", 0 if dry else len(env_items))

    push_batch(sync.sensor_app, f"rooms/{ROOM_ID}/occupancy/history", occ_items, dry)
    log.info("Escrito occupancy/history (%d itens)", 0 if dry else len(occ_items))

    log.info("Pronto. Lembrete: documenta no relatório que estes dados são SINTÉTICOS.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="Quantos dias para trás (default: 7)")
    ap.add_argument("--step-minutes", type=int, default=2,
                    help="Passo entre pontos em minutos (default: 2 → 720 pts/dia)")
    ap.add_argument("--dry-run", action="store_true", help="Só simular, sem escrever no Firebase")
    a = ap.parse_args()
    sys.exit(main(a.days, a.step_minutes, a.dry_run))
