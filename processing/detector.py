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
    CHAIR_PROXIMITY_FACTOR, CHAIR_IOC_MIN, LAYOUT_DISCOVERY_FRAMES,
    ROOM_CAPACITY, ROOM_TABLES, CHAIRS_PER_TABLE,
    LOCAL_TEMP_DIR, ROOM_ID,
    DELETE_AFTER_INFERENCE,
    SAVE_ANNOTATED_IMAGES, ANNOTATED_DIR,
)
from firebase_sync import FirebaseSync
from layout_discovery import discover_layout_from_image, discover_layout_multi_frame

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

        # Layout: pode estar persistido ou ser descoberto multi-frame.
        self.layout: Optional[dict] = self.firebase.get_layout()
        # Buffer de imagens para descoberta acumulada. Quando o tamanho
        # atinge LAYOUT_DISCOVERY_FRAMES, fundimos as detecções e persistimos.
        self._discovery_buffer: list[str] = []
        if self.layout:
            logger.info("Layout existente carregado: %d cadeiras / %d mesas.",
                        self.layout.get("chairs_total", 0),
                        self.layout.get("tables_total", 0))
        else:
            logger.info("Sem layout persistido — vão ser acumuladas %d frames "
                        "consecutivas para descoberta multi-frame (sala VAZIA).",
                        LAYOUT_DISCOVERY_FRAMES)

    # =====================================================================
    # PIPELINE PRINCIPAL
    # =====================================================================
    def detect(self, image_path: str) -> dict:
        img = cv2.imread(image_path)
        if img is None:
            logger.error("Não foi possível ler a imagem: %s", image_path)
            return {"count": -1, "error": "Imagem inválida"}

        # ----- (A) Descoberta de layout MULTI-FRAME -----
        # Em vez de descobrir a partir de uma única frame (que pode estar
        # mal exposta ou com confiança baixa), acumulamos
        # LAYOUT_DISCOVERY_FRAMES frames consecutivas e fundimos as
        # detecções por IoU. Mais robusto a variabilidade do YOLO.
        if self.layout is None:
            # Copia a imagem para um path estável (o original será apagado pelo
            # loop após esta função terminar).
            stable_dir = Path(LOCAL_TEMP_DIR) / "_discovery"
            stable_dir.mkdir(parents=True, exist_ok=True)
            stable_path = str(stable_dir / Path(image_path).name)
            try:
                cv2.imwrite(stable_path, img)
                self._discovery_buffer.append(stable_path)
            except Exception as e:
                logger.warning("Falha ao guardar frame para descoberta: %s", e)

            n = len(self._discovery_buffer)
            target = LAYOUT_DISCOVERY_FRAMES
            logger.info("Descoberta em progresso: %d/%d frames acumuladas.", n, target)

            if n < target:
                # Ainda não temos frames suficientes — devolve resultado
                # vazio (não publica nada na API) e espera pela próxima.
                return {"count": -1, "error": "A acumular frames para descoberta"}

            # Buffer cheio — corre descoberta multi-frame.
            logger.info("A correr descoberta multi-frame com %d frames…", target)
            layout = discover_layout_multi_frame(self._discovery_buffer, model=self.model)
            if layout is None:
                logger.warning(
                    "Descoberta falhou (ex.: pessoas em alguma frame). "
                    "A esvaziar buffer e a tentar outra vez."
                )
                self._discovery_buffer.clear()
                return {"count": -1, "error": "Descoberta falhou"}

            self.firebase.push_layout(layout)
            self.layout = layout
            # Limpa as frames temporárias de descoberta
            for p in self._discovery_buffer:
                try: Path(p).unlink()
                except OSError: pass
            self._discovery_buffer.clear()
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
                    # Guardamos o box completo (em coords normalizadas) para
                    # podermos depois calcular IoU/IoC com as cadeiras.
                    occupier_dets.append({
                        "cls": cls, "conf": conf,
                        "x":   x1 / w_img,
                        "y":   y1 / h_img,
                        "w":   (x2 - x1) / w_img,
                        "h":   (y2 - y1) / h_img,
                        "cx":  cx_n,
                        "cy":  cy_n,
                        # bottom-center: o "ponto de assento" virtual.
                        # Para uma pessoa sentada, esta é a coord onde o
                        # rabo encontraria a cadeira; para um objeto sobre
                        # a mesa (laptop), é onde toca o tampo.
                        "bcx": cx_n,
                        "bcy": y2 / h_img,
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
        # Pipeline em DUAS passagens:
        #
        # ┌─ PASSAGEM 1 — pessoas (cls=0) ─────────────────────────────────┐
        # │  Processa pessoas por ordem de confiança. Cada pessoa procura  │
        # │  uma cadeira via 3 estágios:                                   │
        # │    1) IoC (sobreposição box-pessoa × box-cadeira)              │
        # │    2) proximidade da bottom-center                             │
        # │    3) snap-to-table                                            │
        # │  As mesas onde foi atribuída uma pessoa ficam marcadas.        │
        # └────────────────────────────────────────────────────────────────┘
        #
        # ┌─ PASSAGEM 2 — objetos (laptop/book/backpack/…) ────────────────┐
        # │  Processa objetos. Cada objeto pode reivindicar uma cadeira    │
        # │  DIRETAMENTE (IoC sobre o box da cadeira → seat hogging        │
        # │  legítimo: mochila no assento, livro no encosto) MESMO         │
        # │  havendo pessoas perto. MAS o snap-to-table (objeto pousado    │
        # │  no MEIO da mesa) só vale se NÃO houver pessoa nessa mesa —    │
        # │  caso contrário o objeto é "da pessoa" e não conta.            │
        # └────────────────────────────────────────────────────────────────┘
        #
        # Justificação: um portátil ao lado de uma pessoa sentada NÃO é
        # uma cadeira reservada por ele — é da pessoa. Mas uma mochila
        # POUSADA sobre o assento de outra cadeira É reserva ("seat
        # hogging"), mesmo havendo gente na mesa.

        person_dets = sorted(
            (d for d in occupier_dets if d["cls"] == 0),
            key=lambda d: d["conf"], reverse=True,
        )
        object_dets = sorted(
            (d for d in occupier_dets if d["cls"] != 0),
            key=lambda d: d["conf"], reverse=True,
        )

        # IDs de mesas em que foi atribuída pelo menos 1 pessoa.
        tables_with_person: set[str] = set()

        def _match_chair(
            det: dict,
            allow_snap: bool,
            allow_proximity: bool,
            forbidden_table_ids: Optional[set] = None,
        ) -> tuple[Optional[dict], Optional[str]]:
            """Aplica os 3 estágios de matching e devolve (cadeira, descrição).

            `forbidden_table_ids` é a lista de mesas que estão "fora de
            limites" para reivindicações FRACAS (estágios 2 e 3). O estágio
            1 (IoC — objeto fisicamente em cima do assento, seat hogging
            legítimo) NUNCA é bloqueado: uma mochila no assento conta
            mesmo havendo pessoas na mesma mesa.
            """
            forbidden = forbidden_table_ids or set()

            # 1) IoC — sempre disponível, sem filtro de mesa.
            cand = []
            for ch in chairs:
                if ch["occupied"]:
                    continue
                inter = _box_intersection_area(ch, det)
                chair_area = ch["w"] * ch["h"]
                if chair_area <= 0:
                    continue
                ioc = inter / chair_area
                if ioc >= CHAIR_IOC_MIN:
                    d_bc = math.hypot(ch["cx"] - det["bcx"], ch["cy"] - det["bcy"])
                    cand.append((ch, ioc, d_bc))
            if cand:
                cand.sort(key=lambda t: t[2])
                return cand[0][0], f"IoC={cand[0][1]:.2f}"

            # 2) Proximidade — filtra cadeiras de mesas proibidas.
            if allow_proximity:
                best_d, best = math.inf, None
                for ch in chairs:
                    if ch["occupied"]:
                        continue
                    if ch.get("table_id") in forbidden:
                        continue   # esta mesa já tem pessoa
                    d = math.hypot(ch["cx"] - det["bcx"], ch["cy"] - det["bcy"])
                    limit = CHAIR_PROXIMITY_FACTOR * (ch.get("diag") or mean_diag)
                    if d > limit:
                        continue
                    if d < best_d:
                        best_d, best = d, ch
                if best is not None:
                    return best, f"d={best_d:.3f}"

            # 3) Snap-to-table — filtra mesas proibidas.
            if allow_snap:
                for t in tables:
                    if t["id"] in forbidden:
                        continue   # mesa já tem pessoa, objecto é "dela"
                    inside = (t["x"] <= det["bcx"] <= t["x"] + t["w"] and
                              t["y"] <= det["bcy"] <= t["y"] + t["h"])
                    if not inside:
                        continue
                    table_chair_ids = set(t.get("chair_ids", []))
                    candidates = [
                        ch for ch in chairs
                        if not ch["occupied"] and ch["id"] in table_chair_ids
                    ]
                    if not candidates:
                        continue
                    chosen = min(candidates,
                                 key=lambda ch: math.hypot(ch["cx"] - det["bcx"],
                                                            ch["cy"] - det["bcy"]))
                    return chosen, f"table={t['id']}"
            return None, None

        def _claim(det: dict, chair: dict, kind: str) -> None:
            chair["occupied"]      = True
            chair["occupied_by"]   = CLASS_NAMES.get(det["cls"], str(det["cls"]))
            chair["occupier_conf"] = round(det["conf"], 3)
            tid = chair.get("table_id")
            if det["cls"] == 0 and tid:
                tables_with_person.add(tid)
            logger.info(
                "  → %s (conf=%.2f) ocupa %s [%s]",
                CLASS_NAMES.get(det["cls"], str(det["cls"])),
                det["conf"], chair["id"], kind,
            )

        # ===== Passagem 1: pessoas (todos os 3 estágios disponíveis) =====
        for det in person_dets:
            chair, kind = _match_chair(det, allow_snap=True, allow_proximity=True)
            if chair is not None:
                _claim(det, chair, kind)

        # ===== Passagem 2: objetos =====
        # Estágio 1 (IoC, seat hogging) é SEMPRE válido. Estágios 2 e 3
        # (proximidade e snap-to-table) são bloqueados nas mesas que já
        # têm pessoa — nessas mesas, qualquer objeto perto/na mesa é
        # assumido como pertencendo à pessoa e não conta como reserva.
        for det in object_dets:
            chair, kind = _match_chair(
                det,
                allow_snap=True,
                allow_proximity=True,
                forbidden_table_ids=tables_with_person,
            )
            if chair is not None:
                _claim(det, chair, kind)
            else:
                logger.info(
                    "  · %s (conf=%.2f) sem cadeira [proximidade/snap bloqueados ou sem match]",
                    CLASS_NAMES.get(det["cls"], str(det["cls"])), det["conf"],
                )

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


# ----------------------------------------------------------------------
# Helpers geométricos
# ----------------------------------------------------------------------
def _box_intersection_area(a: dict, b: dict) -> float:
    """
    Área da intersecção de dois boxes axis-aligned em coords normalizadas.
    Cada box é um dict com chaves x, y, w, h (top-left + dimensões).
    Devolve 0.0 se não se cruzam.
    """
    ix1 = max(a["x"], b["x"])
    iy1 = max(a["y"], b["y"])
    ix2 = min(a["x"] + a["w"], b["x"] + b["w"])
    iy2 = min(a["y"] + a["h"], b["y"] + b["h"])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


if __name__ == "__main__":
    OccupancyDetector().process_loop()
