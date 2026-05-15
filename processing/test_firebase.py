"""
Sala de Estudo Inteligente — Teste rápido de Firebase
Sem YOLO, sem DeepSORT. Só valida que:
  1. As credenciais funcionam para os 2 projetos.
  2. Conseguimos ler o caminho da última imagem (Vision).
  3. Conseguimos descarregar essa imagem.
  4. Conseguimos ler os sensores ambientais (Sensor).
  5. Conseguimos escrever um estado de teste em occupancy/status (Sensor).
"""

import json
import logging
import sys

from firebase_sync import FirebaseSync
from config import LOCAL_TEMP_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("test_firebase")


def main() -> int:
    log.info("A inicializar Firebase...")
    sync = FirebaseSync()

    # 1) Última imagem
    log.info("--- Vision: latest_image ---")
    path = sync.get_latest_image_path()
    ts   = sync.get_last_capture_ts()
    log.info("  path: %s", path)
    log.info("  ts  : %s", ts)
    if not path:
        log.error("Não há nenhuma imagem ainda. Confirma que o Vision_NODE está a correr.")
        return 1

    # 2) Download
    log.info("--- Vision: download ---")
    local = sync.download_image(path, LOCAL_TEMP_DIR)
    if not local:
        log.error("Download falhou.")
        return 2
    log.info("  guardada em %s", local)

    # 3) Leitura sensores
    log.info("--- Sensor: environment ---")
    env = sync.get_environment()
    if not env:
        log.warning("Sem dados ambientais (Sensor_NODE talvez ainda não esteja a debitar).")
    else:
        log.info("  %s", json.dumps(env, indent=2, ensure_ascii=False))

    # 4) Escrita de teste
    log.info("--- Sensor: push_led_state('livre') ---")
    sync.push_led_state("livre")
    log.info("  OK. Confere no Firebase Console que rooms/.../occupancy/status = 'livre'.")

    log.info("=== Teste concluído com sucesso ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
