import logging
import os

from dotenv import load_dotenv

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
GD_INDEX_URL = os.getenv("GD_INDEX_URL", "")
RCLONE_ISOLATE_JOBS = os.getenv("RCLONE_ISOLATE_JOBS", "true").lower() in ("true", "1", "yes")

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Parse authorized user IDs
def get_authorized_users() -> list[int]:
    users_raw = os.getenv("AUTHORIZED_USERS", "")
    if not users_raw:
        return []
    authorized = []
    for u in users_raw.split(","):
        u_clean = u.strip()
        if not u_clean:
            continue
        if u_clean.isdigit():
            authorized.append(int(u_clean))
        else:
            logger.warning(f"Invalid user ID in AUTHORIZED_USERS config: '{u_clean}'")
    return authorized

AUTHORIZED_USERS = set(get_authorized_users())

# Concurrency limits
try:
    MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
except ValueError:
    logger.error("MAX_CONCURRENT_JOBS must be an integer. Falling back to default (2).")
    MAX_CONCURRENT_JOBS = 2
