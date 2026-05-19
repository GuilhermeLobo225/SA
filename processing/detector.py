"""
Sala de Estudo Inteligente — Pipeline de Deteção (per-mesa, auto-discovery)

Fluxo:
  1. No arranque:
       a. Tenta carregar layout persistido em `rooms/<id>/layout` (Firebase).
       b. Se não houver, entra em modo DISCOVERY: acumula `LAYOUT_DISCOVERY_FRAMES`
          frames (assumidas sala vazia), corre `discover_layout_multi_frame`
          para identificar as mesas via YOLO (classe `dining_table`), e
          persiste o resultado. Câmara estática ⇒ corre uma vez e basta.
       c. `ROOM_TABLE_POSITIONS` em config.py funciona como OVERRIDE manual:
          se não estiver vazio, ignora descoberta e usa hardcoded.

  2. Em runtime:
       - Corre YOLO sobre pessoas + ocupadores.
       - Atribui cada deteção à MESA MAIS PRÓXIMA pela bottom-center da bbox.
       - Deteções a mais de `TABLE_MAX_ASSIGN_DIST` da mesa mais próxima
         são descartadas (gente em circulação).
       - Regras de estado por mesa:
            • pessoas > 0  → ocupação = pessoas (ignora objetos)
            • só objetos   → "parcial" (seat hogging)
            • vazio        → "livre"
            • ocupação ≥ capacidade → "cheio"
       - Agrega para a sala — alimenta o LED RGB e os badges.
"""

import os
import math
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
    ROOM_CAPACITY, ROOM_TABLES, CHAIRS_PER_TABLE,
    ROOM_TABLE_POSITIONS, TABLE_MAX_ASSIGN_DIST,
    LAYOUT_DISCOVERY_FRAMES,
    LOCAL_TEMP_DIR, ROOM_ID,
    DELETE_AFTER_INFERENCE,
    SAVE_ANNOTATED_IMAGES, ANNOTATED_DIR,
)
from firebase_sync import FirebaseSync
from layout_discovery import discover_layout_multi_frame

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


CLASS_NAMES = {
    0: "person", 24: "backpack", 26: "handbag", 28: "suitcase",
    39: "bottle", 56: "chair", 57: "couch", 60: "dining_table",
    63: "laptop", 67: "cell_phone", 73: "book",
}


def _tables_from_layout(layout: dict) -> list[dict]:
    """
    Converte a estrutura devolvida por `discover_layout_multi_frame` (ou
    persistida em `rooms/<id>/layout`) numa lista [{id, cx, cy, capacity}, …]
    consumível pelo OccupancyDetector.

    A capacidade de cada mesa é o nº de cadeiras que lhe foram atribuídas
    durante a descoberta (`chair_ids`). Se for 0 (YOLO não viu as cadeiras
    mas viu a mesa), cai para `CHAIRS_PER_TABLE` do config.
    """
    tables = []
    for t in layout.get("tables", []):
        cap = len(t.get("chair_ids", [])) or CHAIRS_PER_TABLE
        tables.append({
            "id":       t["id"],
            "cx":       float(t["cx"]),
            "cy":       float(t["cy"]),
            "capacity": cap,
        })
    return tables


def _tables_from_hardcoded() -> list[dict]:
    """Lista de mesas a partir de `ROOM_TABLE_POSITIONS` (override manual)."""
    return [
        {"id": f"T{i+1}", "cx": float(cx), "cy": float(cy),
         "capacity": CHAIRS_PER_TABLE}
        for i, (cx, cy) in enumerate(ROOM_TABLE_POSITIONS)
    ]


