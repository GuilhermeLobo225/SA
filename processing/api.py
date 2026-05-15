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
def compute_status_5(count: int, capacity: int) -> str:
    """
    Mapeamento percentual baseado em UX (5 níveis para badges de cor).
    Usado pelo website e pela app. Independente do estado simplificado
    (3 níveis) que o firmware do LED consome.
    """
    if capacity <= 0 or count <= 0:
        return "vazio"
    pct = count / capacity
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

    count    = int(occ.get("people", 0) or 0)
    capacity = int(occ.get("capacity", 0) or 0)
    status_3 = occ.get("status")                        # "livre" | "parcial" | "cheio"
    status_5 = compute_status_5(count, capacity)

    # Timestamp: prefere o da ocupação (mais recente em geral), caindo para o
    # do ambiente, caindo para "now".
    timestamp = occ.get("timestamp") or env.get("timestamp") or datetime.now().isoformat()

    return {
        # Identificação
        "room_id":      to_public_id(internal_id),
        "timestamp":    timestamp,

        # Ocupação
        "count":          count,                                # número de pessoas (alias "people")
        "people":         count,                                # alias para retro-compat
        "capacity":       capacity,
        "tables":         int(occ.get("tables", 0) or 0),
        "chairs_total":   int(occ.get("chairs_total", 0) or 0),
        "chairs_free":    int(occ.get("chairs_free", 0) or 0),
        "occupancy_pct":  float(occ.get("occupancy_pct", 0) or 0),
        "status":         status_5,                             # 5 estados (UX)
        "status_simple":  status_3,                             # 3 estados (LED)

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


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "sala-estudo-api"})


if __name__ == "__main__":
    app.run(host=API_HOST, port=API_PORT, debug=True)
