import os
import re
import time
import shutil
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Constants
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if API_ID:
    API_ID = int(API_ID)

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

# Initialize Telethon Client if credentials are provided
if API_ID and API_HASH and BOT_TOKEN:
    bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
else:
    bot = None
    logger.warning("Telegram credentials not fully set. Please configure .env file.")

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

def get_filename(message) -> str:
    """Safely extract filename from a message's document attributes."""
    if not message.media or not message.document:
        return None
    for attr in message.document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return None

async def edit_message_throttled(status_msg, text: str, last_edit_state: dict):
    """Edit a message with rate-limiting to prevent Telegram API rate limits."""
    now = time.time()
    # Edit if 3+ seconds elapsed OR if it's the final update
    if now - last_edit_state.get("time", 0) > 3.0 or text.startswith("✅") or text.startswith("❌"):
        if last_edit_state.get("text") == text:
            return  # No need to edit if text is identical
        try:
            await status_msg.edit(text, parse_mode="Markdown")
            last_edit_state["time"] = now
            last_edit_state["text"] = text
        except Exception as e:
            logger.debug(f"Failed to edit message: {e}")

async def tg_progress_callback(received, total, status_msg, last_edit_state):
    """Progress callback for Telethon media downloads."""
    if not total:
        return
    percent = int(received * 100 / total)
    bar = make_progress_bar(percent)
    
    def format_size(size_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
    
    rec_str = format_size(received)
    tot_str = format_size(total)
    
    progress_text = (
        f"📥 *Downloading file from Telegram...*\n"
        f"`[{bar}] {percent}%`\n"
        f"🔸 *Downloaded:* {rec_str} of {tot_str}"
    )
    await edit_message_throttled(status_msg, progress_text, last_edit_state)

async def run_aria2_download(target: str, job_dir: str, status_msg, last_edit_state: dict) -> bool:
    """Run aria2c as a subprocess and stream progress back to Telegram."""
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
        elif "0B/0B" in line or "DL:0B" in line or "DL:0.00B" in line or "DL:0B/s" in line:
            # Handle metadata downloading phase for torrents/magnets
            if not metadata_downloading:
                metadata_downloading = True
                await edit_message_throttled(status_msg, "📥 *Connecting to peers / downloading metadata...*", last_edit_state)
                
    await process.wait()
    return process.returncode == 0

async def run_rclone_upload(source_dir: str, job_id: str, status_msg, last_edit_state: dict) -> bool:
    """Upload job folder contents to Google Drive using rclone."""
    dest_path = f"{RCLONE_REMOTE}:{RCLONE_DEST_DIR}/{job_id}"
    
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

if bot:
    @bot.on(events.NewMessage)
    async def handle_message(event):
        """Main message handler for links and files."""
        user = await event.get_sender()
        if not user:
            return
            
        if not is_authorized(user.id):
            await event.respond("❌ You are not authorized to use this bot.")
            return

        message = event.message
        
        # 1. Handle `/start` Command
        if message.text and message.text.strip().startswith("/start"):
            welcome_text = (
                f"Hi {user.first_name or 'there'}! 👋\n\n"
                f"I am a Downloader & Uploader Bot. Send me one of the following:\n"
                f"1. A direct download link (http/https)\n"
                f"2. A torrent magnet link (`magnet:...`)\n"
                f"3. A `.torrent` file\n"
                f"4. Any other Telegram file (document, video, audio, etc.)\n\n"
                f"I will download the content to the server, upload it to Google Drive, "
                f"and delete the local copy automatically."
            )
            await event.respond(welcome_text)
            return

        # 2. Determine target of job
        job_id = f"{event.chat_id}_{message.id}"
        job_dir = os.path.join(DOWNLOAD_DIR, f"job_{job_id}")
        
        target = None
        is_torrent_file = False
        filename = get_filename(message)
        
        if message.document:
            if filename and filename.lower().endswith(".torrent"):
                is_torrent_file = True
            target = message.document
        elif message.video:
            target = message.video
        elif message.audio:
            target = message.audio
        elif message.voice:
            target = message.voice
        elif message.text:
            text = message.text.strip()
            if text.startswith("http://") or text.startswith("https://") or text.startswith("magnet:"):
                target = text
                
        if not target:
            # Silent ignore or friendly error if it's text that's not a link
            if message.text and not message.text.startswith("/"):
                await event.respond("❌ Unsupported format. Please send a direct download link, magnet link, .torrent file, or a media file.")
            return

        # Create job directory
        os.makedirs(job_dir, exist_ok=True)
        
        # Send status message
        status_msg = await event.respond("⏳ *Initializing job...*")
        
        # We initialize `time` to 0 so the first edit is never throttled
        last_edit_state = {"time": 0, "text": ""}
        
        try:
            # Download phase
            # Ensure the first download edit is forced
            last_edit_state["time"] = 0
            
            if isinstance(target, str):
                # Direct link or magnet link
                success = await run_aria2_download(target, job_dir, status_msg, last_edit_state)
            elif is_torrent_file:
                # Download torrent file first to a temp path
                await edit_message_throttled(status_msg, "⏳ *Downloading .torrent file from Telegram...*", last_edit_state)
                temp_torrent = os.path.join(DOWNLOAD_DIR, f"temp_{job_id}.torrent")
                
                # Download using telethon progress callback
                last_edit_state["time"] = 0
                await event.client.download_media(
                    target,
                    file=temp_torrent,
                    progress_callback=lambda r, t: tg_progress_callback(r, t, status_msg, last_edit_state)
                )
                
                # Start aria2 with downloaded torrent file
                last_edit_state["time"] = 0
                success = await run_aria2_download(temp_torrent, job_dir, status_msg, last_edit_state)
                
                # Cleanup temp torrent file
                if os.path.exists(temp_torrent):
                    os.remove(temp_torrent)
            else:
                # Generic Telegram file
                # Use original file name if available, else fallback
                file_name = filename or f"tg_file_{job_id}"
                local_path = os.path.join(job_dir, file_name)
                
                # Download using telethon progress callback
                last_edit_state["time"] = 0
                await event.client.download_media(
                    target,
                    file=local_path,
                    progress_callback=lambda r, t: tg_progress_callback(r, t, status_msg, last_edit_state)
                )
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
            # Ensure the first upload edit is forced
            last_edit_state["time"] = 0
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
    if not bot:
        logger.error("Bot client is not initialized due to missing credentials.")
        return
    logger.info("Bot is starting polling/listening...")
    bot.run_until_disconnected()

if __name__ == "__main__":
    main()
