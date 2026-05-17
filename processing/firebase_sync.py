"""
Sala de Estudo Inteligente — Sincronização Firebase
Suporta 2 projetos distintos (Vision e Sensor) via apps com nomes diferentes.
"""

import os
import logging
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, db, storage

from config import (
    VISION_CREDENTIALS, VISION_STORAGE_BUCKET, VISION_DATABASE_URL,
    SENSOR_CREDENTIALS, SENSOR_DATABASE_URL,
    ROOM_ID,
)

logger = logging.getLogger(__name__)


class FirebaseSync:
    """Gere as ligações aos dois projetos Firebase em paralelo."""

    APP_VISION = "vision"
    APP_SENSOR = "sensor"

    def __init__(self):
        self._init_app(
            name=self.APP_VISION,
            cred_path=VISION_CREDENTIALS,
            database_url=VISION_DATABASE_URL,
            storage_bucket=VISION_STORAGE_BUCKET,
        )
        self._init_app(
            name=self.APP_SENSOR,
            cred_path=SENSOR_CREDENTIALS,
            database_url=SENSOR_DATABASE_URL,
            storage_bucket=None,
        )
        self.vision_app = firebase_admin.get_app(self.APP_VISION)
        self.sensor_app = firebase_admin.get_app(self.APP_SENSOR)
        logger.info("Firebase inicializado para os 2 projetos (Vision + Sensor).")

    @staticmethod
    def _init_app(name: str, cred_path: str, database_url: str, storage_bucket: str | None):
        """Inicializa uma app Firebase nomeada, se ainda não existir."""
        try:
            firebase_admin.get_app(name)
            return
        except ValueError:
            pass

        if not Path(cred_path).exists():
            raise FileNotFoundError(
                f"Credencial Firebase em falta: {cred_path}\n"
                f"Gera no Firebase Console -> Configurações -> Contas de serviço."
            )

        cred = credentials.Certificate(cred_path)
        options = {"databaseURL": database_url}
        if storage_bucket:
            options["storageBucket"] = storage_bucket
        firebase_admin.initialize_app(cred, options, name=name)

    # ====================================================================
    # VISION — leitura
    # ====================================================================
    def get_latest_image_path(self) -> str | None:
        """Path da última imagem carregada pela ESP32-CAM."""
        ref = db.reference(f"rooms/{ROOM_ID}/latest_image", app=self.vision_app)
        return ref.get()

    def get_last_capture_ts(self) -> str | None:
        ref = db.reference(f"rooms/{ROOM_ID}/last_capture", app=self.vision_app)
        return ref.get()

    def download_image(self, cloud_path: str, local_dir: str) -> str | None:
        """Descarrega uma imagem do Storage do projeto Vision."""
        try:
            bucket = storage.bucket(app=self.vision_app)
            blob = bucket.blob(cloud_path)
            if not blob.exists():
                logger.warning("Imagem não encontrada: %s", cloud_path)
                return None

            Path(local_dir).mkdir(parents=True, exist_ok=True)
            filename = os.path.basename(cloud_path)
            local_path = os.path.join(local_dir, filename)
            blob.download_to_filename(local_path)
            logger.info("Download concluído: %s", local_path)
            return local_path
        except Exception as e:
            logger.error("Erro no download: %s", e)
            return None

    def delete_image(self, cloud_path: str):
        """Apaga a imagem do Storage Vision (privacy by design)."""
        try:
            bucket = storage.bucket(app=self.vision_app)
            blob = bucket.blob(cloud_path)
            blob.delete()
            logger.info("Imagem eliminada: %s", cloud_path)
        except Exception as e:
            logger.error("Erro ao eliminar: %s", e)

    # ====================================================================
    # SENSOR — leitura
    # ====================================================================
    def get_environment(self) -> dict:
        """Última leitura ambiental enviada pelo Sensor_NODE."""
        ref = db.reference(f"rooms/{ROOM_ID}/environment/current", app=self.sensor_app)
        return ref.get() or {}

    # ====================================================================
    # SENSOR — escrita (resultado da inferência YOLO)
    # ====================================================================
    def push_occupancy(self, result: dict):
        """Escreve o estado de ocupação no projeto Sensor."""
        current_ref = db.reference(f"rooms/{ROOM_ID}/occupancy/current", app=self.sensor_app)
        current_ref.set(result)

        history_ref = db.reference(f"rooms/{ROOM_ID}/occupancy/history", app=self.sensor_app)
        history_ref.push(result)
        logger.info("Resultado de ocupação enviado para o Firebase Sensor.")

    def push_led_state(self, status: str):
        """
        Estado simplificado para o LED do Sensor_NODE consumir:
          rooms/<id>/occupancy/status = "livre" | "parcial" | "cheio"
        """
        ref = db.reference(f"rooms/{ROOM_ID}/occupancy/status", app=self.sensor_app)
        ref.set(status)

    def get_room_snapshot(self) -> dict:
        """Snapshot completo da sala do projeto Sensor (env + occupancy)."""
        ref = db.reference(f"rooms/{ROOM_ID}", app=self.sensor_app)
        return ref.get() or {}

    # ====================================================================
    # SENSOR — layout descoberto automaticamente
    # ====================================================================
    def get_layout(self) -> dict | None:
        """
        Devolve o layout persistido em `rooms/<id>/layout`, ou None se a sala
        ainda não tem layout (caso em que o detector deve descobrir um na
        próxima imagem capturada).
        """
        ref = db.reference(f"rooms/{ROOM_ID}/layout", app=self.sensor_app)
        return ref.get()

    def push_layout(self, layout: dict):
        """
        Persiste o layout descoberto pelo `layout_discovery.py`. Sobrescreve
        qualquer layout anterior — admin pode forçar nova descoberta apagando
        este caminho no Firebase Console.
        """
        ref = db.reference(f"rooms/{ROOM_ID}/layout", app=self.sensor_app)
        ref.set(layout)
        logger.info("Layout persistido: %d cadeiras / %d mesas.",
                    layout.get("chairs_total", 0), layout.get("tables_total", 0))
