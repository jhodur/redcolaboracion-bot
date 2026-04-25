"""
Punto de entrada combinado para producción.
Arranca el API Flask en un hilo y el bot de Telegram en el principal.
"""

import os
import sys
import logging
import threading

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger("start")


def run_api():
    """Arranca Flask en un hilo separado."""
    try:
        from api_stats import app
        port = int(os.getenv("API_PORT", "5055"))
        logger.info(f"API arrancando en puerto {port}")
        # Usar el server de werkzeug en modo no-debug; los recursos son escasos
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logger.exception(f"Error en API: {e}")


def main():
    # Arrancar API en hilo daemon
    api_thread = threading.Thread(target=run_api, daemon=True, name="api")
    api_thread.start()
    logger.info("Hilo API iniciado")

    # Arrancar bot en el hilo principal
    import bot as bot_module
    logger.info("Arrancando bot de Telegram...")
    bot_module.main()


if __name__ == "__main__":
    main()
