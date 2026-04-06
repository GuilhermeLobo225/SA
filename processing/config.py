# config.py — Configurações do sistema de processamento

# Firebase
FIREBASE_CREDENTIALS = "firebase_credentials.json"  # Service account key
FIREBASE_STORAGE_BUCKET = "YOUR_PROJECT.appspot.com"
FIREBASE_DATABASE_URL = "https://YOUR_PROJECT.firebaseio.com"

# Sala
ROOM_ID = "sala_b1_piso2"

# YOLOv8
YOLO_MODEL = "yolov8n.pt"       # nano (rápido) — alternativas: yolov8s.pt, yolov8m.pt
YOLO_CONFIDENCE = 0.45
YOLO_IOU_THRESHOLD = 0.5
YOLO_CLASSES = [0]              # 0 = person no COCO dataset

# DeepSORT
DEEPSORT_MAX_AGE = 30           # Frames sem deteção antes de remover track
DEEPSORT_N_INIT = 3             # Deteções mínimas para confirmar track
DEEPSORT_MAX_COSINE_DIST = 0.3

# Capacidade da sala
ROOM_CAPACITY = 20

# API
API_HOST = "0.0.0.0"
API_PORT = 5000

# Imagens
DELETE_AFTER_INFERENCE = True    # Eliminar imagem da cloud após inferência
LOCAL_TEMP_DIR = "temp_images"
