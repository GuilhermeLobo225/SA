"""
Sala de Estudo Inteligente — Sincronização Firebase
"""

import os
import logging
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, db, storage

from config import (
    FIREBASE_CREDENTIALS, FIREBASE_STORAGE_BUCKET,
    FIREBASE_DATABASE_URL, ROOM_ID
)

logger = logging.getLogger(__name__)


class FirebaseSync:

    def __init__(self):
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS)
            firebase_admin.initialize_app(cred, {
                "databaseURL": FIREBASE_DATABASE_URL,
                "storageBucket": FIREBASE_STORAGE_BUCKET,
            })
        self.bucket = storage.bucket()
        logger.info("Firebase inicializado.")

    def get_latest_image_path(self) -> str | None:
        """Obtém o path da última imagem enviada pela ESP32-CAM."""
        ref = db.reference(f"rooms/{ROOM_ID}/latest_image")
        return ref.get()

    def download_image(self, cloud_path: str, local_dir: str) -> str | None:
        """Download de imagem do Firebase Storage."""
        try:
            blob = self.bucket.blob(cloud_path)
            if not blob.exists():
                logger.warning("Imagem não encontrada: %s", cloud_path)
                return None

            filename = os.path.basename(cloud_path)
            local_path = os.path.join(local_dir, filename)
            blob.download_to_filename(local_path)
            logger.info("Download concluído: %s", local_path)
            return local_path
        except Exception as e:
            logger.error("Erro no download: %s", e)
            return None

    def delete_image(self, cloud_path: str):
        """Eliminar imagem do Storage após inferência (privacy by design)."""
        try:
            blob = self.bucket.blob(cloud_path)
            blob.delete()
            logger.info("Imagem eliminada: %s", cloud_path)
        except Exception as e:
            logger.error("Erro ao eliminar: %s", e)

    def push_occupancy(self, result: dict):
        """Enviar resultado de ocupação para o Realtime Database."""
        # Atualizar dados atuais
        ref = db.reference(f"rooms/{ROOM_ID}/occupancy/current")
        ref.set(result)

        # Guardar no histórico
        hist_ref = db.reference(f"rooms/{ROOM_ID}/occupancy/history")
        hist_ref.push(result)
        logger.info("Resultado de ocupação enviado.")

    def get_room_data(self) -> dict:
        """Obter todos os dados atuais de uma sala."""
        ref = db.reference(f"rooms/{ROOM_ID}")
        return ref.get() or {}
