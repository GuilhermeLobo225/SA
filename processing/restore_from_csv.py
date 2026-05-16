"""
Restaura dados de `ml/data/environment_history.csv` para o Firebase Sensor.

Útil quando se apagou o histórico por engano e há uma CSV de backup local
(via VSCode Timeline, Windows File History, ou export manual).

Uso:
    python restore_from_csv.py                          # restaura tudo
    python restore_from_csv.py --dry-run                # mostra o que faria
    python restore_from_csv.py --csv outro_backup.csv   # backup alternativo
    python restore_from_csv.py --target occupancy --csv occupancy_history.csv
"""

import argparse
import logging
import math
import sys
from pathlib import Path

import pandas as pd

from config import ROOM_ID
from firebase_sync import FirebaseSync
from firebase_admin import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("restore")

DEFAULT_CSV = Path(__file__).parent / "ml" / "data" / "environment_history.csv"


def env_row_to_payload(row: pd.Series) -> dict:
    """Converte uma linha do CSV de environment para o formato do Firebase."""
    p = {
        "timestamp":       str(row["timestamp"]),
        "temperature":     float(row.get("temperature", 0)),
        "humidity":        float(row.get("humidity",    0)),
        "air_quality_raw": int(row.get("air_quality_raw", 0)),
        "air_quality":     str(row.get("air_quality", "")),
        "light_raw":       int(row.get("light_raw", 0)),
        "light_digital":   int(row.get("light_digital", 0)),
        "light":           str(row.get("light", "")),
        "noise_db":        float(row.get("noise_db", 0)),
        "noise":           str(row.get("noise", "")),
        "comfort":         str(row.get("comfort", "")),
    }
    # NaN → None (Firebase rejeita NaN)
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in p.items()}


def occ_row_to_payload(row: pd.Series) -> dict:
    p = {
        "timestamp":      str(row["timestamp"]),
        "room_id":        ROOM_ID,
        "people":         int(row.get("people", 0)),
        "chairs_total":   int(row.get("chairs_total", 0)),
        "chairs_free":    int(row.get("chairs_free", 0)),
        "capacity":       int(row.get("capacity", 0)),
        "tables":         int(row.get("tables", 0)),
        "occupancy_pct":  float(row.get("occupancy_pct", 0)),
        "status":         str(row.get("status", "livre")),
    }
    return p


def main(csv_path: Path, target: str, dry: bool) -> int:
    if not csv_path.exists():
        log.error("Ficheiro não encontrado: %s", csv_path)
        return 1
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    if df.empty:
        log.error("CSV está vazia.")
        return 2
    log.info("Linhas a restaurar: %d (%s → %s)",
             len(df), df.timestamp.min(), df.timestamp.max())

    sync = FirebaseSync()

    if target == "environment":
        path = f"rooms/{ROOM_ID}/environment/history"
        payloads = [env_row_to_payload(r) for _, r in df.iterrows()]
    elif target == "occupancy":
        path = f"rooms/{ROOM_ID}/occupancy/history"
        payloads = [occ_row_to_payload(r) for _, r in df.iterrows()]
    else:
        log.error("Target inválido: %s (usa 'environment' ou 'occupancy')", target)
        return 3

    if dry:
        log.info("[dry-run] %d itens NÃO escritos em %s", len(payloads), path)
        log.info("Primeiro item: %s", payloads[0])
        log.info("Último item:   %s", payloads[-1])
        return 0

    ref = db.reference(path, app=sync.sensor_app)
    written = 0
    for p in payloads:
        try:
            ref.push().set(p)
            written += 1
            if written % 100 == 0:
                log.info("  ...%d/%d", written, len(payloads))
        except Exception as e:
            log.warning("Falha em %s: %s", p.get("timestamp"), e)

    log.info("Concluído: %d/%d itens escritos em %s", written, len(payloads), path)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv",    type=Path, default=DEFAULT_CSV,
                    help="Path para a CSV de backup")
    ap.add_argument("--target", choices=["environment", "occupancy"], default="environment",
                    help="Qual sub-árvore restaurar")
    ap.add_argument("--dry-run", action="store_true",
                    help="Só mostra o que faria")
    a = ap.parse_args()
    sys.exit(main(a.csv, a.target, a.dry_run))
