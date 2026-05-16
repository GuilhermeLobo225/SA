"""
Serviço de forecasting de curto-prazo, usado pelo endpoint /api/rooms/<id>/history.

Escolhe automaticamente o modelo mais sofisticado que os dados disponíveis
permitem:

  1. Holt-Winters com sazonalidade diária  (precisa de >=2 dias de histórico)
  2. Simple Exponential Smoothing          (precisa de >=15 min)
  3. Naive (repete o último valor)         (sempre disponível)

Razões:
  - Holt-Winters captura o ciclo dia/noite, ótimo para 1h adiante.
  - SES é robusto e suficiente para extrapolar tendência local.
  - Naive é o "fallback honesto" — melhor mostrar uma linha plana com label
    "previsão indisponível" do que inventar uma trajectória.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd

log = logging.getLogger("forecast")

ModelName = Literal["holt-winters", "exponential", "naive"]
SEASONAL_PERIODS_DAILY = 24 * 60   # 1 dia em minutos (resample a 1 min)


def _resample_to_minutes(s: pd.Series) -> pd.Series:
    """Uniformiza a série para 1 ponto por minuto, interpolando pequenas falhas."""
    if s.empty:
        return s
    s = s.resample("1min").mean()
    s = s.interpolate(method="time", limit=10)   # tapa buracos até 10 min
    s = s.dropna()
    return s


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
        # SES dá uma única previsão repetida — junta-lhe ligeira tendência
        base = float(model.forecast(steps=1)[0])
        recent_trend = float(np.mean(np.diff(s.values[-30:]))) if len(s) >= 30 else 0.0
        return np.array([base + recent_trend * (i + 1) for i in range(steps)])
    except Exception as e:
        log.warning("SES falhou: %s", e)
        return None


def _naive_forecast(s: pd.Series, steps: int) -> np.ndarray:
    last = float(s.iloc[-1]) if not s.empty else 0.0
    return np.full(steps, last, dtype=float)


def forecast_series(
    history: pd.Series,
    minutes_ahead: int = 60,
) -> tuple[pd.Series, ModelName]:
    """
    Devolve uma `pd.Series` com `minutes_ahead` valores previstos, indexada com
    timestamps subsequentes ao fim do histórico, e o nome do modelo usado.
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

    # Tenta Holt-Winters → SES → naive
    for name, fn in (
        ("holt-winters", lambda: _hw_forecast(s, minutes_ahead)),
        ("exponential",  lambda: _ses_forecast(s, minutes_ahead)),
    ):
        values = fn()
        if values is not None and len(values) == minutes_ahead:
            log.info("Forecast com %s (%d pts)", name, minutes_ahead)
            return pd.Series(values, index=future_idx), name

    log.info("Forecast naive (sem dados/libs suficientes)")
    return pd.Series(_naive_forecast(s, minutes_ahead), index=future_idx), "naive"
