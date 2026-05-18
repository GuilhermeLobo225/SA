"""
reset_layout.py — Apaga o layout descoberto para forçar nova descoberta.

Quando muda a posição da câmara ou a disposição da sala, o layout
persistido em `rooms/<id>/layout` deixa de corresponder à realidade e o
matching per-cadeira deixa de bater certo. Este script apaga esse nó para
que o detector volte a fazer descoberta multi-frame na próxima execução
(deixando a sala VAZIA durante as N primeiras frames).

Uso:
    python reset_layout.py                  # apaga layout da sala configurada
    python reset_layout.py --also-current   # apaga também rooms/<id>/occupancy/current
"""

import argparse
import logging

from firebase_admin import db

from config import ROOM_ID
from firebase_sync import FirebaseSync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def reset_layout(also_current: bool = False) -> None:
    sync = FirebaseSync()

    layout_ref = db.reference(f"rooms/{ROOM_ID}/layout", app=sync.sensor_app)
    if layout_ref.get() is None:
        logger.info("Sala '%s' já não tem layout — nada a apagar.", ROOM_ID)
    else:
        layout_ref.delete()
        logger.info("Layout de 'rooms/%s/layout' apagado.", ROOM_ID)

    if also_current:
        current_ref = db.reference(f"rooms/{ROOM_ID}/occupancy/current", app=sync.sensor_app)
        if current_ref.get() is not None:
            current_ref.delete()
            logger.info("Snapshot atual de 'rooms/%s/occupancy/current' apagado.", ROOM_ID)

    logger.info(
        "Pronto. Inicia o detector com a sala VAZIA — ele vai acumular as "
        "primeiras frames para fazer descoberta multi-frame."
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--also-current",
        action="store_true",
        help="Apaga também o snapshot atual de ocupação (rooms/<id>/occupancy/current).",
    )
    args = p.parse_args()
    reset_layout(also_current=args.also_current)
