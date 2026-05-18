"""
Sala de Estudo Inteligente — Pipeline de Deteção (agregada)

Fluxo simplificado:
  1. Lê uma imagem do Storage (projeto Vision).
  2. Corre YOLO sobre as classes "ocupador" (pessoa + objetos típicos de
     ocupação como laptop, mochila, livro, garrafa, telefone).
  3. Contagem agregada:
        chairs_occupied = pessoas + max(0, objetos − pessoas)
     Heurística: cada pessoa "leva" um objeto seu; objetos extra sem pessoa
     são interpretados como ocupação "fantasma" (alguém saiu em pausa mas
     deixou as suas coisas).
  4. `chairs_total = ROOM_CAPACITY` (vem do `config.py`). NÃO depende de
     layout descoberto — é a configuração física da sala.
  5. Estado livre/parcial/cheio para o LED.

A descoberta de layout per-cadeira (layout_discovery.py) foi retirada deste
pipeline por trazer mais variância visual do que valor analítico.
"""

import os
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
from ultralytics import YOLO

from config import (
    YOLO_MODEL, YOLO_CONFIDENCE, YOLO_IOU_THRESHOLD, YOLO_CLASSES,
    YOLO_CONF_PER_CLASS, OCCUPIER_CLASSES,
    ROOM_CAPACITY, ROOM_TABLES,
    LOCAL_TEMP_DIR, ROOM_ID,
    DELETE_AFTER_INFERENCE,
    SAVE_ANNOTATED_IMAGES, ANNOTATED_DIR,
)
from firebase_sync import FirebaseSync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# Nomes amigáveis das classes do COCO que tratamos.
CLASS_NAMES = {
    0: "person", 24: "backpack", 26: "handbag", 28: "suitcase",
    39: "bottle", 56: "chair", 57: "couch", 60: "dining_table",
    63: "laptop", 67: "cell_phone", 73: "book",
}


class OccupancyDetector:
    """Pipeline de ocupação agregada (sem per-cadeira)."""

    def __init__(self):
        logger.info("A inicializar YOLO (%s)…", YOLO_MODEL)
        self.model = YOLO(YOLO_MODEL)
        self.firebase = FirebaseSync()
        Path(LOCAL_TEMP_DIR).mkdir(parents=True, exist_ok=True)
        logger.info("Capacidade da sala: %d cadeiras em %d mesa(s).",
                    ROOM_CAPACITY, ROOM_TABLES)

    # =====================================================================
    # PIPELINE PRINCIPAL
    # =====================================================================
    def detect(self, image_path: str) -> dict:
        img = cv2.imread(image_path)
        if img is None:
            logger.error("Não foi possível ler a imagem: %s", image_path)
            return {"chairs_total": -1, "error": "Imagem inválida"}

        # Threshold mínimo absoluto — filtragem fina é feita per-class abaixo.
        min_conf = (min(YOLO_CONF_PER_CLASS.values())
                    if YOLO_CONF_PER_CLASS else YOLO_CONFIDENCE)
        results = self.model(
            img,
            conf=min_conf,
            iou=YOLO_IOU_THRESHOLD,
            classes=YOLO_CLASSES,
            verbose=False,
        )

        person_count = 0
        object_count = 0
        detections_log: list[dict] = []

        for r in results:
            for box in r.boxes:
                cls  = int(box.cls[0])
                conf = float(box.conf[0])
                cls_thr = YOLO_CONF_PER_CLASS.get(cls, YOLO_CONFIDENCE)
                if conf < cls_thr:
                    continue

                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].cpu().numpy())
                detections_log.append({
                    "cls": cls, "conf": round(conf, 3),
                    "box": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                })

                if cls == 0:
                    person_count += 1
                elif cls in OCCUPIER_CLASSES:
                    object_count += 1
                # chair/table/couch só servem para anotação visual; ignoradas aqui

        # ----- Guarda imagem anotada -----
        if SAVE_ANNOTATED_IMAGES:
            try:
                Path(ANNOTATED_DIR).mkdir(parents=True, exist_ok=True)
                annotated = results[0].plot()
                annotated_path = Path(ANNOTATED_DIR) / Path(image_path).name
                cv2.imwrite(str(annotated_path), annotated)
            except Exception as e:
                logger.warning("Falha ao gravar imagem anotada: %s", e)

        # ----- Log das deteções -----
        for d in detections_log:
            name = CLASS_NAMES.get(d["cls"], str(d["cls"]))
            logger.info("  · %s conf=%.2f box=%s", name, d["conf"], d["box"])

        # ----- Cálculo de ocupação -----
        # Heurística simples e robusta:
        #   • Cada pessoa ocupa 1 cadeira.
        #   • Objetos sem pessoa associada (extras) marcam +1 cadeira cada
        #     (cenário "saí em pausa mas deixei o portátil").
        chairs_total    = ROOM_CAPACITY
        extra_objects   = max(0, object_count - person_count)
        chairs_occupied = min(chairs_total, person_count + extra_objects)
        chairs_free     = chairs_total - chairs_occupied
        occupancy_pct   = (round(chairs_occupied / chairs_total * 100, 1)
                            if chairs_total else 0.0)

        # ----- Estado livre/parcial/cheio (consumido pelo LED) -----
        if chairs_occupied <= 0:
            status = "livre"
        elif chairs_occupied >= chairs_total:
            status = "cheio"
        else:
            status = "parcial"

        result = {
            "room_id":          ROOM_ID,
            "timestamp":        datetime.now().isoformat(timespec="seconds"),
            "people":           person_count,
            "objects":          object_count,
            "chairs_total":     chairs_total,
            "chairs_free":      chairs_free,
            "chairs_occupied":  chairs_occupied,
            "capacity":         chairs_total,
            "tables":           ROOM_TABLES,
            "occupancy_pct":    occupancy_pct,
            "status":           status,
            # Campos legados — mantidos vazios para retro-compat com frontend
            # antigo que possa ainda iterar (a Vista da Câmara foi removida).
            "chair_states":     [],
            "table_states":     [],
        }

        logger.info(
            "Sala %s: %d/%d cadeiras ocupadas (%d pessoa(s), %d objeto(s)) — %s",
            ROOM_ID, chairs_occupied, chairs_total,
            person_count, object_count, status,
        )
        return result

    # =====================================================================
    # LOOP
    # =====================================================================
    def process_loop(self, poll_interval: int = 5):
        logger.info("A iniciar loop de processamento para sala '%s'…", ROOM_ID)
        last_processed = None

        while True:
            try:
                latest = self.firebase.get_latest_image_path()
                if latest and latest != last_processed:
                    logger.info("Nova imagem detetada: %s", latest)

                    local_path = self.firebase.download_image(latest, LOCAL_TEMP_DIR)
                    if local_path:
                        result = self.detect(local_path)
                        if result.get("chairs_total", -1) > 0:
                            self.firebase.push_occupancy(result)
                            self.firebase.push_led_state(result["status"])

                        try:
                            os.remove(local_path)
                        except OSError:
                            pass

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
