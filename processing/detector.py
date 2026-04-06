"""
Sala de Estudo Inteligente — Pipeline de Deteção
YOLOv8 + DeepSORT para contagem de ocupantes.
"""

import os
import time
import logging
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

from config import (
    YOLO_MODEL, YOLO_CONFIDENCE, YOLO_IOU_THRESHOLD, YOLO_CLASSES,
    DEEPSORT_MAX_AGE, DEEPSORT_N_INIT, DEEPSORT_MAX_COSINE_DIST,
    ROOM_CAPACITY, LOCAL_TEMP_DIR, ROOM_ID
)
from firebase_sync import FirebaseSync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class OccupancyDetector:
    """Pipeline de deteção de ocupação com YOLOv8 + DeepSORT."""

    def __init__(self):
        logger.info("A inicializar modelo YOLOv8: %s", YOLO_MODEL)
        self.model = YOLO(YOLO_MODEL)

        logger.info("A inicializar DeepSORT tracker")
        self.tracker = DeepSort(
            max_age=DEEPSORT_MAX_AGE,
            n_init=DEEPSORT_N_INIT,
            max_cosine_distance=DEEPSORT_MAX_COSINE_DIST,
        )

        self.firebase = FirebaseSync()
        Path(LOCAL_TEMP_DIR).mkdir(exist_ok=True)

    def detect(self, image_path: str) -> dict:
        """
        Executa deteção numa imagem.

        Returns:
            dict com count, detections, tracks, timestamp
        """
        img = cv2.imread(image_path)
        if img is None:
            logger.error("Não foi possível ler a imagem: %s", image_path)
            return {"count": -1, "error": "Imagem inválida"}

        # YOLOv8 inference
        results = self.model(
            img,
            conf=YOLO_CONFIDENCE,
            iou=YOLO_IOU_THRESHOLD,
            classes=YOLO_CLASSES,
            verbose=False,
        )

        # Extrair deteções para DeepSORT
        detections = []
        for r in results:
            boxes = r.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                detections.append(([x1, y1, x2 - x1, y2 - y1], conf, "person"))

        # Atualizar tracker
        tracks = self.tracker.update_tracks(detections, frame=img)
        confirmed = [t for t in tracks if t.is_confirmed()]
        count = len(confirmed)

        # Resultado
        result = {
            "room_id": ROOM_ID,
            "timestamp": datetime.now().isoformat(),
            "count": count,
            "capacity": ROOM_CAPACITY,
            "occupancy_pct": round(count / ROOM_CAPACITY * 100, 1),
            "raw_detections": len(detections),
            "status": self._classify_occupancy(count),
        }

        logger.info(
            "Sala %s: %d/%d ocupantes (%.1f%%) — %s",
            ROOM_ID, count, ROOM_CAPACITY,
            result["occupancy_pct"], result["status"]
        )

        return result

    def _classify_occupancy(self, count: int) -> str:
        ratio = count / ROOM_CAPACITY
        if ratio == 0:
            return "vazio"
        elif ratio < 0.5:
            return "disponivel"
        elif ratio < 0.85:
            return "parcialmente_ocupado"
        elif ratio < 1.0:
            return "quase_cheio"
        return "cheio"

    def process_new_images(self):
        """Loop principal: verifica novas imagens no Firebase e processa."""
        logger.info("A iniciar loop de processamento para sala '%s'...", ROOM_ID)

        last_processed = None

        while True:
            try:
                # Verificar nova imagem
                latest = self.firebase.get_latest_image_path()
                if latest and latest != last_processed:
                    logger.info("Nova imagem detetada: %s", latest)

                    # Download
                    local_path = self.firebase.download_image(latest, LOCAL_TEMP_DIR)
                    if local_path:
                        # Deteção
                        result = self.detect(local_path)

                        # Enviar resultado
                        if result.get("count", -1) >= 0:
                            self.firebase.push_occupancy(result)

                        # Limpeza
                        os.remove(local_path)
                        if True:  # DELETE_AFTER_INFERENCE
                            self.firebase.delete_image(latest)

                        last_processed = latest

                time.sleep(5)  # Verificar a cada 5 segundos

            except KeyboardInterrupt:
                logger.info("Processamento interrompido pelo utilizador.")
                break
            except Exception as e:
                logger.error("Erro no loop: %s", e, exc_info=True)
                time.sleep(10)


if __name__ == "__main__":
    detector = OccupancyDetector()
    detector.process_new_images()
