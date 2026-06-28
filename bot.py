import os
import re
import time
import shutil
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Constants
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE_NAME", "gdrive")
RCLONE_DEST_DIR = os.getenv("RCLONE_UPLOAD_DIR", "TelegramBotUploads")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Regex patterns for progress parsing
# Matches: [#368305 1.2MiB/20MiB(6%) CN:1 DL:2.1MiB ETA:8s]
ARIA2_PROGRESS_RE = re.compile(
    r"\[#(?P<gid>[a-f0-9]+)\s+(?P<downloaded>[^/]+)/(?P<total>[^\(]+)\((?P<percent>\d+)%\)"
    r".*?DL:(?P<speed>[^\s\]]+)"
    r"(?:\s+ETA:(?P<eta>[^\s\]]+))?\]"
)

# Matches: Transferred:      123.45 MiB / 1.23 GiB, 10%, 15.2 MiB/s, ETA 1m15s
RCLONE_PROGRESS_RE = re.compile(
    r"Transferred:\s+(?P<uploaded>[\d\.]+\s*\w+)\s+/\s+(?P<total>[\d\.]+\s*\w+),\s+(?P<percent>\d+)%,\s+(?P<speed>[\d\.]+\s*\w+/s),\s+ETA\s+(?P<eta>[^\s]+)"
)

def get_authorized_users() -> list[int]:
    """Parse and return list of authorized user IDs."""
    users_raw = os.getenv("AUTHORIZED_USERS", "")
    if not users_raw:
        return []
    return [int(u.strip()) for u in users_raw.split(",") if u.strip().isdigit()]

def is_authorized(user_id: int) -> bool:
    """Check if the user is authorized to use the bot."""
    auth_users = get_authorized_users()
    if not auth_users:
        # If no users specified, allow anyone by default
        return True
    return user_id in auth_users

