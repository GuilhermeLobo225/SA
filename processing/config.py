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

# Classes ativas no YOLO. Há TRÊS papéis distintos:
#
#  (1) Mobiliário fixo — usado UMA VEZ no arranque para descobrir o layout
#      da sala (ver processing/layout_discovery.py). Depois disso só serve
#      como sanity-check visual nos frames anotados.
#        56 = chair
#        57 = couch
#        60 = dining_table
#
#  (2) "Ocupadores" — qualquer um destes, ao ser detetado, marca a cadeira
#      mais próxima como ocupada. Resolve o seat hogging (pessoa em pausa
#      mas com mochila na mesa).
#        0  = person
#        24 = backpack
#        26 = handbag
#        28 = suitcase
#        39 = bottle
#        63 = laptop
#        67 = cell phone
#        73 = book
OCCUPIER_CLASSES   = [0, 24, 26, 28, 39, 63, 67, 73]
FURNITURE_CLASSES  = [56, 57, 60]
YOLO_CLASSES = OCCUPIER_CLASSES + FURNITURE_CLASSES

# Filtros por classe APLICADOS DEPOIS da inferência (ver detector.py).
# Pessoa exigente (evita confundir cartazes/sombras). Objetos pequenos com
# threshold mais baixo (saem com confiança menor mesmo quando bem detetados).
# Mobiliário moderado: usado uma vez na descoberta, não vale a pena ser estrito.
YOLO_CONF_PER_CLASS = {
    0:  0.55,   # person
    24: 0.30,   # backpack
    26: 0.30,   # handbag
    28: 0.30,   # suitcase
    39: 0.35,   # bottle
    63: 0.40,   # laptop
    67: 0.40,   # cell phone
    73: 0.35,   # book
    56: 0.25,   # chair        — usado na descoberta de layout
    57: 0.30,   # couch        — idem
    60: 0.25,   # dining_table — idem
}

# Critérios para considerar uma deteção como "estando" numa cadeira.
# A câmara está em ângulo cenital — o que significa que objetos sobre a mesa
# (laptop, livro) aparecem ACIMA do encosto da cadeira na imagem. Por isso
# o critério "centro da deteção dentro do box da cadeira" falha quase sempre.
#
# Em vez disso usamos três sinais combinados:
#
#  1) IoC (Intersection over Chair area): se o box da deteção sobrepõe pelo
#     menos CHAIR_IOC_MIN da área da cadeira, considera-se hit.
#  2) Distância da BOTTOM-CENTER da deteção (o "ponto de assento" virtual)
#     ao centro da cadeira deve ser menor que CHAIR_PROXIMITY_FACTOR vezes
#     a diagonal da cadeira.
#  3) Quando uma deteção (ex.: pessoa) sobrepõe várias cadeiras, escolhe-se
#     a cadeira cujo centro é mais próximo da bottom-center da deteção.
CHAIR_IOC_MIN          = 0.10    # 10% da área da cadeira sobreposta = candidato
CHAIR_PROXIMITY_FACTOR = 1.20    # antes 0.50 — demasiado restrito para ângulo cenital

# Descoberta de layout: em vez de usar uma única frame (que pode ter
# detecções incompletas por variabilidade do YOLO), acumulamos detecções
# de mobiliário ao longo de N frames consecutivos. Boxes próximos (IoU>X)
# são consolidados como uma única entidade, ficando com o representante de
# maior confiança.
LAYOUT_DISCOVERY_FRAMES   = 5     # n.º de frames a acumular antes de persistir
LAYOUT_MERGE_IOU          = 0.45  # IoU mínimo para considerar dois boxes iguais
LAYOUT_CHAIR_MIN_CONF     = 0.20  # baixa este threshold só durante descoberta

# ============================================================
# DeepSORT — REMOVIDO
# ============================================================
# O tracking temporal foi retirado: o intervalo de captura da ESP-CAM (30 s)
# é demasiado esparso para o DeepSORT trazer benefícios (n_init=3 implicava
# 90 s para confirmar uma pessoa, e max_age=30 retinha a track ~15 min depois
# de ela sair). Contagem direta de deteções por frame é mais responsiva.
# Os parâmetros DEEPSORT_* foram removidos; ver detector.py.

# ============================================================
# Capacidade da sala — FALLBACK
# ============================================================
# ⚠️  Em produção, a capacidade REAL vem do layout descoberto pelo detector
#     a partir da primeira imagem da ESP-CAM (ver `layout_discovery.py` e
#     `firebase_sync.get_layout()`). Sempre que existir layout persistido em
#     `rooms/<id>/layout` no Firebase, ele tem prioridade.
#
# As constantes abaixo são apenas usadas como FALLBACK em duas situações:
#   1. Antes da primeira descoberta (boot inicial).
#   2. Pelo `seed_synthetic.py` para gerar dados sintéticos sem dependência
#      do layout real.
#
# Para forçar nova descoberta: DELETE /api/rooms/<id>/layout (ou apagar
# manualmente o nó `rooms/<id>/layout` no Firebase Console).
ROOM_TABLES       = 1        # fallback: nº de mesas
CHAIRS_PER_TABLE  = 4        # fallback: cadeiras por mesa
ROOM_CAPACITY     = ROOM_TABLES * CHAIRS_PER_TABLE   # fallback derivado

# Cenários TÍPICOS (só relevantes para o fallback / seed_synthetic):
#   teste mínimo   : ROOM_TABLES=1, CHAIRS_PER_TABLE=1 → 1 cadeira (binário livre/cheio)
#   teste em casa  : ROOM_TABLES=1, CHAIRS_PER_TABLE=4 → 4 cadeiras
#   biblioteca BG  : ROOM_TABLES=2, CHAIRS_PER_TABLE=4 → 8 cadeiras
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
