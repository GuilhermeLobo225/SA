# config.py — Configurações do sistema de processamento
#
# O sistema usa DOIS projetos Firebase:
#   - VISION-NODE  → Storage (imagens) + RTDB (latest_image path)
#   - SENSOR-NODE  → RTDB (environment + occupancy + LED state)

from pathlib import Path

# ============================================================
# Firebase — Projeto VISION (imagens da ESP32-CAM)
# ============================================================
VISION_CREDENTIALS    = str(Path(__file__).parent / "secrets" / "vision-credentials.json")
VISION_STORAGE_BUCKET = "vision-node-ef817.firebasestorage.app"
VISION_DATABASE_URL   = "https://vision-node-ef817-default-rtdb.europe-west1.firebasedatabase.app"

# ============================================================
# Firebase — Projeto SENSOR (sensores ambientais + ocupação)
# ============================================================
SENSOR_CREDENTIALS    = str(Path(__file__).parent / "secrets" / "sensor-credentials.json")
SENSOR_DATABASE_URL   = "https://sensor-node-da140-default-rtdb.europe-west1.firebasedatabase.app"

# ============================================================
# Sala
# ============================================================
ROOM_ID = "sala_b1_piso2"

# Mapeamento entre os IDs públicos (consumidos pelo website e pela app) e o
# ROOM_ID interno usado no Firebase. Permite que o frontend continue a falar
# em "bg" (Biblioteca Geral) enquanto a infraestrutura usa "sala_b1_piso2".
# Adicionar aqui novas salas piloto à medida que forem instaladas.
PUBLIC_TO_INTERNAL_ROOM_ID = {
    "bg": ROOM_ID,
}
# Inverso, útil para serializar IDs internos em IDs públicos nas respostas.
INTERNAL_TO_PUBLIC_ROOM_ID = {v: k for k, v in PUBLIC_TO_INTERNAL_ROOM_ID.items()}

# ============================================================
# YOLOv8
# ============================================================
YOLO_MODEL = "yolo11x.pt"        # versão extra-large do YOLOv11 — máxima precisão
# Alternativas (do mais leve ao mais pesado):
#   yolo11n.pt  →  ~6 MB, ~50 ms CPU
#   yolo11s.pt  →  ~22 MB
#   yolo11m.pt  →  ~50 MB
#   yolo11l.pt  →  ~90 MB
#   yolo11x.pt  →  ~109 MB, ~1-3 s/imagem em CPU mas máxima accuracy
YOLO_CONFIDENCE = 0.30           # threshold base fallback (classes sem entrada no dict)
YOLO_IOU_THRESHOLD = 0.5

# Classes ativas no YOLO:
#   0  = person        → ÚNICA classe que conta para a ocupação (LED)
#   56 = chair         → DEBUG VISUAL — não entra na contagem
#   57 = couch         → DEBUG VISUAL — não entra na contagem
#   60 = dining_table  → DEBUG VISUAL — não entra na contagem
#
# A capacidade da sala (chairs_total) vem de ROOM_TABLES × CHAIRS_PER_TABLE,
# não da deteção. Isto torna o LED imune a:
#   • cadeiras tapadas por estudantes sentados (oclusão)
#   • cadeiras fantasma em ângulos infelizes (falsos positivos)
#   • estilos de cadeira que o COCO não reconhece bem
# A deteção destas classes serve apenas como sanity-check visual nos frames
# anotados em temp_images/_annotated/.
YOLO_CLASSES = [0, 56, 57, 60]

# Filtros por classe APLICADOS DEPOIS da inferência (ver detector.py).
# Para mobília subimos um pouco o threshold em relação ao mínimo absoluto
# para evitar boxes ruidosas no canto da imagem (já não dependemos delas
# para contagem, portanto não há benefício em ser muito permissivo).
YOLO_CONF_PER_CLASS = {
    0:  0.55,   # person       — exigente (evita confundir cartazes/sombras)
    56: 0.25,   # chair        — moderado (visual; o LED não depende)
    57: 0.30,   # couch        — moderado
    60: 0.25,   # dining_table — moderado
}

# ============================================================
# DeepSORT — REMOVIDO
# ============================================================
# O tracking temporal foi retirado: o intervalo de captura da ESP-CAM (30 s)
# é demasiado esparso para o DeepSORT trazer benefícios (n_init=3 implicava
# 90 s para confirmar uma pessoa, e max_age=30 retinha a track ~15 min depois
# de ela sair). Contagem direta de deteções por frame é mais responsiva.
# Os parâmetros DEEPSORT_* foram removidos; ver detector.py.

# ============================================================
# Capacidade da sala
# ============================================================
# Modelo: cada mesa tem CHAIRS_PER_TABLE cadeiras.
# A capacidade total é derivada: ROOM_CAPACITY = ROOM_TABLES * CHAIRS_PER_TABLE
ROOM_TABLES       = 1        # nº de mesas no campo de visão da ESP-CAM
CHAIRS_PER_TABLE  = 4        # cadeiras por mesa (cenário sala-piloto)
ROOM_CAPACITY     = ROOM_TABLES * CHAIRS_PER_TABLE   # = 4

# Cenários:
#   teste mínimo   : ROOM_TABLES=1, CHAIRS_PER_TABLE=1 → 1 cadeira (binário livre/cheio)
#   teste em casa  : ROOM_TABLES=1, CHAIRS_PER_TABLE=4 → 4 cadeiras
#   biblioteca BG  : ROOM_TABLES=2, CHAIRS_PER_TABLE=4 → 8 cadeiras (cenário atual)
#   maior          : ROOM_TABLES=5, CHAIRS_PER_TABLE=4 → 20 cadeiras

# ============================================================
# API REST
# ============================================================
API_HOST = "0.0.0.0"
API_PORT = 5000

# ============================================================
# Imagens locais
# ============================================================
DELETE_AFTER_INFERENCE = False  # ← True em produção (privacy by design). False para testar.
LOCAL_TEMP_DIR = str(Path(__file__).parent / "temp_images")

# Debug: gravar versão anotada (com bounding boxes) ao lado da original em
# temp_images/_annotated/ — útil para ver O QUE o YOLO está a detectar.
SAVE_ANNOTATED_IMAGES = True
ANNOTATED_DIR = str(Path(__file__).parent / "temp_images" / "_annotated")
