"""
Descoberta automática do layout da sala a partir de uma imagem (assumida vazia).

A primeira vez que o detector arranca e não encontra layout persistido em
`rooms/<id>/layout` no Firebase, a próxima imagem capturada é assumida como
sala vazia e passada a `discover_layout_from_image`, que devolve uma estrutura:

    {
      "image_size":   [W, H],                      # pixels
      "tables":  [
        {"id": "T1", "x": 0.21, "y": 0.32, "w": 0.28, "h": 0.18,
         "cx": 0.35, "cy": 0.41, "chair_ids": ["C1","C2","C3","C4"]}
      ],
      "chairs":  [
        {"id": "C1", "x": 0.10, "y": 0.20, "w": 0.08, "h": 0.10,
         "cx": 0.14, "cy": 0.25, "diag": 0.128, "table_id": "T1"}
      ],
      "discovered_at": "2026-05-16T21:00:00",
      "source_image": "/images/123456.jpg"
    }

Todas as coordenadas (x, y, w, h, cx, cy, diag) estão **normalizadas ao
intervalo [0, 1]** relativo ao tamanho da imagem — assim a planta pode ser
reescalada sem reprocessar. As detecções de `couch` (57) são tratadas como
cadeiras para efeitos de assento.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Optional

import cv2
from ultralytics import YOLO

from config import (
    YOLO_MODEL, YOLO_IOU_THRESHOLD, YOLO_CONF_PER_CLASS,
    FURNITURE_CLASSES,
)

logger = logging.getLogger(__name__)

CLASS_CHAIR        = 56
CLASS_COUCH        = 57
CLASS_DINING_TABLE = 60

# Quantos pares (chair_idx, table_idx) candidatos guardamos antes de escolher
# o mais próximo? Limitado para evitar O(N²) em salas muito grandes.
_MAX_CHAIRS_PER_TABLE = 12


def discover_layout_from_image(
    image_path: str,
    model: Optional[YOLO] = None,
) -> Optional[dict]:
    """
    Corre YOLO sobre `image_path`, extrai mobiliário, e devolve o layout
    normalizado. Devolve `None` se nenhuma cadeira for detetada (caso em que
    a chamada deve ser repetida na próxima imagem).

    O parâmetro `model` permite reaproveitar o modelo já carregado pelo
    detector; se None, carregamos um novo (mais lento).
    """
    img = cv2.imread(image_path)
    if img is None:
        logger.error("Não foi possível ler a imagem para descoberta: %s", image_path)
        return None
    h_img, w_img = img.shape[:2]

    if model is None:
        logger.info("A carregar YOLO (%s) para descoberta de layout…", YOLO_MODEL)
        model = YOLO(YOLO_MODEL)

    # Para descoberta de mobília, deixamos o YOLO devolver candidatos com
    # confiança relativamente baixa — filtramos depois por classe.
    min_conf = min(YOLO_CONF_PER_CLASS.get(c, 0.25) for c in FURNITURE_CLASSES)
    results = model(
        img,
        conf=min_conf,
        iou=YOLO_IOU_THRESHOLD,
        classes=FURNITURE_CLASSES,
        verbose=False,
    )

    chairs_px: list[dict] = []
    tables_px: list[dict] = []

    for r in results:
        for box in r.boxes:
            cls  = int(box.cls[0])
            conf = float(box.conf[0])
            cls_thr = YOLO_CONF_PER_CLASS.get(cls, 0.25)
            if conf < cls_thr:
                continue

            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].cpu().numpy())
            entry = {
                "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1,
                "cx": (x1 + x2) / 2.0,
                "cy": (y1 + y2) / 2.0,
                "conf": round(conf, 3),
            }
            if cls in (CLASS_CHAIR, CLASS_COUCH):
                chairs_px.append(entry)
            elif cls == CLASS_DINING_TABLE:
                tables_px.append(entry)

    logger.info("Descoberta: %d cadeira(s)/sofá(s), %d mesa(s) detetada(s).",
                len(chairs_px), len(tables_px))

    if not chairs_px:
        logger.warning("Nenhuma cadeira detetada — descoberta abortada (tentar próxima imagem).")
        return None

    # ---- Normalização ----
    def _norm_box(e: dict) -> dict:
        return {
            "x":   e["x"]  / w_img,
            "y":   e["y"]  / h_img,
            "w":   e["w"]  / w_img,
            "h":   e["h"]  / h_img,
            "cx":  e["cx"] / w_img,
            "cy":  e["cy"] / h_img,
        }

    chairs = [
        {**_norm_box(c), "id": f"C{i+1}",
         "diag": math.hypot(c["w"] / w_img, c["h"] / h_img)}
        for i, c in enumerate(chairs_px)
    ]
    tables = [
        {**_norm_box(t), "id": f"T{i+1}", "chair_ids": []}
        for i, t in enumerate(tables_px)
    ]

    # ---- Atribuir cada cadeira à mesa mais próxima ----
    # Se não houver mesas detetadas, criamos uma "mesa virtual" que cobre o
    # bounding box do conjunto de cadeiras — assim o layout fica consistente.
    if not tables:
        if chairs:
            xs = [c["x"] for c in chairs] + [c["x"] + c["w"] for c in chairs]
            ys = [c["y"] for c in chairs] + [c["y"] + c["h"] for c in chairs]
            tables = [{
                "x": min(xs), "y": min(ys),
                "w": max(xs) - min(xs), "h": max(ys) - min(ys),
                "cx": (min(xs) + max(xs)) / 2,
                "cy": (min(ys) + max(ys)) / 2,
                "id": "T1", "chair_ids": [],
            }]

    for c in chairs:
        best_t = min(tables,
                     key=lambda t: math.hypot(t["cx"] - c["cx"], t["cy"] - c["cy"]))
        c["table_id"] = best_t["id"]
        if len(best_t["chair_ids"]) < _MAX_CHAIRS_PER_TABLE:
            best_t["chair_ids"].append(c["id"])

    layout = {
        "image_size":    [w_img, h_img],
        "tables":        tables,
        "chairs":        chairs,
        "chairs_total":  len(chairs),
        "tables_total":  len(tables),
        "discovered_at": datetime.now().isoformat(timespec="seconds"),
        "source_image":  image_path,
    }
    logger.info("Layout descoberto: %d cadeiras em %d mesa(s).",
                layout["chairs_total"], layout["tables_total"])
    return layout