def make_progress_bar(percent: int) -> str:
    """Generate a visual progress bar string."""
    filled = int(percent / 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty

async def edit_message_throttled(message, text: str, last_edit_state: dict):
    """Edit a message with rate-limiting to prevent Telegram API rate limits."""
    now = time.time()
    # Edit if 3+ seconds elapsed OR if it's the final update
    if now - last_edit_state.get("time", 0) > 3.0 or text.startswith("✅") or text.startswith("❌"):
        if last_edit_state.get("text") == text:
            return  # No need to edit if text is identical
        try:
            await message.edit_text(text, parse_mode="Markdown")
            last_edit_state["time"] = now
            last_edit_state["text"] = text
        except Exception as e:
            logger.debug(f"Failed to edit message: {e}")

async def run_aria2_download(target: str, job_dir: str, status_msg, last_edit_state: dict) -> bool:
    """Run aria2c as a subprocess and stream progress back to Telegram."""
    # Ensure job_dir exists
    os.makedirs(job_dir, exist_ok=True)
    
    cmd = [
        "aria2c",
        f"--dir={job_dir}",
        "--seed-time=0",
        "--summary-interval=1",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        target
    ]
    
    logger.info(f"Starting aria2c download: {cmd}")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    
    metadata_downloading = False
    
    while True:
        line_bytes = await process.stdout.readline()
        if not line_bytes:
            break
        
        line = line_bytes.decode("utf-8", errors="ignore").strip()
        
        # Check progress line matches
        match = ARIA2_PROGRESS_RE.search(line)
        if match:
            groups = match.groupdict()
            downloaded = groups["downloaded"]
            total = groups["total"]
            percent = int(groups["percent"])
            speed = groups["speed"]
            eta = groups.get("eta") or "N/A"
            
            bar = make_progress_bar(percent)
            progress_text = (
                f"📥 *Downloading...*\n"
                f"`[{bar}] {percent}%`\n"
                f"🔸 *Downloaded:* {downloaded} of {total}\n"
                f"🔸 *Speed:* {speed}/s | *ETA:* {eta}"
            )
            await edit_message_throttled(status_msg, progress_text, last_edit_state)
            metadata_downloading = False
        elif "0B/0B" in line or "DL:0B" in line:
            # Handle metadata downloading phase for torrents/magnets
            if not metadata_downloading:
                metadata_downloading = True
                await edit_message_throttled(status_msg, "📥 *Connecting to peers / downloading metadata...*", last_edit_state)
                
    await process.wait()
    return process.returncode == 0

async def run_rclone_upload(source_dir: str, job_id: str, status_msg, last_edit_state: dict) -> bool:
    """Upload job folder contents to Google Drive using rclone."""
    dest_path = f"{RCLONE_REMOTE}:{RCLONE_DEST_DIR}/{job_id}"
    
    # Run rclone move
    cmd = [
        "rclone",
        "move",
        source_dir,
        dest_path,
        "--drive-chunk-size=64M",
        "--stats=1s",
        "-v"
    ]
    
    logger.info(f"Starting rclone move: {cmd}")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    
    while True:
        line_bytes = await process.stdout.readline()
        if not line_bytes:
            break
        
        line = line_bytes.decode("utf-8", errors="ignore").strip()
        match = RCLONE_PROGRESS_RE.search(line)
        if match:
            groups = match.groupdict()
            uploaded = groups["uploaded"]
            total = groups["total"]
            percent = int(groups["percent"])
            speed = groups["speed"]
            eta = groups["eta"]
            
            bar = make_progress_bar(percent)
            progress_text = (
                f"📤 *Uploading to Google Drive...*\n"
                f"`[{bar}] {percent}%`\n"
                f"🔸 *Uploaded:* {uploaded} of {total}\n"
                f"🔸 *Speed:* {speed} | *ETA:* {eta}"
            )
            await edit_message_throttled(status_msg, progress_text, last_edit_state)
            
    await process.wait()
    return process.returncode == 0

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greeting handler."""
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
        
    welcome_text = (
        f"Hi {user.first_name}! 👋\n\n"
        f"I am a Downloader & Uploader Bot. Send me one of the following:\n"
        f"1. A direct download link (http/https)\n"
        f"2. A torrent magnet link (`magnet:...`)\n"
        f"3. A `.torrent` file\n"
        f"4. Any other Telegram file (document, video, audio, etc.)\n\n"
        f"I will download the content to the server, upload it to Google Drive, "
        f"and delete the local copy automatically."
    )
    await update.message.reply_text(welcome_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler for links and files."""
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return

    message = update.message
    job_id = f"{update.effective_chat.id}_{message.message_id}"
    job_dir = os.path.join(DOWNLOAD_DIR, f"job_{job_id}")
    
    target = None
    is_torrent_file = False
    
    # 1. Check if it's a native telegram file
    if message.document:
        doc = message.document
        # Check if it's a .torrent file
        if doc.file_name.lower().endswith(".torrent"):
            is_torrent_file = True
        target = doc
    elif message.video:
        target = message.video
    elif message.audio:
        target = message.audio
    elif message.voice:
        target = message.voice
    # 2. Check if it's text (link or magnet)
    elif message.text:
        text = message.text.strip()
        if text.startswith("http://") or text.startswith("https://") or text.startswith("magnet:"):
            target = text
            
    if not target:
        await update.message.reply_text("❌ Unsupported format. Please send a direct download link, magnet link, .torrent file, or a media file.")
        return

    # Create job directory
    os.makedirs(job_dir, exist_ok=True)
    
    # Send status message
    status_msg = await update.message.reply_text("⏳ *Initializing job...*", parse_mode="Markdown")
    last_edit_state = {"time": time.time(), "text": ""}
    
    try:
        # Download phase
        if isinstance(target, str):
            # Direct link or magnet link
            success = await run_aria2_download(target, job_dir, status_msg, last_edit_state)
        elif is_torrent_file:
            # Download torrent file first to a temp path
            await edit_message_throttled(status_msg, "⏳ *Downloading .torrent file from Telegram...*", last_edit_state)
            tg_file = await context.bot.get_file(target.file_id)
            temp_torrent = os.path.join(DOWNLOAD_DIR, f"temp_{job_id}.torrent")
            await tg_file.download_to_drive(temp_torrent)
            
            # Start aria2 with downloaded torrent file
            success = await run_aria2_download(temp_torrent, job_dir, status_msg, last_edit_state)
            
            # Cleanup temp torrent file
            if os.path.exists(temp_torrent):
                os.remove(temp_torrent)
        else:
            # Generic Telegram file
            await edit_message_throttled(status_msg, "⏳ *Downloading file from Telegram...*", last_edit_state)
            tg_file = await context.bot.get_file(target.file_id)
            
            # Use original file name if document, else fallback
            file_name = getattr(target, "file_name", None) or f"tg_file_{job_id}"
            local_path = os.path.join(job_dir, file_name)
            await tg_file.download_to_drive(local_path)
            success = True
            
        if not success:
            await edit_message_throttled(status_msg, "❌ *Download failed.* Check URL or torrent validity.", last_edit_state)
            shutil.rmtree(job_dir, ignore_errors=True)
            return
            
        # Check if downloaded anything
        downloaded_contents = os.listdir(job_dir)
        if not downloaded_contents:
            await edit_message_throttled(status_msg, "❌ *Download completed, but no files found.*", last_edit_state)
            shutil.rmtree(job_dir, ignore_errors=True)
            return
            
        # Upload phase
        await edit_message_throttled(status_msg, "⏳ *Preparing to upload to Google Drive...*", last_edit_state)
        upload_success = await run_rclone_upload(job_dir, job_id, status_msg, last_edit_state)
        
        if upload_success:
            await edit_message_throttled(
                status_msg, 
                f"✅ *Upload complete!*\n\n"
                f"📂 Folder: `{RCLONE_DEST_DIR}/{job_id}`\n"
                f"🧹 Local files cleaned up successfully.",
                last_edit_state
            )
        else:
            await edit_message_throttled(status_msg, "❌ *Upload to Google Drive failed.*", last_edit_state)
            
    except Exception as e:
        logger.error(f"Error handling job {job_id}: {e}", exc_info=True)
        try:
            await edit_message_throttled(status_msg, f"❌ *An error occurred:* `{str(e)}`", last_edit_state)
        except Exception:
            pass
    finally:
        # Guarantee cleanup of local files
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)

def main():
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return
        
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    
    # Message handlers
    application.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.TEXT,
        handle_message
    ))
    
    logger.info("Bot is starting polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
