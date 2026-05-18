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

# Classes ativas no YOLO. Há QUATRO papéis distintos:
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
#
#  (3) "Distratores" — classes incluídas APENAS na inferência (não em
#      OCCUPIER_CLASSES). Servem para o YOLO conseguir rotular objetos
#      pequenos retangulares (rato, comando, teclado, tigela) na sua
#      classe correta em vez de os forçar a `cell_phone` (que era a única
#      classe pequena disponível e por isso "absorvia" todos os falsos).
#      Estas classes NÃO ocupam cadeiras — só evitam a confusão.
#        64 = mouse        (ratos de computador)
#        65 = remote       (comandos, carregadores parecidos)
#        66 = keyboard     (teclados)
#        41 = cup          (canecas que se confundem com bottle)
#        45 = bowl         (tigelas que se confundem com livro/laptop)
#        62 = tv           (monitores: evita confusão com laptop)
OCCUPIER_CLASSES   = [0, 24, 26, 28, 39, 63, 67, 73]
FURNITURE_CLASSES  = [56, 57, 60]
DISTRACTOR_CLASSES = [41, 45, 62, 64, 65, 66]   # detetadas, mas ignoradas
YOLO_CLASSES = OCCUPIER_CLASSES + FURNITURE_CLASSES + DISTRACTOR_CLASSES

# Filtros por classe APLICADOS DEPOIS da inferência (ver detector.py).
# Pessoa exigente (evita confundir cartazes/sombras). Objetos pequenos com
# threshold mais baixo (saem com confiança menor mesmo quando bem detetados).
#
# Mobília (chair/couch/table): threshold MUITO BAIXO. Em runtime a mobília
# só serve para o desenho debug em temp_images/_annotated/ — a contagem de
# ocupação usa o LAYOUT guardado em rooms/<id>/layout, não as detecções
# em tempo real de cadeiras. Por isso podemos ser permissivos sem afetar
# a precisão da ocupação. Em ângulos cenitais com pouca silhueta visível
# (ex.: sala vazia sem objetos sobre a mesa), o YOLO frequentemente baixa
# a confiança da cadeira para 0.15–0.20 — esse é o piso que aceitamos.
YOLO_CONF_PER_CLASS = {
    # --- ocupadores ---
    # Person: BAIXADO de 0.55 → 0.40. Em ângulo cenital a 2ª pessoa do
    # fundo (parcialmente tapada pela primeira) costuma sair com conf
    # entre 0.40 e 0.60. A 0.55 era frequentemente perdida, fazendo com
    # que a sala reportasse 1 pessoa em vez de 2. O risco de falsos
    # positivos (cartazes, fotografias na parede) é mitigado pelo
    # PERSON_MIN_BBOX_AREA mais abaixo.
    0:  0.40,   # person
    24: 0.35,   # backpack
    26: 0.35,   # handbag
    28: 0.35,   # suitcase
    39: 0.40,   # bottle  (subido — confunde-se com canecas e copos)
    63: 0.45,   # laptop  (subido — confunde-se com livros/tablets)
    # Cell phone: SUBIDO de 0.40 → 0.70. Era a classe responsável pela
    # maior parte dos falsos positivos — carregadores, ratos, comandos
    # e estojos de óculos eram todos rotulados como cell_phone porque
    # era a única classe pequena retangular ativa. Combinado com as
    # DISTRACTOR_CLASSES (mouse/remote/keyboard) e o sanity-check de
    # tamanho no detector, fica drasticamente mais robusto.
    67: 0.70,   # cell phone
    73: 0.40,   # book   (subido — confunde-se com tablets e revistas)

    # --- mobiliário (só debug visual) ---
    56: 0.10,   # chair
    57: 0.15,   # couch
    60: 0.10,   # dining_table

    # --- distratores (detetados para absorver falsos positivos) ---
    # Mantemos thresholds relativamente baixos: queremos que estas
    # classes ABSORVAM rotulações erradas que de outra forma cairiam
    # em cell_phone/laptop/book. Não entram em OCCUPIER_CLASSES, por
    # isso não contam para a ocupação.
    41: 0.25,   # cup
    45: 0.25,   # bowl
    62: 0.30,   # tv / monitor
    64: 0.25,   # mouse
    65: 0.25,   # remote
    66: 0.25,   # keyboard
}

# Sanity-checks de tamanho de bbox (em fração da área da imagem).
# Aplicados no detector DEPOIS da inferência, antes de o ocupador entrar
# na lista para atribuição a cadeira. Detecções fora do intervalo são
# descartadas — protegem contra: pessoas "vistas" em cartazes
# (demasiado pequenas), objetos confundidos com a mesa toda (demasiado
# grandes), e laptops do tamanho de uma bolacha (provavelmente livros).
OCCUPIER_BBOX_LIMITS = {
    0:  (0.010, 0.70),   # person:    >=1.0% e <=70% da imagem
    24: (0.003, 0.30),   # backpack
    26: (0.002, 0.20),   # handbag
    28: (0.005, 0.30),   # suitcase
    39: (0.0005, 0.05),  # bottle:    objeto pequeno
    63: (0.005, 0.35),   # laptop:    objeto médio (ecrã visível)
    67: (0.0008, 0.04),  # cell phone: pequeno e fino, NUNCA enorme
    73: (0.002, 0.15),   # book
}

# Deduplicação entre pessoas: quando dois boxes "person" se sobrepõem
# acima deste IoU, mantemos só o de maior confiança. Protege contra
# o YOLO devolver dois boxes para a mesma pessoa quando ela aparece
# parcialmente tapada (raro, mas acontece em ângulo cenital).
PERSON_DEDUP_IOU = 0.55

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
