"""
Sala de Estudo Inteligente — Pipeline de Deteção
YOLOv8 + DeepSORT para contagem de ocupantes.

Lê imagens do projeto Vision (Storage) e escreve resultados de ocupação
no projeto Sensor (RTDB).
"""

import os
import time
import logging
from datetime import datetime
from pathlib import Path

import cv2
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

from config import (
    YOLO_MODEL, YOLO_CONFIDENCE, YOLO_IOU_THRESHOLD, YOLO_CLASSES,
    YOLO_CONF_PER_CLASS,
    DEEPSORT_MAX_AGE, DEEPSORT_N_INIT, DEEPSORT_MAX_COSINE_DIST,
    ROOM_CAPACITY, ROOM_TABLES, CHAIRS_PER_TABLE,
    LOCAL_TEMP_DIR, ROOM_ID,
    DELETE_AFTER_INFERENCE,
    SAVE_ANNOTATED_IMAGES, ANNOTATED_DIR,
)
from firebase_sync import FirebaseSync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# IDs do COCO usados pelo YOLOv8
# Só a pessoa interessa para a contagem. O resto (mesa) é puro debug visual.
COCO_PERSON = 0


class OccupancyDetector:
    """YOLOv8 + DeepSORT — contagem de pessoas na sala.

    A capacidade da sala (nº de cadeiras) vem do config (ROOM_CAPACITY), não do
    YOLO. As cadeiras livres são derivadas: ROOM_CAPACITY − pessoas detetadas.
    """

    def __init__(self):
        logger.info("A inicializar YOLOv8 (%s)...", YOLO_MODEL)
        self.model = YOLO(YOLO_MODEL)

        logger.info("A inicializar DeepSORT...")
        self.tracker = DeepSort(
            max_age=DEEPSORT_MAX_AGE,
            n_init=DEEPSORT_N_INIT,
            max_cosine_distance=DEEPSORT_MAX_COSINE_DIST,
        )

        self.firebase = FirebaseSync()
        Path(LOCAL_TEMP_DIR).mkdir(parents=True, exist_ok=True)

    def detect(self, image_path: str) -> dict:
        img = cv2.imread(image_path)
        if img is None:
            logger.error("Não foi possível ler a imagem: %s", image_path)
            return {"count": -1, "error": "Imagem inválida"}

        # Passamos o threshold mínimo do dict per-class para que o modelo devolva
        # candidatos suficientes (ex.: cadeiras vazias com conf baixa). A filtragem
        # fina é feita a seguir, classe a classe, usando YOLO_CONF_PER_CLASS.
        min_conf = min(YOLO_CONF_PER_CLASS.values()) if YOLO_CONF_PER_CLASS else YOLO_CONFIDENCE
        results = self.model(
            img,
            conf=min_conf,
            iou=YOLO_IOU_THRESHOLD,
            classes=YOLO_CLASSES,
            verbose=False,
        )

        person_dets = []
        detections_log = []   # para debug visual

        for r in results:
            for box in r.boxes:
                cls  = int(box.cls[0])
                conf = float(box.conf[0])

                # --- Filtro per-class ---
                # Se a classe não tem threshold definido, cai para o global.
                cls_thr = YOLO_CONF_PER_CLASS.get(cls, YOLO_CONFIDENCE)
                if conf < cls_thr:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                detections_log.append({"cls": cls, "conf": round(conf, 3),
                                        "box": [round(float(x1),1), round(float(y1),1),
                                                round(float(x2),1), round(float(y2),1)]})
                if cls == COCO_PERSON:
                    person_dets.append(([x1, y1, x2 - x1, y2 - y1], conf, "person"))
                # Outras classes (ex.: dining_table) são apenas debug visual.

        # --- Guardar imagem anotada para debug ---
        if SAVE_ANNOTATED_IMAGES:
            try:
                Path(ANNOTATED_DIR).mkdir(parents=True, exist_ok=True)
                annotated = results[0].plot()   # imagem BGR com caixas
                annotated_path = Path(ANNOTATED_DIR) / Path(image_path).name
                cv2.imwrite(str(annotated_path), annotated)
            except Exception as e:
                logger.warning("Falha ao gravar imagem anotada: %s", e)

        # Tracking só de pessoas
        tracks = self.tracker.update_tracks(person_dets, frame=img)
        confirmed = [t for t in tracks if t.is_confirmed()]
        people = len(confirmed)

        # Log detalhado de cada deteção
        if detections_log:
            for d in detections_log:
                cls_name = {0: "person", 56: "chair", 57: "couch", 60: "table"}.get(d["cls"], str(d["cls"]))
                logger.info("  · detecção: %s conf=%.2f box=%s", cls_name, d["conf"], d["box"])

        # Cadeiras: o layout da sala é conhecido em config (ROOM_CAPACITY).
        # Não dependemos do YOLO para contar cadeiras — só para contar pessoas.
        chairs_total = ROOM_CAPACITY
        free_chairs  = max(0, ROOM_CAPACITY - people)

        status = self._classify(people, free_chairs)

        result = {
            "room_id":       ROOM_ID,
            "timestamp":     datetime.now().isoformat(),
            "people":        people,
            "chairs_total":  chairs_total,
            "chairs_free":   free_chairs,
            "capacity":      ROOM_CAPACITY,
            "tables":        ROOM_TABLES,
            "occupancy_pct": round(people / ROOM_CAPACITY * 100, 1),
            "status":        status,
        }

        logger.info(
            "Sala %s: %d/%d pessoas, %d cadeiras livres — %s",
            ROOM_ID, people, ROOM_CAPACITY, free_chairs, status,
        )
        return result

    @staticmethod
    def _classify(people: int, free_chairs: int) -> str:
        """
        Modelo: a sala tem ROOM_TABLES mesas, cada uma com CHAIRS_PER_TABLE cadeiras.
        Capacidade total = ROOM_TABLES * CHAIRS_PER_TABLE = ROOM_CAPACITY.

        Sem informação espacial pessoa→mesa, assumimos distribuição "preencher mesa a
        mesa": as primeiras CHAIRS_PER_TABLE pessoas vão para a 1.ª mesa, etc.
        Isto dá-nos uma heurística directa:

          - pessoas == 0                                  → 0 mesas com pessoas
          - 1 ≤ pessoas ≤ CHAIRS_PER_TABLE                → 1 mesa com pessoas
          - CHAIRS_PER_TABLE+1 ≤ pessoas ≤ 2*CHAIRS...    → 2 mesas com pessoas
          - ...

        Regras do projeto (vão para o LED via rooms/.../occupancy/status):
          🟢 livre   — ainda há pelo menos UMA mesa totalmente vazia
                      (mesas ocupadas < ROOM_TABLES)
          🟡 parcial — todas as mesas têm gente mas há cadeiras livres
                      (mesas ocupadas == ROOM_TABLES e pessoas < ROOM_CAPACITY)
          🔴 cheio   — todas as cadeiras ocupadas
                      (pessoas >= ROOM_CAPACITY)
        """
        if people <= 0:
            return "livre"

        # Quantas mesas foram "tocadas" assumindo enchimento sequencial
        # (math.ceil sem importar a lib: //)
        tables_used = (people + CHAIRS_PER_TABLE - 1) // CHAIRS_PER_TABLE

        if tables_used < ROOM_TABLES:
            return "livre"
        if people < ROOM_CAPACITY:
            return "parcial"
        return "cheio"

    def process_loop(self, poll_interval: int = 5):
        logger.info("A iniciar loop de processamento para sala '%s'...", ROOM_ID)
        last_processed = None

        while True:
            try:
                latest = self.firebase.get_latest_image_path()
                if latest and latest != last_processed:
                    logger.info("Nova imagem detetada: %s", latest)

                    local_path = self.firebase.download_image(latest, LOCAL_TEMP_DIR)
                    if local_path:
                        result = self.detect(local_path)
                        if result.get("people", -1) >= 0:
                            # Envia resultado completo + estado simplificado para o LED
                            self.firebase.push_occupancy(result)
                            self.firebase.push_led_state(result["status"])

                        # Limpeza local
                        try:
                            os.remove(local_path)
                        except OSError:
                            pass

                        # Privacy by design: apagar imagem da cloud
                        if DELETE_AFTER_INFERENCE:
                            self.firebase.delete_image(latest)

                        last_processed = latest

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                logger.info("Interrompido pelo utilizador.")
                break
            except Exception as e:
                logger.error("Erro no loop: %s", e, exc_info=True)
                time.sleep(10)


if __name__ == "__main__":
    OccupancyDetector().process_loop()
