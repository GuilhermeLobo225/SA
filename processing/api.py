"""
Sala de Estudo Inteligente — API REST

Expõe dados de ocupação (YOLO) + ambiente (sensor) para o dashboard web e a
app móvel. Lê do Firebase (projeto Sensor) e serve um JSON unificado por sala.

Contrato público: ver docs/api_contract.md
"""

import logging
from datetime import datetime

from flask import Flask, jsonify
from flask_cors import CORS

from config import (
    API_HOST, API_PORT, ROOM_ID,
    PUBLIC_TO_INTERNAL_ROOM_ID, INTERNAL_TO_PUBLIC_ROOM_ID,
)
from firebase_sync import FirebaseSync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

sync = FirebaseSync()


# ============================================================
# Mapeamento de room IDs
# ============================================================
def resolve_internal_id(public_id: str) -> str | None:
    """Aceita ID público ('bg') OU ID interno ('sala_b1_piso2')."""
    if public_id in PUBLIC_TO_INTERNAL_ROOM_ID:
        return PUBLIC_TO_INTERNAL_ROOM_ID[public_id]
    # se já for um ID interno conhecido, devolve-o
    if public_id in INTERNAL_TO_PUBLIC_ROOM_ID:
        return public_id
    return None


def to_public_id(internal_id: str) -> str:
    """Devolve o ID público; se não houver mapeamento, devolve o interno."""
    return INTERNAL_TO_PUBLIC_ROOM_ID.get(internal_id, internal_id)


# ============================================================
# Classificação de ocupação — 5 estados, para o frontend
# ============================================================
def compute_status_5(occupied: int, capacity: int) -> str:
    """
    Mapeamento percentual baseado em UX (5 níveis para badges de cor).
    Usado pelo website e pela app. Independente do estado simplificado
    (3 níveis) que o firmware do LED consome.

    `occupied` é o nº de CADEIRAS ocupadas (pessoas + objetos sem dono),
    não o nº de pessoas — para bater certo com o LED quando alguém deixa
    as coisas em pausa.
    """
    if capacity <= 0 or occupied <= 0:
        return "vazio"
    pct = occupied / capacity
    if pct >= 0.95:
        return "cheio"
    if pct >= 0.75:
        return "quase_cheio"
    if pct >= 0.40:
        return "parcialmente_ocupado"
    return "disponivel"


