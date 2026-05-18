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
    LAYOUT_DISCOVERY_FRAMES, LAYOUT_MERGE_IOU, LAYOUT_CHAIR_MIN_CONF,
)

logger = logging.getLogger(__name__)

CLASS_PERSON       = 0
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
    # Incluímos `person` (0) na inferência para detetar contaminação: se a
    # imagem assumida-vazia tem pessoas, abortamos a descoberta para evitar
    # cadeiras parcialmente tapadas serem perdidas.
    detect_classes = list(FURNITURE_CLASSES) + [CLASS_PERSON]
    # Durante a descoberta baixamos o threshold das cadeiras para
    # LAYOUT_CHAIR_MIN_CONF — queremos apanhar TODAS as cadeiras possíveis,
    # mesmo as menos confiáveis. A acumulação multi-frame depois filtra
    # ruído por consenso.
    min_conf = min(LAYOUT_CHAIR_MIN_CONF,
                   *(YOLO_CONF_PER_CLASS.get(c, 0.25) for c in detect_classes))
    results = model(
        img,
        conf=min_conf,
        iou=YOLO_IOU_THRESHOLD,
        classes=detect_classes,
        verbose=False,
    )

    chairs_px: list[dict] = []
    tables_px: list[dict] = []
    persons_detected = 0

    # Override do threshold per-classe para a descoberta: aceita cadeiras/
    # mesas mesmo com confiança baixa (acumulação multi-frame valida).
    discovery_thresholds = dict(YOLO_CONF_PER_CLASS)
    for c in (CLASS_CHAIR, CLASS_COUCH, CLASS_DINING_TABLE):
        discovery_thresholds[c] = LAYOUT_CHAIR_MIN_CONF

    for r in results:
        for box in r.boxes:
            cls  = int(box.cls[0])
            conf = float(box.conf[0])
            cls_thr = discovery_thresholds.get(cls, 0.25)
            if conf < cls_thr:
                continue

            if cls == CLASS_PERSON:
                persons_detected += 1
                continue   # não entra nem em chairs nem em tables

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

    # Se a imagem assumida-vazia tem pessoas, abortamos: a descoberta exige
    # mobiliário visível e sem oclusões. O caller deve tentar a próxima imagem.
    if persons_detected > 0:
        logger.warning(
            "Imagem tem %d pessoa(s) detetada(s) — descoberta abortada. "
            "Captura uma nova imagem com a SALA VAZIA.",
            persons_detected,
        )
        return None

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
    # Se não houver mesas detetadas, criamos uma "mesa virtual" inflada 25%
    # em volta do bounding box das cadeiras — cobre também a área central
    # onde tipicamente ficam pousados objetos (laptops, livros).
    if not tables:
        if chairs:
            xs = [c["x"] for c in chairs] + [c["x"] + c["w"] for c in chairs]
            ys = [c["y"] for c in chairs] + [c["y"] + c["h"] for c in chairs]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            pad_x = (x_max - x_min) * 0.25
            pad_y = (y_max - y_min) * 0.25
            x_min = max(0.0, x_min - pad_x)
            x_max = min(1.0, x_max + pad_x)
            y_min = max(0.0, y_min - pad_y)
            y_max = min(1.0, y_max + pad_y)
            tables = [{
                "x": x_min, "y": y_min,
                "w": x_max - x_min, "h": y_max - y_min,
                "cx": (x_min + x_max) / 2, "cy": (y_min + y_max) / 2,
                "id": "T1", "chair_ids": [], "virtual": True,
            }]
            logger.info("Mesa não detectada — usada MESA VIRTUAL inflada.")

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


