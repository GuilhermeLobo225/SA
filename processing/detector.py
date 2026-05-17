"""
Sala de Estudo Inteligente — Pipeline de Deteção (per-cadeira)

Fluxo:
  1. Lê uma imagem do Storage (projeto Vision).
  2. Se ainda não existir layout persistido para a sala, assume que ESTA imagem
     é a sala vazia e corre `layout_discovery.discover_layout_from_image`,
     persistindo o resultado em `rooms/<id>/layout` no projeto Sensor.
  3. Para cada imagem subsequente, detecta os "ocupadores" (pessoa + objetos
     do COCO que indicam presença, ex.: backpack, laptop, book, …) e atribui
     cada deteção à cadeira cujo bounding box contém o centro da deteção
     (com tolerância CHAIR_PROXIMITY_FACTOR × diagonal_média_das_cadeiras).
  4. Marca cada cadeira como ocupada/livre e calcula um estado agregado
     (livre/parcial/cheio) que vai para o LED.

A capacidade da sala já não vem de constantes — vem do layout descoberto.
ROOM_TABLES/CHAIRS_PER_TABLE em `config.py` são usadas APENAS como fallback
para o estado inicial enquanto o layout ainda não foi descoberto.
"""

import os
import time
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
from ultralytics import YOLO

from config import (
    YOLO_MODEL, YOLO_CONFIDENCE, YOLO_IOU_THRESHOLD, YOLO_CLASSES,
    YOLO_CONF_PER_CLASS, OCCUPIER_CLASSES, FURNITURE_CLASSES,
    CHAIR_PROXIMITY_FACTOR,
    ROOM_CAPACITY, ROOM_TABLES, CHAIRS_PER_TABLE,
    LOCAL_TEMP_DIR, ROOM_ID,
    DELETE_AFTER_INFERENCE,
    SAVE_ANNOTATED_IMAGES, ANNOTATED_DIR,
)
from firebase_sync import FirebaseSync
from layout_discovery import discover_layout_from_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# Nomes amigáveis das classes do COCO que tratamos.
CLASS_NAMES = {
    0: "person", 24: "backpack", 26: "handbag", 28: "suitcase",
    39: "bottle", 56: "chair", 57: "couch", 60: "dining_table",
    63: "laptop", 67: "cell_phone", 73: "book",
}


