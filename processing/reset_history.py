"""
Apaga o histórico do Firebase para começar uma recolha limpa.

Por defeito apaga:
  - rooms/<ROOM_ID>/environment/history   (Sensor-NODE)
  - rooms/<ROOM_ID>/occupancy/history     (Sensor-NODE)

NÃO apaga `current` — o firmware do LED depende disso. Se apagares ficaria em
"sem dados" até à próxima leitura.

Uso:
    python reset_history.py                  # apaga histórico (com confirmação)
    python reset_history.py --yes            # sem prompt (CUIDADO)
    python reset_history.py --include-images # também apaga imagens do Storage
"""

import argparse
import logging
import sys

from firebase_admin import db, storage

from config import ROOM_ID, VISION_STORAGE_BUCKET
from firebase_sync import FirebaseSync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reset_history")


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes", "s", "sim")


def main(skip_prompt: bool, include_images: bool) -> int:
    sync = FirebaseSync()
    log.info("Sala: %s", ROOM_ID)

    targets = [
        ("environment/history", "ambiente", sync.sensor_app),
        ("occupancy/history",   "ocupação", sync.sensor_app),
    ]

    if not skip_prompt:
        log.info("Vai apagar:")
        for path, label, _ in targets:
            log.info("  • rooms/%s/%s  (%s)", ROOM_ID, path, label)
        if include_images:
            log.info("  • Storage: dados_camara/%s/  (imagens da ESP-CAM)", ROOM_ID)
        log.info("Não apaga: rooms/.../environment/current nem .../occupancy/current.")
        if not confirm("Continuar?"):
            log.info("Cancelado.")
            return 1

    # Apagar histórico no RTDB
    for path, label, app in targets:
        full = f"rooms/{ROOM_ID}/{path}"
        ref = db.reference(full, app=app)
        try:
            ref.delete()
            log.info("✓ Apagado: %s", full)
        except Exception as e:
            log.error("✗ Erro a apagar %s: %s", full, e)

    # Apagar imagens
    if include_images:
        try:
            bucket = storage.bucket(VISION_STORAGE_BUCKET, app=sync.vision_app)
            prefix = f"dados_camara/{ROOM_ID}/"
            blobs = list(bucket.list_blobs(prefix=prefix))
            log.info("Storage: %d imagens em %s", len(blobs), prefix)
            for b in blobs:
                b.delete()
            log.info("✓ Imagens apagadas")
        except Exception as e:
            log.error("✗ Erro a apagar imagens: %s", e)

    log.info("Reset concluído. Os nós ESP32 e o detector.py continuam a correr —")
    log.info("o histórico vai começar a regenerar nos próximos 30 segundos.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="Saltar a confirmação interactiva")
    ap.add_argument("--include-images", action="store_true",
                    help="Apagar também as imagens em Storage")
    args = ap.parse_args()
    sys.exit(main(args.yes, args.include_images))
