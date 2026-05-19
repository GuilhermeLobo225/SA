"""
Gera um CSV sintético com histórico ambiental + ocupação,
SEM tocar no Firebase.

Reaproveita os modelos sintéticos de `seed_synthetic.py` (mesma sazonalidade
diária realista, mesmo padrão "biblioteca"), mas escreve direto para
`processing/ml/data/merged.csv` — pronto a ser consumido por `forecasting.py`.

Uso:
    python seed_csv.py                      # 14 dias, sampling 30s
    python seed_csv.py --days 30
    python seed_csv.py --interval 60        # 1 amostra/min (mais leve)
    python seed_csv.py --out caminho.csv    # destino alternativo

O CSV gerado tem as mesmas colunas que `data_export.py merged.csv`:
    timestamp, temperature, humidity, air_quality_raw, light_raw,
    light_digital, noise_db, comfort, air_quality, light, noise, people

Justificação académica: o `data.csv` real só cobre ~7 h e mostra a sala
vazia; é insuficiente para Holt-Winters (>=2 dias) ou LSTM (>=1 semana).
Geramos 14 dias sintéticos para o treino e validação offline. Em produção,
o modelo treinado faz inferência sobre os dados REAIS do Firebase.
"""

import argparse
import csv
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Adiciona ml/ ao path para apanhar synthetic_models, e processing/ para config
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Reaproveita os geradores existentes (mesmas funções usadas pelo
# seed_synthetic.py que escreve no Firebase). Garante coerência entre
# os dados de treino e os dados "seed" de fallback no Firebase.
from synthetic_models import occupancy_at, env_at  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("seed_csv")

DEFAULT_OUT = Path(__file__).parent / "data" / "merged.csv"
COLUMNS = [
    "timestamp", "temperature", "humidity",
    "air_quality_raw", "air_quality",
    "light_raw", "light_digital", "light",
    "noise_db", "noise", "comfort",
    "people",
]


def generate(days: int, interval_s: int) -> list[dict]:
    """Gera os pontos do histórico — espaçamento `interval_s` segundos."""
    end = datetime.now().replace(microsecond=0, second=0)
    start = end - timedelta(days=days)
    step = timedelta(seconds=interval_s)

    rows: list[dict] = []
    ts = start
    while ts <= end:
        ppl = occupancy_at(ts)
        env = env_at(ts, ppl)
        # env já vem com timestamp em ISO; mas queremos formato sem 'T'
        # para bater certo com a saída do data_export.py real (pandas
        # lida bem com ambos, mas convém ser consistente).
        env["timestamp"] = ts.strftime("%Y-%m-%d %H:%M:%S")
        env["people"] = ppl
        rows.append({c: env.get(c) for c in COLUMNS})
        ts += step
    return rows


def write_csv(rows: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    log.info("✓ %d linhas escritas em %s (%.1f KB)",
             len(rows), path, path.stat().st_size / 1024)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--days",     type=int, default=14,
                    help="dias de histórico a gerar (default 14)")
    ap.add_argument("--interval", type=int, default=30,
                    help="intervalo entre amostras, em segundos (default 30)")
    ap.add_argument("--out",      type=Path, default=DEFAULT_OUT,
                    help=f"caminho de saída (default {DEFAULT_OUT})")
    args = ap.parse_args()

    log.info("A gerar %d dia(s) a cada %d s → ~%d pontos…",
             args.days, args.interval,
             args.days * 86400 // args.interval)
    rows = generate(args.days, args.interval)
    write_csv(rows, args.out)


if __name__ == "__main__":
    main()
