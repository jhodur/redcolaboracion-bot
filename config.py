import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PROJECT_NAME = os.getenv("PROJECT_NAME", "Entre Montañas")
TIMEZONE = os.getenv("TIMEZONE", "America/Bogota")

DB_PATH = os.getenv("DB_PATH", "gamification.db")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "uploads")
VOUCHERS_DIR = os.getenv("VOUCHERS_DIR", "vouchers")
SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "screenshots")

# Puntos por tipo de interacción
POINTS_LIKE     = 10   # Me gusta
POINTS_SHARE    = 10   # Compartir
POINTS_COMMENT  = 15   # Comentar
POINTS_MIN_REDEEM = 100  # Mínimo para redimir