# ============================================================
# Builders de payload
# ============================================================
def build_room_payload(internal_id: str) -> dict | None:
    """
    Junta occupancy + environment do Firebase num único objeto, na forma que
    o frontend espera. Devolve None se a sala não existir / não tiver dados.
    """
    snap = sync.get_room_snapshot()
    if not snap:
        return None

    occ = (snap.get("occupancy") or {}).get("current") or {}
    env = (snap.get("environment") or {}).get("current") or {}

    capacity = int(occ.get("capacity", 0) or 0)
    people   = int(occ.get("people",   0) or 0)              # nº de pessoas físicas detetadas
    status_3 = occ.get("status")                              # "livre" | "parcial" | "cheio"

    # Timestamp: prefere o da ocupação (mais recente em geral), caindo para o
    # do ambiente, caindo para "now".
    timestamp = occ.get("timestamp") or env.get("timestamp") or datetime.now().isoformat()

    # ---- Per-cadeira ----
    # Vem do detector como rooms/<id>/occupancy/current.chair_states (e
    # table_states). Mantém estrutura mesmo se o detector ainda não tiver
    # produzido — devolve listas vazias.
    chair_states = occ.get("chair_states") or []
    table_states = occ.get("table_states") or []
    chairs_occupied = int(occ.get("chairs_occupied", sum(1 for c in chair_states if c.get("occupied"))) or 0)

    # `count` no contrato é o número de LUGARES ocupados (= chairs_occupied),
    # não de pessoas. Isto garante que a UI mostra "1/4 ocupados" quando
    # alguém deixou o portátil em pausa, em vez de "0/4 vazio".
    # O `status_5` segue a mesma lógica para manter a UX alinhada com o LED.
    count    = chairs_occupied
    status_5 = compute_status_5(chairs_occupied, capacity)

    return {
        # Identificação
        "room_id":      to_public_id(internal_id),
        "timestamp":    timestamp,

        # Ocupação agregada
        "count":            count,                              # nº de LUGARES ocupados (= chairs_occupied)
        "people":           people,                             # nº de pessoas físicas detetadas
        "capacity":         capacity,
        "tables":           int(occ.get("tables", 0) or 0),
        "chairs_total":     int(occ.get("chairs_total", 0) or 0),
        "chairs_free":      int(occ.get("chairs_free", 0) or 0),
        "chairs_occupied":  chairs_occupied,
        "occupancy_pct":    float(occ.get("occupancy_pct", 0) or 0),
        "status":           status_5,                           # 5 estados (UX)
        "status_simple":    status_3,                           # 3 estados (LED)

        # Ocupação per-cadeira / per-mesa (vindo do layout descoberto)
        "chair_states":     chair_states,
        "table_states":     table_states,

        # Ambiente — valores numéricos primários (para thresholds e gráficos)
        "temperature":   env.get("temperature"),                # °C
        "humidity":      env.get("humidity"),                   # %
        "air_quality":   env.get("air_quality_raw"),            # ADC 12-bit (0-4095, MQ-135)
        "light":         env.get("light_raw"),                  # ADC 12-bit (fotodíodo)
        "light_digital": env.get("light_digital"),              # 0/1 (limiar do potenciómetro)
        "noise_db":      env.get("noise_db"),                   # dB relativo (MSM261 I2S)

        # Ambiente — classes textuais (para badges de status)
        "comfort":           env.get("comfort"),                # "bom" | "moderado" | "mau"
        "air_quality_class": env.get("air_quality"),            # "bom" | "moderado" | "mau"
        "light_class":       env.get("light"),                  # "bom" | "moderado" | "mau"
        "noise":             env.get("noise"),                  # "baixo" | "moderado" | "elevado"
    }


# ============================================================
# Endpoints
# ============================================================
@app.route("/api/rooms", methods=["GET"])
def list_rooms():
    """Lista de todas as salas com sensorização ativa."""
    rooms = []
    for public_id, internal_id in PUBLIC_TO_INTERNAL_ROOM_ID.items():
        payload = build_room_payload(internal_id)
        if payload:
            rooms.append(payload)
    return jsonify(rooms)


