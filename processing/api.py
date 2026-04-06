"""
Sala de Estudo Inteligente — API REST
Expõe dados de ocupação e conforto ambiental.
"""

from flask import Flask, jsonify
from flask_cors import CORS

import firebase_admin
from firebase_admin import credentials, db

from config import (
    FIREBASE_CREDENTIALS, FIREBASE_DATABASE_URL,
    API_HOST, API_PORT, ROOM_ID
)

app = Flask(__name__)
CORS(app)

# Firebase init
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDENTIALS)
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DATABASE_URL})


@app.route("/api/rooms", methods=["GET"])
def get_rooms():
    """Lista todas as salas."""
    ref = db.reference("rooms")
    rooms = ref.get() or {}
    summary = []
    for room_id, data in rooms.items():
        occ = data.get("occupancy", {}).get("current", {})
        env = data.get("environment", {}).get("current", {})
        summary.append({
            "room_id": room_id,
            "count": occ.get("count", 0),
            "capacity": occ.get("capacity", 0),
            "status": occ.get("status", "desconhecido"),
            "comfort": env.get("comfort", "desconhecido"),
            "temperature": env.get("temperature"),
            "noise": env.get("noise"),
        })
    return jsonify(summary)


@app.route("/api/rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    """Dados detalhados de uma sala."""
    ref = db.reference(f"rooms/{room_id}")
    data = ref.get()
    if not data:
        return jsonify({"error": "Sala não encontrada"}), 404
    return jsonify(data)


@app.route("/api/rooms/<room_id>/occupancy", methods=["GET"])
def get_occupancy(room_id):
    """Dados de ocupação atuais."""
    ref = db.reference(f"rooms/{room_id}/occupancy/current")
    data = ref.get()
    if not data:
        return jsonify({"error": "Sem dados de ocupação"}), 404
    return jsonify(data)


@app.route("/api/rooms/<room_id>/environment", methods=["GET"])
def get_environment(room_id):
    """Dados ambientais atuais."""
    ref = db.reference(f"rooms/{room_id}/environment/current")
    data = ref.get()
    if not data:
        return jsonify({"error": "Sem dados ambientais"}), 404
    return jsonify(data)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host=API_HOST, port=API_PORT, debug=True)
