import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Core Telegram configuration
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if API_ID:
    try:
        API_ID = int(API_ID)
    except ValueError:
        logger.error("TELEGRAM_API_ID must be an integer.")
        API_ID = None

# Rclone and Storage Configuration
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE_NAME", "gdrive")
RCLONE_DEST_DIR = os.getenv("RCLONE_UPLOAD_DIR", "TelegramBotUploads")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Parse authorized user IDs
def get_authorized_users() -> list[int]:
    users_raw = os.getenv("AUTHORIZED_USERS", "")
    if not users_raw:
        return []
    return [int(u.strip()) for u in users_raw.split(",") if u.strip().isdigit()]

AUTHORIZED_USERS = get_authorized_users()
