"""
Exporta o histórico ambiental + ocupação do Firebase Sensor para CSV.
Pronto para ser carregado em pandas e dado a baseline / Prophet / LSTM.

Uso:
    python ml/data_export.py                      # exporta tudo até agora
    python ml/data_export.py --hours 168          # só os últimos 7 dias

Saídas em ml/data/:
    environment_history.csv   — colunas: timestamp, temperature, humidity,
                                 air_quality_raw, light_raw, noise_db, comfort
    occupancy_history.csv     — colunas: timestamp, people, status,
                                 occupancy_pct
    merged.csv                — junção alinhada por timestamp (1 linha por
                                 leitura ambiental, com a contagem de pessoas
                                 mais recente disponível)
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Permite correr este script tanto de processing/ como de processing/ml/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ROOM_ID            # noqa: E402
from firebase_sync import FirebaseSync  # noqa: E402
from firebase_admin import db          # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("data_export")

OUT_DIR = Path(__file__).parent / "data"


def fetch_history(sync: FirebaseSync, kind: str) -> dict:
    """`kind` ∈ {'environment', 'occupancy'} — devolve o nó /history bruto."""
    path = f"rooms/{ROOM_ID}/{kind}/history"
    ref = db.reference(path, app=sync.sensor_app)
    raw = ref.get() or {}
    log.info("  %s: %d registos brutos", kind, len(raw))
    return raw


def to_dataframe(raw: dict, kind: str) -> pd.DataFrame:
    """Converte o dict {push_id: leitura, ...} num DataFrame ordenado por tempo."""
    if not raw:
        return pd.DataFrame()
    rows = list(raw.values())
    df = pd.DataFrame(rows)
    if "timestamp" not in df.columns:
        log.warning("[%s] sem coluna 'timestamp'.", kind)
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def filter_recent(df: pd.DataFrame, hours: int | None) -> pd.DataFrame:
    if not hours or df.empty:
        return df
    cutoff = pd.Timestamp.now() - pd.Timedelta(hours=hours)
    return df[df["timestamp"] >= cutoff].reset_index(drop=True)


def merge_environment_with_occupancy(env: pd.DataFrame, occ: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada leitura ambiental, encontra a contagem de pessoas mais recente
    (asof merge). Resultado: dataset alinhado para treinar previsão de conforto
    com a ocupação como feature.
    """
    if env.empty:
        return env
    if occ.empty:
        out = env.copy()
        out["people"] = 0
        out["occupancy_status"] = None
        return out

    env_s = env.sort_values("timestamp")
    occ_s = occ.sort_values("timestamp")
    merged = pd.merge_asof(
        env_s,
        occ_s[["timestamp", "people", "status"]].rename(columns={"status": "occupancy_status"}),
        on="timestamp",
        direction="backward",
        tolerance=pd.Timedelta(minutes=2),
    )
    merged["people"] = merged["people"].fillna(0).astype(int)
    return merged


def main(hours: int | None) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info("A inicializar Firebase...")
    sync = FirebaseSync()

    log.info("A puxar histórico de %s...", ROOM_ID)
    env_raw = fetch_history(sync, "environment")
    occ_raw = fetch_history(sync, "occupancy")

    env = filter_recent(to_dataframe(env_raw, "environment"), hours)
    occ = filter_recent(to_dataframe(occ_raw, "occupancy"),   hours)

    if env.empty:
        log.warning("Sem dados ambientais — o Sensor_NODE já enviou alguma coisa?")
    if occ.empty:
        log.warning("Sem dados de ocupação — o detector.py correu durante algum tempo?")

    # Guardar
    env_out = OUT_DIR / "environment_history.csv"
    occ_out = OUT_DIR / "occupancy_history.csv"
    merged_out = OUT_DIR / "merged.csv"

    env.to_csv(env_out, index=False)
    occ.to_csv(occ_out, index=False)
    merged = merge_environment_with_occupancy(env, occ)
    merged.to_csv(merged_out, index=False)

    log.info("Escritos:")
    log.info("  %s  (%d linhas)", env_out, len(env))
    log.info("  %s  (%d linhas)", occ_out, len(occ))
    log.info("  %s  (%d linhas)", merged_out, len(merged))

    if not env.empty:
        log.info("Intervalo temporal: %s → %s",
                 env["timestamp"].min(), env["timestamp"].max())

    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=None,
                    help="Filtrar apenas as últimas N horas (default: tudo)")
    args = ap.parse_args()
    sys.exit(main(args.hours))