@app.route("/api/rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    """Snapshot completo de uma sala (ocupação + ambiente)."""
    internal_id = resolve_internal_id(room_id)
    if internal_id is None:
        return jsonify({"error": f"Sala '{room_id}' não encontrada"}), 404

    payload = build_room_payload(internal_id)
    if payload is None:
        return jsonify({"error": f"Sem dados para a sala '{room_id}'"}), 404
    return jsonify(payload)


@app.route("/api/rooms/<room_id>/occupancy", methods=["GET"])
def get_occupancy(room_id):
    """Apenas os campos de ocupação."""
    internal_id = resolve_internal_id(room_id)
    if internal_id is None:
        return jsonify({"error": f"Sala '{room_id}' não encontrada"}), 404

    payload = build_room_payload(internal_id)
    if payload is None:
        return jsonify({"error": "Sem dados de ocupação"}), 404

    return jsonify({
        "room_id":        payload["room_id"],
        "timestamp":      payload["timestamp"],
        "count":          payload["count"],
        "capacity":       payload["capacity"],
        "tables":         payload["tables"],
        "chairs_total":   payload["chairs_total"],
        "chairs_free":    payload["chairs_free"],
        "occupancy_pct":  payload["occupancy_pct"],
        "status":         payload["status"],
        "status_simple":  payload["status_simple"],
        # Estado per-mesa: lista de
        # {id, capacity, occupied, free, people, objects, status}
        # vinda do detector (atribuição por proximidade aos centroides
        # definidos em ROOM_TABLE_POSITIONS).
        "table_states":   payload["table_states"],
    })


@app.route("/api/rooms/<room_id>/environment", methods=["GET"])
def get_environment(room_id):
    """Apenas os campos ambientais."""
    internal_id = resolve_internal_id(room_id)
    if internal_id is None:
        return jsonify({"error": f"Sala '{room_id}' não encontrada"}), 404

    payload = build_room_payload(internal_id)
    if payload is None:
        return jsonify({"error": "Sem dados ambientais"}), 404

    return jsonify({
        "room_id":            payload["room_id"],
        "timestamp":          payload["timestamp"],
        "temperature":        payload["temperature"],
        "humidity":           payload["humidity"],
        "air_quality":        payload["air_quality"],
        "light":              payload["light"],
        "light_digital":      payload["light_digital"],
        "noise_db":           payload["noise_db"],
        "comfort":            payload["comfort"],
        "air_quality_class":  payload["air_quality_class"],
        "light_class":        payload["light_class"],
        "noise":              payload["noise"],
    })


@app.route("/api/rooms/<room_id>/layout", methods=["GET"])
def get_layout(room_id):
    """
    Layout descoberto automaticamente pelo detector na primeira imagem
    (rooms/<id>/layout no Firebase). Devolve {chairs, tables, image_size,
    discovered_at, ...} normalizado em [0..1], pronto para a planta SVG e
    para a `PlantaView` da app móvel renderizarem cadeira a cadeira.
    """
    internal_id = resolve_internal_id(room_id)
    if internal_id is None:
        return jsonify({"error": f"Sala '{room_id}' não encontrada"}), 404

    from firebase_admin import db
    ref = db.reference(f"rooms/{internal_id}/layout", app=sync.sensor_app)
    layout = ref.get()
    if not layout:
        return jsonify({
            "error": "Layout ainda não descoberto",
            "hint":  "Aguardar a próxima imagem da ESP32-CAM (assume-se sala vazia).",
        }), 404
    return jsonify({"room_id": to_public_id(internal_id), **layout})


@app.route("/api/rooms/<room_id>/layout", methods=["DELETE"])
def reset_layout(room_id):
    """
    Apaga o layout persistido em `rooms/<id>/layout`. Útil quando a câmara é
    reposicionada ou a sala reconfigurada — força o detector a redescobrir
    o layout na próxima imagem que receber.

    O detector tem de ser reiniciado (Ctrl+C + python detector.py) para
    voltar a entrar em modo "à espera de imagem com sala vazia"; em
    alternativa, basta esperar que ele detecte a ausência de layout no
    próximo loop e retome a descoberta automaticamente.
    """
    internal_id = resolve_internal_id(room_id)
    if internal_id is None:
        return jsonify({"error": f"Sala '{room_id}' não encontrada"}), 404

    from firebase_admin import db
    ref = db.reference(f"rooms/{internal_id}/layout", app=sync.sensor_app)
    existing = ref.get()
    if not existing:
        return jsonify({
            "ok":   True,
            "note": "Não havia layout para apagar.",
        })
    ref.delete()
    logger.info("Layout de %s eliminado por API — pronto para redescoberta.", internal_id)
    return jsonify({
        "ok":   True,
        "note": ("Layout apagado. Reinicia o detector OU aguarda o próximo "
                 "ciclo: a próxima imagem (sala vazia) vai disparar nova "
                 "descoberta automaticamente."),
        "chairs_before": existing.get("chairs_total", 0),
        "tables_before": existing.get("tables_total", 0),
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "sala-estudo-api"})


# ============================================================
# Endpoint de série temporal + previsão curta
# ============================================================
# Lazy imports — só carrega pandas/forecast_service quando este endpoint é
# chamado pela primeira vez. Mantém arranque rápido para quem só usa /current.
_lazy = {}


def _get_history_deps():
    if "pd" not in _lazy:
        import pandas as pd            # noqa: WPS433
        from firebase_admin import db  # noqa: WPS433
        from forecast_service import forecast_series  # noqa: WPS433
        _lazy["pd"] = pd
        _lazy["db"] = db
        _lazy["forecast_series"] = forecast_series
    return _lazy["pd"], _lazy["db"], _lazy["forecast_series"]


# Targets aceites e onde encontrá-los no Firebase (sub-árvore + nome do campo)
HISTORY_TARGETS = {
    "temperature":     ("environment", "temperature",     "°C"),
    "humidity":        ("environment", "humidity",        "%"),
    "air_quality":     ("environment", "air_quality_raw", "ADC"),
    "light":           ("environment", "light_raw",       "ADC"),
    "noise_db":        ("environment", "noise_db",        "dB rel."),
    "people":          ("occupancy",   "people",          "pessoas"),
}


def _fetch_history_df(internal_id: str, sub: str, field: str, hours: float):
    """Lê rooms/<id>/<sub>/history e devolve um DataFrame [timestamp, value]."""
    pd, db, _ = _get_history_deps()
    path = f"rooms/{internal_id}/{sub}/history"
    ref = db.reference(path, app=sync.sensor_app)
    raw = ref.get() or {}
    if not raw:
        return pd.DataFrame(columns=["timestamp", "value"])
    rows = []
    for item in raw.values():
        ts = item.get("timestamp")
        v  = item.get(field)
        if ts is None or v is None:
            continue
        rows.append({"timestamp": ts, "value": v})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    cutoff = pd.Timestamp.now() - pd.Timedelta(hours=hours)
    df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    return df


@app.route("/api/rooms/<room_id>/history", methods=["GET"])
def get_history(room_id):
    """
    Série temporal recente + previsão curta para o frontend.
    Query params:
      target           — temperature | humidity | air_quality | light |
                          noise_db | people
      hours            — janela histórica (default 4)
      forecast_minutes — horizonte da previsão (default 60)
    """
    from flask import request   # local import — Flask já está importado em cima
    target  = request.args.get("target", "temperature")
    hours   = float(request.args.get("hours", 4))
    horizon = int(request.args.get("forecast_minutes", 60))

    internal_id = resolve_internal_id(room_id)
    if internal_id is None:
        return jsonify({"error": f"Sala '{room_id}' não encontrada"}), 404
    if target not in HISTORY_TARGETS:
        return jsonify({"error": f"target inválido. Use um de: {list(HISTORY_TARGETS)}"}), 400

    sub, field, unit = HISTORY_TARGETS[target]
    df = _fetch_history_df(internal_id, sub, field, hours)
    pd, _, forecast_series = _get_history_deps()

    if df.empty:
        return jsonify({
            "target": target, "unit": unit,
            "history": [], "forecast": [], "model": "naive",
            "note": "Sem histórico disponível para este target.",
        })

    # Histórico (1 ponto por timestamp; valores numéricos)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna()
    series = df.set_index("timestamp")["value"]

    # Previsão curta — só faz sentido para targets numéricos contínuos.
    # Para `people` devolvemos vazia (a previsão de ocupação é trabalho futuro).
    if target == "people":
        forecast_series_out = pd.Series(dtype=float)
        model = "n/a"
    else:
        # Passa `target` para o forecast_service poder usar o modelo
        # persistido em ml/models/<target>.pkl (treinado offline via
        # `python ml/forecasting.py --target <t> --save`). Se o checkpoint
        # não existir, o serviço cai para refit online (HW → SES → naive).
        forecast_series_out, model = forecast_series(
            series, minutes_ahead=horizon, target=target,
        )

    payload = {
        "target":   target,
        "unit":     unit,
        "hours":    hours,
        "history":  [
            {"t": ts.isoformat(timespec="seconds"), "v": float(v)}
            for ts, v in series.items()
        ],
        "forecast": [
            {"t": ts.isoformat(timespec="seconds"), "v": float(v)}
            for ts, v in forecast_series_out.items()
        ],
        "model":    model,
    }
    return jsonify(payload)


# ============================================================
# Endpoint de estatísticas do dia (agregados desde 00:00 local)
# ============================================================
@app.route("/api/rooms/<room_id>/stats", methods=["GET"])
def get_stats(room_id):
    """Métricas agregadas das últimas 24h ou desde 00:00 (configurável).

    Devolve:
      - occupancy: pico, média, % do tempo com sala cheia/parcial/livre
      - environment: min/max/média temperatura, humidade; pico ruído; pior ar
      - last_24h_points: nº amostras consideradas
    """
    from flask import request
    internal_id = resolve_internal_id(room_id)
    if internal_id is None:
        return jsonify({"error": f"Sala '{room_id}' não encontrada"}), 404

    hours = float(request.args.get("hours", 24))
    pd, _, _ = _get_history_deps()

    env_df = _fetch_history_df(internal_id, "environment", "temperature", hours)
    # Para conforto/ar/ruído precisamos das colunas extra → ir buscar com mais campos
    # Versão simples: re-puxar com cada campo (poucas chamadas, é OK)
    def col(field):
        df = _fetch_history_df(internal_id, "environment", field, hours)
        return df.set_index("timestamp")["value"] if not df.empty else pd.Series(dtype=float)

    temp  = col("temperature")
    hum   = col("humidity")
    air   = col("air_quality_raw")
    noise = col("noise_db")

    occ_df = _fetch_history_df(internal_id, "occupancy", "people", hours)
    occ_status_df = _fetch_history_df(internal_id, "occupancy", "status", hours)

    def num_summary(s, fmt=lambda v: round(v, 1)):
        if s.empty:
            return {"min": None, "max": None, "avg": None, "median": None}
        return {
            "min":    fmt(float(s.min())),
            "max":    fmt(float(s.max())),
            "avg":    fmt(float(s.mean())),
            "median": fmt(float(s.median())),
        }

    # Hora mais quente / mais fresca
    hottest = coldest = None
    if not temp.empty:
        hottest = temp.idxmax().isoformat(timespec="seconds")
        coldest = temp.idxmin().isoformat(timespec="seconds")

    # Ocupação
    occ_summary = {
        "peak": None, "avg": None, "median": None, "min": None,
        "pct_livre": 0, "pct_parcial": 0, "pct_cheio": 0,
    }
    if not occ_df.empty:
        ppl = occ_df.set_index("timestamp")["value"].astype(float)
        occ_summary["peak"]   = int(ppl.max())
        occ_summary["min"]    = int(ppl.min())
        occ_summary["avg"]    = round(float(ppl.mean()),   1)
        occ_summary["median"] = round(float(ppl.median()), 1)
    if not occ_status_df.empty:
        statuses = occ_status_df["value"].astype(str)
        total = max(1, len(statuses))
        for k in ("livre", "parcial", "cheio"):
            occ_summary[f"pct_{k}"] = round((statuses == k).sum() * 100 / total, 1)

    return jsonify({
        "room_id":         to_public_id(internal_id),
        "hours_window":    hours,
        "occupancy":       occ_summary,
        "temperature":     {**num_summary(temp),  "hottest_at": hottest, "coldest_at": coldest},
        "humidity":        num_summary(hum),
        "air_quality":     num_summary(air, fmt=lambda v: int(v)),
        "noise_db":        num_summary(noise),
        "samples":         {
            "environment": int(len(temp)),
            "occupancy":   int(len(occ_df)),
        },
    })


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=API_PORT, debug=True)