# ============================================================
# Descoberta multi-frame (acumula detecções de N frames)
# ============================================================
def _bbox_iou(a: dict, b: dict) -> float:
    """IoU de dois boxes axis-aligned (formato x, y, w, h)."""
    ix1 = max(a["x"], b["x"])
    iy1 = max(a["y"], b["y"])
    ix2 = min(a["x"] + a["w"], b["x"] + b["w"])
    iy2 = min(a["y"] + a["h"], b["y"] + b["h"])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def _merge_boxes(
    box_lists: list[list[dict]],
    iou_threshold: float,
    min_support: int = 2,
    min_conf_single: float = 0.6,
) -> list[dict]:
    """
    Junta boxes de várias frames: dois boxes são "o mesmo" se IoU >= threshold.
    Cada cluster fica representado pela mediana das coordenadas (mais robusto
    a outliers que a média) e pela maior confiança vista.

    Filtros de aceitação:
      - `min_support`: nº mínimo de frames em que o cluster aparece.
      - `min_conf_single`: confiança mínima quando o cluster aparece em menos
        frames que `min_support`. Permite manter detecções pontuais MAS muito
        confiantes (típico de mesas únicas em ângulo cenital).
    """
    if not box_lists:
        return []
    # Flatten
    flat = [b for frame in box_lists for b in frame]
    if not flat:
        return []

    # Algoritmo guloso simples: percorre por ordem de confiança DESC e
    # agrupa cada box com o cluster existente cujo representante tem IoU
    # acima do threshold; caso contrário cria novo cluster.
    flat_sorted = sorted(flat, key=lambda b: b["conf"], reverse=True)
    clusters: list[list[dict]] = []
    for b in flat_sorted:
        attached = False
        for cluster in clusters:
            if _bbox_iou(cluster[0], b) >= iou_threshold:
                cluster.append(b)
                attached = True
                break
        if not attached:
            clusters.append([b])

    out: list[dict] = []
    for cluster in clusters:
        if len(cluster) == 0:
            continue
        max_conf = max(b["conf"] for b in cluster)
        n = len(cluster)
        # Filtro: aceita se aparecer em ≥min_support frames OU tiver
        # confiança ≥min_conf_single numa única frame.
        if n < min_support and max_conf < min_conf_single:
            continue
        # Mediana de cada coordenada — mais robusto a outliers do que média.
        xs = sorted(b["x"] for b in cluster)
        ys = sorted(b["y"] for b in cluster)
        ws = sorted(b["w"] for b in cluster)
        hs = sorted(b["h"] for b in cluster)
        m = lambda L: L[len(L) // 2]
        x, y, w, h = m(xs), m(ys), m(ws), m(hs)
        out.append({
            "x": x, "y": y, "w": w, "h": h,
            "cx": x + w / 2.0,
            "cy": y + h / 2.0,
            "conf": round(max_conf, 3),
            "support": n,
        })
    return out


def discover_layout_multi_frame(
    image_paths: list[str],
    model: Optional[YOLO] = None,
) -> Optional[dict]:
    """
    Descoberta robusta: corre `discover_layout_from_image` em cada uma das
    `image_paths`, recolhe as detecções de cadeira/mesa em coords ABSOLUTAS
    e funde-as por IoU. O resultado final é normalizado e devolvido na
    mesma estrutura que `discover_layout_from_image`.

    Mais resistente a variabilidade do YOLO: cadeiras que aparecem em
    apenas 1 frame com confiança baixa são descartadas, mas cadeiras
    consistentes (≥2 frames) ou de confiança alta (≥0.6) entram no layout.
    """
    if not image_paths:
        return None

    # 1) Por frame, corre YOLO e guarda boxes em coords PIXEL (sem normalizar).
    if model is None:
        logger.info("A carregar YOLO (%s) para descoberta multi-frame…", YOLO_MODEL)
        model = YOLO(YOLO_MODEL)

    discovery_thresholds = dict(YOLO_CONF_PER_CLASS)
    for c in (CLASS_CHAIR, CLASS_COUCH, CLASS_DINING_TABLE):
        discovery_thresholds[c] = LAYOUT_CHAIR_MIN_CONF
    detect_classes = list(FURNITURE_CLASSES) + [CLASS_PERSON]
    min_conf = min(LAYOUT_CHAIR_MIN_CONF,
                   *(YOLO_CONF_PER_CLASS.get(c, 0.25) for c in detect_classes))

    h_img = w_img = 0
    chair_lists: list[list[dict]] = []
    table_lists: list[list[dict]] = []
    persons_in_any_frame = 0

    for path in image_paths:
        img = cv2.imread(path)
        if img is None:
            logger.warning("Ignorada (não lida): %s", path)
            continue
        h_img, w_img = img.shape[:2]
        results = model(img, conf=min_conf, iou=YOLO_IOU_THRESHOLD,
                        classes=detect_classes, verbose=False)
        frame_chairs: list[dict] = []
        frame_tables: list[dict] = []
        for r in results:
            for box in r.boxes:
                cls = int(box.cls[0]); conf = float(box.conf[0])
                if conf < discovery_thresholds.get(cls, 0.25):
                    continue
                if cls == CLASS_PERSON:
                    persons_in_any_frame += 1
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].cpu().numpy())
                entry = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "conf": conf}
                if cls in (CLASS_CHAIR, CLASS_COUCH):
                    frame_chairs.append(entry)
                elif cls == CLASS_DINING_TABLE:
                    frame_tables.append(entry)
        chair_lists.append(frame_chairs)
        table_lists.append(frame_tables)
        logger.info("Frame %s: %d cadeira(s), %d mesa(s)",
                    path, len(frame_chairs), len(frame_tables))

    if persons_in_any_frame > 0:
        logger.warning(
            "Foram vistas %d pessoa(s) nas %d frames de descoberta — "
            "descoberta abortada. Captura novas frames com SALA VAZIA.",
            persons_in_any_frame, len(image_paths),
        )
        return None

    # Cadeiras: filtro rigoroso (≥2 frames OU conf ≥0.6) — geralmente são
    # várias, queremos consenso entre frames para evitar falsos positivos.
    chairs_px = _merge_boxes(chair_lists, LAYOUT_MERGE_IOU,
                             min_support=2, min_conf_single=0.6)
    # Mesas: filtro permissivo (1 frame com conf ≥LAYOUT_CHAIR_MIN_CONF basta).
    # Justificação: tipicamente só há 1 mesa no campo de visão, é grande, e o
    # YOLO em ângulo cenital perde-a com frequência por estar parcialmente
    # tapada (laptops, livros) — quando aparece, é fiável.
    tables_px = _merge_boxes(table_lists, LAYOUT_MERGE_IOU,
                             min_support=1, min_conf_single=LAYOUT_CHAIR_MIN_CONF)
    logger.info("Após merge: %d cadeira(s), %d mesa(s).", len(chairs_px), len(tables_px))

    if not chairs_px:
        logger.warning("Sem cadeiras consistentes ao longo de %d frame(s).",
                       len(image_paths))
        return None

    # 2) Normaliza + atribui cadeiras a mesas (igual ao single-frame).
    def _norm_box(e: dict) -> dict:
        return {
            "x":  e["x"] / w_img, "y":  e["y"] / h_img,
            "w":  e["w"] / w_img, "h":  e["h"] / h_img,
            "cx": e["cx"] / w_img if "cx" in e else (e["x"] + e["w"] / 2) / w_img,
            "cy": e["cy"] / h_img if "cy" in e else (e["y"] + e["h"] / 2) / h_img,
        }

    chairs = [
        {**_norm_box(c), "id": f"C{i+1}",
         "diag": math.hypot(c["w"] / w_img, c["h"] / h_img),
         "conf": c["conf"], "support": c.get("support", 1)}
        for i, c in enumerate(chairs_px)
    ]
    tables = [
        {**_norm_box(t), "id": f"T{i+1}", "chair_ids": [],
         "conf": t["conf"], "support": t.get("support", 1)}
        for i, t in enumerate(tables_px)
    ]
    if not tables and chairs:
        # Mesa virtual: bounding box das cadeiras INFLADO para cobrir também
        # a área central onde os objetos ficam pousados (laptops, livros).
        # Sem isto, a "mesa" só ocuparia a banda dos encostos e o snap-to-table
        # não apanharia nada que estivesse acima/no meio.
        xs = [c["x"] for c in chairs] + [c["x"] + c["w"] for c in chairs]
        ys = [c["y"] for c in chairs] + [c["y"] + c["h"] for c in chairs]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        # Infla 25% em todas as direções, com clipping a [0, 1].
        pad_x = (x_max - x_min) * 0.25
        pad_y = (y_max - y_min) * 0.25
        x_min = max(0.0, x_min - pad_x)
        x_max = min(1.0, x_max + pad_x)
        y_min = max(0.0, y_min - pad_y)
        y_max = min(1.0, y_max + pad_y)
        tables = [{
            "x": x_min, "y": y_min,
            "w": x_max - x_min, "h": y_max - y_min,
            "cx": (x_min + x_max) / 2, "cy": (y_min + y_max) / 2,
            "id": "T1", "chair_ids": [], "conf": 0.0, "support": 0,
            "virtual": True,
        }]
        logger.info(
            "Mesa não detectada pelo YOLO — usada MESA VIRTUAL (bbox das "
            "cadeiras inflado 25%%) a x=[%.2f,%.2f] y=[%.2f,%.2f].",
            x_min, x_max, y_min, y_max,
        )
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
        "source_image":  image_paths[-1],
        "source_frames": len(image_paths),
        "method":        "multi-frame",
    }
    logger.info(
        "Layout multi-frame: %d cadeira(s) (suporte médio %.1f) em %d mesa(s).",
        layout["chairs_total"],
        sum(c["support"] for c in chairs) / max(1, len(chairs)),
        layout["tables_total"],
    )
    return layout
