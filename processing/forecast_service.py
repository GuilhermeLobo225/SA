"""
Serviço de forecasting de curto-prazo, usado pelo endpoint /api/rooms/<id>/history.

Estratégia (por ordem de preferência):

  1. **Modelo persistido**  — se `target` for dado e existir um checkpoint
     pré-treinado em `ml/models/<target>.pkl` (Holt-Winters serializado via
     statsmodels), carrega-o uma única vez e usa-o para forecast. É o caminho
     normal em produção depois de correr `python ml/forecasting.py --target all
     --save`. A previsão é tirada no espaçamento do treino (5 min) e depois
     reindexada para minutos com interpolação linear; é aplicado um "level
     shift" para alinhar o primeiro valor com a última observação real (evita
     descontinuidade visual no gráfico).

  2. **Holt-Winters online**  — refit por chamada se houver >=2 dias de
     histórico. Mais pesado mas evita treino prévio.

  3. **Simple Exponential Smoothing**  — para histórico curto (>=15 min).

  4. **Naive**  — fallback honesto: linha plana com o último valor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("forecast")

ModelName = Literal["persisted", "holt-winters", "exponential", "naive"]
SEASONAL_PERIODS_DAILY = 24 * 60      # 1 dia em minutos (resample a 1 min)
MODELS_DIR = Path(__file__).parent / "ml" / "models"

# Cache em memória: target -> HoltWintersResults | None (None = tentei e
# falhou). Evita re-carregar pickle a cada pedido HTTP.
_MODEL_CACHE: dict[str, object | None] = {}


def _resample_to_minutes(s: pd.Series) -> pd.Series:
    """Uniformiza a série para 1 ponto por minuto, interpolando pequenos buracos."""
    if s.empty:
        return s
    s = s.resample("1min").mean()
    s = s.interpolate(method="time", limit=10)
    s = s.dropna()
    return s


# ============================================================
# Modelo persistido (carregado de disco, treinado offline)
# ============================================================
def _load_persisted_model(target: str):
    """
    Devolve o `HoltWintersResults` persistido em `ml/models/<target>.pkl`.
    Resultado em cache. Devolve None se ficheiro não existir ou se o load
    falhar (qualquer erro é silenciado para não partir a API).
    """
    if target in _MODEL_CACHE:
        return _MODEL_CACHE[target]

    pkl = MODELS_DIR / f"{target}.pkl"
    if not pkl.exists():
        log.info("Sem checkpoint para target '%s' (%s).", target, pkl)
        _MODEL_CACHE[target] = None
        return None

    try:
        # `HoltWintersResults.load()` foi removido em statsmodels recentes
        # (o `.save()` no fit-results usa pickle por baixo). Carregamos
        # com pickle padrão — mais portável entre versões.
        import pickle
        with open(pkl, "rb") as f:
            model = pickle.load(f)
        log.info("Checkpoint carregado: %s (%.1f KB)", pkl,
                 pkl.stat().st_size / 1024)
        _MODEL_CACHE[target] = model
        return model
    except Exception as e:
        log.warning("Falha a carregar checkpoint %s: %s", pkl, e)
        _MODEL_CACHE[target] = None
        return None


def _persisted_forecast(
    target: str,
    history: pd.Series,
    steps_minutes: int,
) -> np.ndarray | None:
    """
    Faz forecast usando o modelo treinado offline.

    O modelo foi treinado com espaçamento de 5 min (ver forecasting.py
    RESAMPLE_RULE), por isso pedimos `steps_5min = ceil(steps_minutes/5)`
    e depois fazemos upsample linear para os `steps_minutes` pontos finais.

    Aplica level-shift: alinha o primeiro valor do forecast com a última
    observação da `history`. Sem isto, o gráfico mostraria um salto se o
    nível atual da sala estiver acima/abaixo da média do treino.
    """
    model = _load_persisted_model(target)
    if model is None:
        return None

    steps_5min = max(1, (steps_minutes + 4) // 5)
    try:
        raw_5min = np.asarray(model.forecast(steps=steps_5min), dtype=float)
    except Exception as e:
        log.warning("Forecast do checkpoint falhou para '%s': %s", target, e)
        return None

    # Upsample para 1 min via interpolação linear (5 min → 1 min).
    # np.interp é suficiente: x_known em [0, 5, 10, ...], y_known = raw_5min.
    x_known = np.arange(steps_5min) * 5.0
    x_target = np.arange(steps_minutes, dtype=float)
    raw_1min = np.interp(x_target, x_known, raw_5min)

    # Level shift: alinha o primeiro valor à última observação real.
    # Não calibra a tendência — só remove o offset DC.
    if not history.empty:
        try:
            last_real = float(history.iloc[-1])
            shift = last_real - float(raw_1min[0])
            raw_1min = raw_1min + shift
        except Exception:
            pass

    return raw_1min


# ============================================================
# Fluxo legacy — online fit (refit por chamada)
# ============================================================
def _hw_forecast(s: pd.Series, steps: int) -> np.ndarray | None:
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
    except ImportError:
        log.warning("statsmodels não instalado — sem Holt-Winters")
        return None

    if len(s) < 2 * SEASONAL_PERIODS_DAILY:
        return None
    try:
        model = ExponentialSmoothing(
            s.values,
            trend="add",
            seasonal="add",
            seasonal_periods=SEASONAL_PERIODS_DAILY,
            initialization_method="estimated",
        ).fit()
        return np.asarray(model.forecast(steps=steps))
    except Exception as e:
        log.warning("Holt-Winters falhou: %s", e)
        return None


def _ses_forecast(s: pd.Series, steps: int) -> np.ndarray | None:
    try:
        from statsmodels.tsa.holtwinters import SimpleExpSmoothing
    except ImportError:
        return None

    if len(s) < 15:
        return None
    try:
        model = SimpleExpSmoothing(s.values, initialization_method="estimated").fit()
        base = float(model.forecast(steps=1)[0])
        recent_trend = float(np.mean(np.diff(s.values[-30:]))) if len(s) >= 30 else 0.0
        return np.array([base + recent_trend * (i + 1) for i in range(steps)])
    except Exception as e:
        log.warning("SES falhou: %s", e)
        return None


def _naive_forecast(s: pd.Series, steps: int) -> np.ndarray:
    last = float(s.iloc[-1]) if not s.empty else 0.0
    return np.full(steps, last, dtype=float)


# ============================================================
# Entrypoint usado pela API
# ============================================================
def forecast_series(
    history: pd.Series,
    minutes_ahead: int = 60,
    target: Optional[str] = None,
) -> tuple[pd.Series, ModelName]:
    """
    Devolve `(pd.Series com minutes_ahead pontos a 1 min, model_name)`.

    Args:
      history       : série histórica indexada por timestamp.
      minutes_ahead : horizonte da previsão em minutos.
      target        : nome da coluna (ex.: "temperature"). Se dado e existir
                      checkpoint em ml/models/<target>.pkl, é usado. Senão,
                      cai para refit online (mais lento).
    """
    s = _resample_to_minutes(history)
    if s.empty:
        return pd.Series(dtype=float), "naive"

    end = s.index[-1]
    future_idx = pd.date_range(
        start=end + pd.Timedelta(minutes=1),
        periods=minutes_ahead,
        freq="1min",
    )

    # 1. Modelo persistido (preferencial em produção)
    if target:
        vals = _persisted_forecast(target, s, minutes_ahead)
        if vals is not None and len(vals) == minutes_ahead:
            log.info("Forecast com checkpoint persistido (%s, %d pts)",
                     target, minutes_ahead)
            return pd.Series(vals, index=future_idx), "persisted"

    # 2. Holt-Winters online → SES → naive
    for name, fn in (
        ("holt-winters", lambda: _hw_forecast(s, minutes_ahead)),
        ("exponential",  lambda: _ses_forecast(s, minutes_ahead)),
    ):
        values = fn()
        if values is not None and len(values) == minutes_ahead:
            log.info("Forecast com %s online (%d pts)", name, minutes_ahead)
            return pd.Series(values, index=future_idx), name

    log.info("Forecast naive (sem dados/libs suficientes)")
    return pd.Series(_naive_forecast(s, minutes_ahead), index=future_idx), "naive"
