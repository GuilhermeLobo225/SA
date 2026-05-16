"""
Comparação de 3 abordagens para prever temperatura (ou outra série) na sala:

  1. Baseline      — média horária histórica (modelo trivial mas
                     surpreendentemente forte em dados periódicos).
  2. Holt-Winters  — suavização exponencial com sazonalidade diária
                     (clássico, sem hyperparams a calibrar).
  3. LSTM          — rede recorrente com janela das últimas leituras +
                     features temporais (hora-do-dia em seno/cosseno).

Métrica primária: MAE em °C (erro absoluto médio).
Métrica secundária: RMSE (penaliza erros grandes).

Uso típico (no relatório):
    cd processing
    python ml/data_export.py --hours 168      # exporta última semana
    python ml/forecasting.py --target temperature --horizon 30

Resultado: tabela de métricas no stdout + gráfico opcional em ml/data/.
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("forecasting")

DATA_DIR = Path(__file__).parent / "data"
RESAMPLE_RULE = "1min"   # uniformiza espaçamento temporal (Sensor envia a cada 30s)


# ============================================================
# Carregamento e preparação
# ============================================================
def load_series(target: str,
                data_from: str | None = None,
                data_to: str | None = None) -> pd.Series:
    csv = DATA_DIR / "merged.csv"
    if not csv.exists():
        raise FileNotFoundError(
            f"{csv} não existe. Corre primeiro: python ml/data_export.py"
        )
    df = pd.read_csv(csv, parse_dates=["timestamp"])
    if target not in df.columns:
        raise KeyError(f"Target '{target}' não está em {list(df.columns)}")

    # Filtro temporal: deixa só treinar/avaliar numa janela específica.
    # Útil quando há dados reais e sintéticos misturados na mesma CSV.
    if data_from:
        df = df[df["timestamp"] >= pd.Timestamp(data_from)]
        log.info("Filtro --data-from: %s", data_from)
    if data_to:
        df = df[df["timestamp"] <  pd.Timestamp(data_to)]
        log.info("Filtro --data-to:   %s", data_to)

    s = df.set_index("timestamp")[target].astype(float)
    # uniformiza espaçamento temporal e preenche pequenos buracos
    s = s.resample(RESAMPLE_RULE).mean().interpolate(method="time", limit=5)
    s = s.dropna()
    log.info("Série '%s': %d pontos, de %s a %s",
             target, len(s), s.index.min(), s.index.max())
    return s


def train_test_split(s: pd.Series, test_hours: float = 6.0):
    cutoff = s.index.max() - pd.Timedelta(hours=test_hours)
    train = s[s.index <= cutoff]
    test  = s[s.index >  cutoff]
    log.info("Train: %d pts | Test: %d pts (~%.1f h)", len(train), len(test), test_hours)
    return train, test


# ============================================================
# Métricas
# ============================================================
def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


# ============================================================
# Modelo 1 — Baseline (média horária)
# ============================================================
def predict_baseline(train: pd.Series, test_index: pd.DatetimeIndex) -> pd.Series:
    hourly = train.groupby(train.index.hour).mean()
    pred = pd.Series([hourly.get(h, train.mean()) for h in test_index.hour], index=test_index)
    return pred


# ============================================================
# Modelo 2 — Holt-Winters (sazonalidade diária)
# ============================================================
def predict_holt_winters(train: pd.Series, test_index: pd.DatetimeIndex) -> pd.Series:
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
    except ImportError:
        log.warning("statsmodels em falta — pip install statsmodels")
        return pd.Series([np.nan] * len(test_index), index=test_index)

    # 1 dia = 1440 minutos (com RESAMPLE_RULE = '1min')
    seasonal_periods = 24 * 60
    if len(train) < 2 * seasonal_periods:
        log.warning("Holt-Winters precisa de >=2 dias de dados; saltando.")
        return pd.Series([np.nan] * len(test_index), index=test_index)

    model = ExponentialSmoothing(
        train.values,
        trend="add",
        seasonal="add",
        seasonal_periods=seasonal_periods,
        initialization_method="estimated",
    ).fit()
    forecast = model.forecast(steps=len(test_index))
    return pd.Series(forecast, index=test_index)


# ============================================================
# Modelo 3 — LSTM
# ============================================================
def predict_lstm(train: pd.Series, test_index: pd.DatetimeIndex,
                  window: int = 60, epochs: int = 15) -> pd.Series:
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        log.warning("torch em falta — pip install torch")
        return pd.Series([np.nan] * len(test_index), index=test_index)

    # Normalização (min-max)
    vmin, vmax = float(train.min()), float(train.max())
    rng = max(1e-6, vmax - vmin)
    scaled = (train.values - vmin) / rng

    # Features de tempo: sin/cos da hora-do-dia
    def time_feats(idx):
        h = idx.hour + idx.minute / 60.0
        ang = 2 * np.pi * h / 24
        return np.stack([np.sin(ang), np.cos(ang)], axis=1)

    train_tf = time_feats(train.index)        # (T, 2)
    # Construir janelas: X = (window, 3), y = próximo valor
    X, y = [], []
    for i in range(window, len(scaled)):
        feats = np.concatenate(
            [scaled[i - window:i].reshape(-1, 1), train_tf[i - window:i]], axis=1
        )
        X.append(feats)
        y.append(scaled[i])
    if not X:
        log.warning("Pouco dados para LSTM (window=%d). Saltando.", window)
        return pd.Series([np.nan] * len(test_index), index=test_index)

    X = torch.tensor(np.array(X), dtype=torch.float32)
    y = torch.tensor(np.array(y), dtype=torch.float32).unsqueeze(1)

    class LSTMNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(input_size=3, hidden_size=32, num_layers=1, batch_first=True)
            self.fc   = nn.Linear(32, 1)

        def forward(self, x):
            o, _ = self.lstm(x)
            return self.fc(o[:, -1, :])

    net = LSTMNet()
    opt = torch.optim.Adam(net.parameters(), lr=1e-2)
    loss_fn = nn.MSELoss()

    net.train()
    for ep in range(epochs):
        opt.zero_grad()
        pred = net(X)
        loss = loss_fn(pred, y)
        loss.backward()
        opt.step()
        if (ep + 1) % 5 == 0:
            log.info("  LSTM epoch %2d/%d loss=%.5f", ep + 1, epochs, loss.item())

    # Forecast recursivo: começa nas últimas `window` amostras de train, prevê
    # 1 passo, junta à janela, prevê o seguinte, etc.
    net.eval()
    history = list(scaled[-window:])
    test_tf = time_feats(test_index)
    preds_scaled = []
    with torch.no_grad():
        for t, tf in enumerate(test_tf):
            seq = np.concatenate(
                [np.array(history[-window:]).reshape(-1, 1),
                 time_feats(pd.date_range(end=test_index[t], periods=window, freq=RESAMPLE_RULE))],
                axis=1,
            )
            inp = torch.tensor(seq[None, ...], dtype=torch.float32)
            p = net(inp).item()
            preds_scaled.append(p)
            history.append(p)

    preds = np.array(preds_scaled) * rng + vmin
    return pd.Series(preds, index=test_index)


# ============================================================
# Runner
# ============================================================
def main(target: str, test_hours: float, plot: bool,
         data_from: str | None = None, data_to: str | None = None):
    s = load_series(target, data_from=data_from, data_to=data_to)
    train, test = train_test_split(s, test_hours=test_hours)

    if len(test) == 0:
        log.error("Sem horizonte de teste — recolhe mais histórico.")
        return 1

    log.info("Modelo 1/3: baseline (média horária)...")
    p1 = predict_baseline(train, test.index)
    log.info("Modelo 2/3: Holt-Winters...")
    p2 = predict_holt_winters(train, test.index)
    log.info("Modelo 3/3: LSTM...")
    p3 = predict_lstm(train, test.index)

    print()
    print("=" * 60)
    print(f"Comparação de previsão  ·  target = {target}")
    print(f"Janela de teste: últimas {test_hours} h ({len(test)} pontos)")
    print("=" * 60)
    print(f"{'Modelo':<24}{'MAE':>10}{'RMSE':>10}")
    print("-" * 60)
    for name, pred in [("Baseline (avg por hora)", p1),
                       ("Holt-Winters",            p2),
                       ("LSTM",                    p3)]:
        if pred.dropna().empty:
            print(f"{name:<24}{'—':>10}{'—':>10}")
            continue
        m = mae(test.values, pred.values)
        r = rmse(test.values, pred.values)
        print(f"{name:<24}{m:>10.3f}{r:>10.3f}")
    print("=" * 60)

    if plot:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            log.warning("matplotlib em falta — pip install matplotlib")
            return 0
        plt.figure(figsize=(12, 4))
        plt.plot(train.index[-len(test) * 3:], train.values[-len(test) * 3:], label="histórico", alpha=0.5)
        plt.plot(test.index, test.values, label="real", color="black", linewidth=2)
        plt.plot(test.index, p1.values, label="baseline", linestyle="--")
        if not p2.dropna().empty:
            plt.plot(test.index, p2.values, label="Holt-Winters", linestyle="--")
        if not p3.dropna().empty:
            plt.plot(test.index, p3.values, label="LSTM", linestyle="--")
        plt.title(f"Previsão de {target}")
        plt.xlabel("Tempo"); plt.ylabel(target)
        plt.legend(); plt.tight_layout()
        out = DATA_DIR / f"forecast_{target}.png"
        plt.savefig(out, dpi=120)
        log.info("Gráfico guardado em %s", out)

    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="temperature",
                    help="Coluna a prever (temperature, humidity, air_quality_raw, noise_db, people, ...)")
    # compute default horizon (hours) from data if available, otherwise 0.5
    try:
        csv = DATA_DIR / "merged.csv"
        if csv.exists():
            df = pd.read_csv(csv, parse_dates=["timestamp"])
            total_h = (df.timestamp.max() - df.timestamp.min()).total_seconds() / 3600.0
            # 10% do dataset, com mínimo de 0.5h e máximo de 2h
            default_h = min(2.0, max(0.5, total_h * 0.10))
        else:
            default_h = 0.5
    except Exception:
        default_h = 0.5
    ap.add_argument("--horizon", type=float, default=default_h,
                    help="Horas de teste no fim da série (default: 0.5 h)")
    ap.add_argument("--plot", action="store_true",
                    help="Gera ml/data/forecast_<target>.png")
    ap.add_argument("--data-from", type=str, default=None,
                    help="ISO date — usar apenas pontos a partir desta data")
    ap.add_argument("--data-to",   type=str, default=None,
                    help="ISO date — usar apenas pontos ANTES desta data (exclusivo)")
    a = ap.parse_args()
    sys.exit(main(a.target, a.horizon, a.plot, a.data_from, a.data_to))