class OccupancyDetector:
    """Pipeline de ocupação per-mesa com descoberta automática de layout."""

    def __init__(self):
        logger.info("A inicializar YOLO (%s)…", YOLO_MODEL)
        self.model = YOLO(YOLO_MODEL)
        self.firebase = FirebaseSync()
        Path(LOCAL_TEMP_DIR).mkdir(parents=True, exist_ok=True)

        # ----- Resolução do layout -----
        # Prioridade: override hardcoded > layout persistido > descoberta.
        self.tables_cfg: Optional[list[dict]] = None
        self._discovery_buffer: list[str] = []   # paths de frames a acumular

        if ROOM_TABLE_POSITIONS:
            self.tables_cfg = _tables_from_hardcoded()
            logger.info(
                "Override manual ativo: %d mesa(s) hardcoded em config.py.",
                len(self.tables_cfg),
            )
        else:
            layout = self.firebase.get_layout()
            if layout and layout.get("tables"):
                self.tables_cfg = _tables_from_layout(layout)
                logger.info(
                    "Layout carregado do Firebase: %d mesa(s) (descoberto a %s).",
                    len(self.tables_cfg), layout.get("discovered_at", "?"),
                )
            else:
                logger.warning(
                    "Sem layout persistido. A entrar em modo DISCOVERY — vou "
                    "acumular as próximas %d frame(s) (SALA VAZIA) para "
                    "identificar as mesas via YOLO.",
                    LAYOUT_DISCOVERY_FRAMES,
                )

        if self.tables_cfg is not None:
            self._log_tables()

    def _log_tables(self):
        logger.info(
            "Sala '%s': %d mesa(s) configurada(s). Centroides + capacidade: %s",
            ROOM_ID, len(self.tables_cfg),
            [(t["id"], round(t["cx"], 3), round(t["cy"], 3), t["capacity"])
             for t in self.tables_cfg],
        )

    # ===================================================================
    # DISCOVERY (modo inicial — sala vazia)
    # ===================================================================
    def _try_discovery(self) -> bool:
        """
        Corre `discover_layout_multi_frame` sobre `self._discovery_buffer`.
        Devolve True se a descoberta tiver sucesso (mesas encontradas).
        Em caso de falha (pessoas na frame, sem cadeiras), limpa o buffer
        para tentar com as próximas N frames.
        """
        layout = discover_layout_multi_frame(
            self._discovery_buffer, model=self.model
        )
        if not layout or not layout.get("tables"):
            logger.warning(
                "Descoberta falhou nas %d frame(s) acumuladas. A repetir "
                "com novo lote.",
                len(self._discovery_buffer),
            )
            self._discovery_buffer.clear()
            return False

        # Persiste no Firebase + configura este detector
        self.firebase.push_layout(layout)
        self.tables_cfg = _tables_from_layout(layout)
        self._discovery_buffer.clear()
        logger.info("✓ Descoberta concluída e persistida.")
        self._log_tables()
        return True

    # ===================================================================
    # ATRIBUIÇÃO PER-MESA
    # ===================================================================
    def _nearest_table(self, bx: float, by: float) -> Optional[dict]:
        """Mesa cujo centroide está mais próximo de (bx, by), com cutoff."""
        if not self.tables_cfg:
            return None
        best = min(
            self.tables_cfg,
            key=lambda t: math.hypot(t["cx"] - bx, t["cy"] - by),
        )
        dist = math.hypot(best["cx"] - bx, best["cy"] - by)
        if dist > TABLE_MAX_ASSIGN_DIST:
            return None
        return best

    # ===================================================================
    # PIPELINE PRINCIPAL
    # ===================================================================
    def detect(self, image_path: str) -> dict:
        img = cv2.imread(image_path)
        if img is None:
            logger.error("Não foi possível ler a imagem: %s", image_path)
            return {"chairs_total": -1, "error": "Imagem inválida"}
        h_img, w_img = img.shape[:2]

        min_conf = (min(YOLO_CONF_PER_CLASS.values())
                    if YOLO_CONF_PER_CLASS else YOLO_CONFIDENCE)
        results = self.model(
            img, conf=min_conf, iou=YOLO_IOU_THRESHOLD,
            classes=YOLO_CLASSES, verbose=False,
        )

        per_table = {
            t["id"]: {
                "id": t["id"], "cx": t["cx"], "cy": t["cy"],
                "capacity": t["capacity"], "people": 0, "objects": 0,
            }
            for t in self.tables_cfg
        }
        discarded_people = discarded_objects = 0
        person_count_total = object_count_total = 0
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
                    "box": [round(x1, 1), round(y1, 1),
                            round(x2, 1), round(y2, 1)],
                })

                if cls != 0 and cls not in OCCUPIER_CLASSES:
                    continue

                # Bottom-center da bbox em coords normalizadas — robusto
                # sob ângulo lateral (câmara num canto da sala).
                bx = ((x1 + x2) / 2.0) / w_img
                by = ((y1 + y2) / 2.0) / h_img
                table = self._nearest_table(bx, by)

                if cls == 0:
                    person_count_total += 1
                    if table is None:
                        discarded_people += 1
                    else:
                        per_table[table["id"]]["people"] += 1
                else:
                    object_count_total += 1
                    if table is None:
                        discarded_objects += 1
                    else:
                        per_table[table["id"]]["objects"] += 1

        # ----- Imagem anotada (debug) -----
        if SAVE_ANNOTATED_IMAGES:
            try:
                Path(ANNOTATED_DIR).mkdir(parents=True, exist_ok=True)
                annotated = results[0].plot()
                annotated_path = Path(ANNOTATED_DIR) / Path(image_path).name
                cv2.imwrite(str(annotated_path), annotated)
            except Exception as e:
                logger.warning("Falha ao gravar imagem anotada: %s", e)

        for d in detections_log:
            name = CLASS_NAMES.get(d["cls"], str(d["cls"]))
            logger.info("  · %s conf=%.2f box=%s",
                        name, d["conf"], d["box"])

        # ----- Regras de ocupação per-mesa -----
        tables_state: list[dict] = []
        for tid in sorted(per_table.keys()):
            e   = per_table[tid]
            cap = e["capacity"]
            if e["people"] > 0:
                occ = min(e["people"], cap)
                st  = "cheio" if occ >= cap else "parcial"
            elif e["objects"] > 0:
                # Seat hogging: status sempre "parcial" — não há ninguém
                # fisicamente sentado, é apenas reserva.
                occ = min(e["objects"], cap)
                st  = "parcial"
            else:
                occ = 0; st = "livre"
            tables_state.append({
                "id": tid, "capacity": cap, "occupied": occ,
                "free": cap - occ, "people": e["people"],
                "objects": e["objects"], "status": st,
            })

        chairs_total    = sum(ts["capacity"] for ts in tables_state)
        chairs_occupied = sum(ts["occupied"] for ts in tables_state)
        chairs_free     = chairs_total - chairs_occupied
        occupancy_pct   = (round(chairs_occupied / chairs_total * 100, 1)
                           if chairs_total else 0.0)

        if chairs_occupied <= 0:
            status = "livre"
        elif chairs_occupied >= chairs_total:
            status = "cheio"
        else:
            status = "parcial"

        result = {
            "room_id":          ROOM_ID,
            "timestamp":        datetime.now().isoformat(timespec="seconds"),
            "people":           person_count_total,
            "objects":          object_count_total,
            "chairs_total":     chairs_total,
            "chairs_free":      chairs_free,
            "chairs_occupied":  chairs_occupied,
            "capacity":         chairs_total,
            "tables":           len(tables_state),
            "occupancy_pct":    occupancy_pct,
            "status":           status,
            "tables_state":     tables_state,
            "discarded_people":  discarded_people,
            "discarded_objects": discarded_objects,
            # Campos legados.
            "chair_states":     [],
            "table_states":     tables_state,
        }

        logger.info(
            "Sala %s: %d/%d ocupadas (%s) | total %d pessoa(s), "
            "%d objeto(s) (descartados: %dp / %do)",
            ROOM_ID, chairs_occupied, chairs_total, status,
            person_count_total, object_count_total,
            discarded_people, discarded_objects,
        )
        for ts in tables_state:
            logger.info("  - %s: %d/%d (%s) — %dp + %do",
                        ts["id"], ts["occupied"], ts["capacity"],
                        ts["status"], ts["people"], ts["objects"])
        return result

    # ===================================================================
    # LOOP
    # ===================================================================
    def process_loop(self, poll_interval: int = 5):
        logger.info("A iniciar loop de processamento para sala '%s'…", ROOM_ID)
        last_processed = None

        while True:
            try:
                latest = self.firebase.get_latest_image_path()
                if latest and latest != last_processed:
                    logger.info("Nova imagem detetada: %s", latest)

                    local_path = self.firebase.download_image(
                        latest, LOCAL_TEMP_DIR)
                    if local_path:
                        # --- Modo DISCOVERY ---
                        if self.tables_cfg is None:
                            self._discovery_buffer.append(local_path)
                            logger.info(
                                "Frame %d/%d acumulada para descoberta de "
                                "layout.",
                                len(self._discovery_buffer),
                                LAYOUT_DISCOVERY_FRAMES,
                            )
                            if len(self._discovery_buffer) >= LAYOUT_DISCOVERY_FRAMES:
                                self._try_discovery()
                                # Mesmo que falhe, limpa as imagens locais.
                                self._cleanup_buffer()

                        # --- Modo NORMAL (layout pronto) ---
                        else:
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

    def _cleanup_buffer(self):
        """Apaga as imagens locais que foram para o buffer de descoberta."""
        for p in self._discovery_buffer:
            try: os.remove(p)
            except OSError: pass
        self._discovery_buffer.clear()


if __name__ == "__main__":
    OccupancyDetector().process_loop()