class OccupancyDetector:
    """Pipeline de ocupação por cadeira."""

    def __init__(self):
        logger.info("A inicializar YOLO (%s)…", YOLO_MODEL)
        self.model = YOLO(YOLO_MODEL)
        self.firebase = FirebaseSync()
        Path(LOCAL_TEMP_DIR).mkdir(parents=True, exist_ok=True)

        # Layout: pode estar persistido ou ser descoberto na primeira imagem.
        self.layout: Optional[dict] = self.firebase.get_layout()
        if self.layout:
            logger.info("Layout existente carregado: %d cadeiras / %d mesas.",
                        self.layout.get("chairs_total", 0),
                        self.layout.get("tables_total", 0))
        else:
            logger.info("Sem layout persistido — a próxima imagem será usada "
                        "para descobrir o layout (assume-se sala vazia).")

    # =====================================================================
    # PIPELINE PRINCIPAL
    # =====================================================================
    def detect(self, image_path: str) -> dict:
        img = cv2.imread(image_path)
        if img is None:
            logger.error("Não foi possível ler a imagem: %s", image_path)
            return {"count": -1, "error": "Imagem inválida"}

        # ----- (A) Descoberta de layout, se ainda não existir -----
        if self.layout is None:
            logger.info("A tentar descobrir o layout a partir desta imagem…")
            layout = discover_layout_from_image(image_path, model=self.model)
            if layout is None:
                logger.warning("Descoberta falhou — vou tentar na próxima imagem.")
                return {"count": -1, "error": "Layout pendente"}
            self.firebase.push_layout(layout)
            self.layout = layout
            # Como assumimos que esta imagem é a sala vazia, o estado é "livre"
            # com todas as cadeiras desocupadas.
            return self._build_result(image_path, occupier_dets=[], annotated=None)

        # ----- (B) Inferência normal sobre os ocupadores + mobília (visual) -----
        min_conf = min(YOLO_CONF_PER_CLASS.values()) if YOLO_CONF_PER_CLASS else YOLO_CONFIDENCE
        results = self.model(
            img,
            conf=min_conf,
            iou=YOLO_IOU_THRESHOLD,
            classes=YOLO_CLASSES,
            verbose=False,
        )

        occupier_dets: list[dict] = []
        detections_log: list[dict] = []
        h_img, w_img = img.shape[:2]

        for r in results:
            for box in r.boxes:
                cls  = int(box.cls[0])
                conf = float(box.conf[0])
                cls_thr = YOLO_CONF_PER_CLASS.get(cls, YOLO_CONFIDENCE)
                if conf < cls_thr:
                    continue

                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].cpu().numpy())
                cx_n = ((x1 + x2) / 2.0) / w_img
                cy_n = ((y1 + y2) / 2.0) / h_img
                detections_log.append({
                    "cls":  cls,
                    "conf": round(conf, 3),
                    "box":  [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                })
                if cls in OCCUPIER_CLASSES:
                    occupier_dets.append({
                        "cls": cls, "conf": conf,
                        "cx": cx_n, "cy": cy_n,
                    })

        # Guarda o frame anotado para inspeção visual
        annotated_path = None
        if SAVE_ANNOTATED_IMAGES:
            try:
                Path(ANNOTATED_DIR).mkdir(parents=True, exist_ok=True)
                annotated = results[0].plot()
                annotated_path = Path(ANNOTATED_DIR) / Path(image_path).name
                cv2.imwrite(str(annotated_path), annotated)
            except Exception as e:
                logger.warning("Falha ao gravar imagem anotada: %s", e)

        # Log resumido
        if detections_log:
            for d in detections_log:
                name = CLASS_NAMES.get(d["cls"], str(d["cls"]))
                logger.info("  · %s conf=%.2f box=%s", name, d["conf"], d["box"])

        return self._build_result(image_path, occupier_dets, annotated_path)

    # =====================================================================
    # ATRIBUIÇÃO PER-CADEIRA + AGREGAÇÃO
    # =====================================================================
    def _build_result(self, image_path: str,
                      occupier_dets: list[dict],
                      annotated: Optional[Path]) -> dict:
        layout = self.layout or {}
        chairs = [dict(c) for c in layout.get("chairs", [])]   # cópia rasa
        tables = [dict(t) for t in layout.get("tables", [])]
        for c in chairs:
            c.setdefault("occupied", False)
            c.setdefault("occupied_by", None)
            c.setdefault("occupier_conf", None)

        # Distância média de "perto": fallback se a cadeira não tiver diagonal.
        diags = [c.get("diag") for c in chairs if c.get("diag")]
        mean_diag = sum(diags) / len(diags) if diags else 0.1

        # ----- Atribuir cada deteção à cadeira "vencedora" -----
        # Estratégia: para cada deteção, encontrar a cadeira cujo box contém
        # o centro; se nenhuma contiver, escolher a cadeira mais próxima
        # (distância centro-a-centro < CHAIR_PROXIMITY_FACTOR × diag).
        # Empate: a deteção com maior confiança "vence" a cadeira (não a
        # sobrepõe se já estiver atribuída a alguém com confiança maior).
        # Pessoas têm prioridade sobre objetos (mesma cadeira → person ganha).
        PRIORITY = {0: 3, 63: 2, 73: 2, 24: 2, 26: 2, 28: 2, 67: 1, 39: 1}

        def claim_strength(det: dict) -> float:
            return PRIORITY.get(det["cls"], 1) * 10 + det["conf"]

        # Itera por ordem decrescente de "força" da reivindicação: pessoa
        # com alta confiança primeiro, depois objetos, por fim coisas mais
        # ambíguas como bottle/cell_phone. Como percorremos por essa ordem,
        # a primeira deteção que reivindica uma cadeira é sempre a vencedora
        # — desempates posteriores são ignorados (cadeira já ocupada).
        for det in sorted(occupier_dets, key=claim_strength, reverse=True):
            best_chair = None
            best_score = math.inf
            for ch in chairs:
                if ch["occupied"]:
                    continue   # já reivindicada por uma deteção mais forte
                inside = (ch["x"] <= det["cx"] <= ch["x"] + ch["w"]
                          and ch["y"] <= det["cy"] <= ch["y"] + ch["h"])
                d = math.hypot(ch["cx"] - det["cx"], ch["cy"] - det["cy"])
                limit = CHAIR_PROXIMITY_FACTOR * (ch.get("diag") or mean_diag)
                if not inside and d > limit:
                    continue
                # Quem está "dentro" tem score=0 e vence sempre os "perto".
                score = 0.0 if inside else d
                if score < best_score:
                    best_score = score
                    best_chair = ch
            if best_chair is None:
                continue
            best_chair["occupied"]      = True
            best_chair["occupied_by"]   = CLASS_NAMES.get(det["cls"], str(det["cls"]))
            best_chair["occupier_conf"] = round(det["conf"], 3)

        # ----- Reagregação por mesa + estado global -----
        for t in tables:
            ids = set(t.get("chair_ids", []))
            t["chairs_total"]    = len(ids)
            t["chairs_occupied"] = sum(1 for c in chairs if c["id"] in ids and c["occupied"])
            t["chairs_free"]     = t["chairs_total"] - t["chairs_occupied"]

        chairs_total    = len(chairs) if chairs else ROOM_CAPACITY
        chairs_occupied = sum(1 for c in chairs if c["occupied"])
        chairs_free     = chairs_total - chairs_occupied
        people_count    = sum(1 for d in occupier_dets if d["cls"] == 0)
        occupancy_pct   = round(chairs_occupied / chairs_total * 100, 1) if chairs_total else 0.0

        status = self._classify(tables, chairs_total, chairs_occupied)

        result = {
            "room_id":         ROOM_ID,
            "timestamp":       datetime.now().isoformat(timespec="seconds"),
            "people":          people_count,        # nº de PESSOAS detetadas (alias retro-compat)
            "chairs_total":    chairs_total,
            "chairs_free":     chairs_free,
            "chairs_occupied": chairs_occupied,
            "capacity":        chairs_total,
            "tables":          len(tables) if tables else ROOM_TABLES,
            "occupancy_pct":   occupancy_pct,
            "status":          status,
            "chair_states":    [
                {"id": c["id"], "occupied": c["occupied"], "by": c["occupied_by"]}
                for c in chairs
            ],
            "table_states":    [
                {"id": t["id"],
                 "chairs_total":    t["chairs_total"],
                 "chairs_occupied": t["chairs_occupied"],
                 "chairs_free":     t["chairs_free"]}
                for t in tables
            ],
        }

        logger.info(
            "Sala %s: %d/%d cadeiras ocupadas (%d pessoa(s)) — %s",
            ROOM_ID, chairs_occupied, chairs_total, people_count, status,
        )
        return result

    # =====================================================================
    # CLASSIFICAÇÃO LIVRE/PARCIAL/CHEIO (consumida pelo LED)
    # =====================================================================
    @staticmethod
    def _classify(tables: list[dict], chairs_total: int, chairs_occupied: int) -> str:
        """
        Regras (idênticas em espírito à versão anterior, agora com info per-mesa):

          🟢 livre   — existe pelo menos UMA mesa totalmente vazia
          🟡 parcial — todas as mesas têm gente mas ainda há cadeiras livres
          🔴 cheio   — não há cadeiras livres

        Quando ainda não temos tabelas (early boot), caímos para a heurística
        agregada: livre se 0, parcial se algumas, cheio se todas.
        """
        if chairs_occupied <= 0:
            return "livre"
        if chairs_total > 0 and chairs_occupied >= chairs_total:
            return "cheio"
        if tables:
            any_empty_table = any(t.get("chairs_occupied", 0) == 0
                                  and t.get("chairs_total", 0) > 0
                                  for t in tables)
            return "livre" if any_empty_table else "parcial"
        return "parcial"

    # =====================================================================
    # LOOP
    # =====================================================================
    def process_loop(self, poll_interval: int = 5):
        logger.info("A iniciar loop de processamento para sala '%s'…", ROOM_ID)

        # Se ainda não há layout persistido, ignoramos a imagem que possa
        # estar agora em `latest_image` (pode ser antiga, com pessoas, e
        # estragar a descoberta). Só processamos a PRÓXIMA imagem nova,
        # que o utilizador deve capturar com a sala vazia.
        #
        # Quando já há layout, não há motivo para saltar — continuamos de
        # onde estávamos e processamos o que estiver disponível.
        last_processed = None
        if self.layout is None:
            current = self.firebase.get_latest_image_path()
            if current:
                last_processed = current
                logger.warning(
                    "Layout ainda por descobrir. A imagem atual em `latest_image` "
                    "(%s) vai ser IGNORADA para evitar contaminação. "
                    "Captura uma nova imagem com a SALA VAZIA para o detector "
                    "descobrir o layout.",
                    current,
                )
            else:
                logger.info("Nenhuma imagem em `latest_image` — a aguardar a primeira captura.")

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
