import asyncio
import json
import logging
import os
import time

from telethon.tl.types import DocumentAttributeFilename

import bencode
import config

# Bot start time for uptime tracking
bot_start_time = time.time()

# Stats file path
STATS_FILE = os.path.join('session', 'stats.json')

logger = logging.getLogger(__name__)

def load_stats() -> dict:
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE) as f:
                data = json.load(f)
                return {
                    "total_downloaded": data.get("total_downloaded", 0),
                    "total_uploaded": data.get("total_uploaded", 0)
                }
        except Exception as e:
            logger.error(f"Error loading stats file: {e}")
    return {"total_downloaded": 0, "total_uploaded": 0}

def save_stats(stats: dict):
    try:
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, 'w') as f:
            json.dump(stats, f)
    except Exception as e:
        logger.error(f"Error saving stats file: {e}")

# Global cache for in-memory tracking
_stats_cache = load_stats()

def add_download_stats(size_bytes: int):
    global _stats_cache
    _stats_cache["total_downloaded"] += size_bytes
    save_stats(_stats_cache)

def add_upload_stats(size_bytes: int):
    global _stats_cache
    _stats_cache["total_uploaded"] += size_bytes
    save_stats(_stats_cache)

def get_total_stats() -> tuple[int, int]:
    global _stats_cache
    return _stats_cache["total_downloaded"], _stats_cache["total_uploaded"]

def get_uptime_string() -> str:
    uptime_seconds = int(time.time() - bot_start_time)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    
    return " ".join(parts)

# Selection sessions registry
# Structure: { job_id: { "files": list, "current_dir": tuple, "dir_map": dict, "id_map": dict, "msg_id": int, ... } }
selection_sessions = {}

# Queue registry for concurrency control
# List of dicts representing job execution contexts
job_queue = []

# Shared Global Jobs registry
# Structure: { job_id: { "user": str, "name": str, "status": str, "percent": int, "speed": str, "eta": str, "phase": str } }
active_jobs = {}

def make_progress_bar(percent: int) -> str:
    """Generate a visual progress bar string."""
    filled = int(percent / 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty

def format_size(size_bytes: float) -> str:
    """Convert size in bytes to a human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

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

def is_authorized(user_id: int) -> bool:
    """Check if the user ID is in the authorized list."""
    if not config.AUTHORIZED_USERS:
        return True
    return user_id in config.AUTHORIZED_USERS

def get_filename(obj) -> str | None:
    """Safely extract filename from a message's document attributes or a document object."""
    if not obj:
        return None
    
    if hasattr(obj, 'document'):
        document = obj.document
    else:
        document = obj
        
    if not document or not hasattr(document, 'attributes'):
        return None
        
    for attr in document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return None

async def tg_progress_callback(received: int, total: int, status_msg, last_edit_state: dict, job_id: str):
    """Progress callback for Telethon media downloads with cancellation support."""
    if not total:
        return
        
    # Check if job was cancelled
    if job_id in active_jobs and active_jobs[job_id].get("cancelled"):
        raise asyncio.CancelledError("Download cancelled by user")
        
    percent = int(received * 100 / total)
    bar = make_progress_bar(percent)
    
    rec_str = format_size(received)
    tot_str = format_size(total)
    
    progress_text = (
        f"📥 **Downloading file from Telegram...**\n"
        f"`[{bar}] {percent}%`\n"
        f"🔸 **Downloaded:** {rec_str} of {tot_str}\n\n"
        f"To cancel, send: `/cancel {job_id}`"
    )
    await edit_message_throttled(status_msg, progress_text, last_edit_state)

def parse_torrent_files(torrent_path: str) -> tuple[str, list[dict]]:
    """Parse a bencoded torrent file and extract root folder name and file list."""
    with open(torrent_path, 'rb') as f:
        data = f.read()
    
    torrent = bencode.bdecode(data)
    if not isinstance(torrent, dict):
        raise ValueError("Invalid torrent file structure")
    info = torrent.get('info', {})
    if not isinstance(info, dict):
        raise ValueError("Invalid torrent file structure")
    
    root_name = info.get('name', b'').decode('utf-8', errors='ignore')
    
    files_list = []
    if 'files' in info:
        # Multi-file torrent
        for idx, file_info in enumerate(info['files'], start=1):
            path_components = [p.decode('utf-8', errors='ignore') for p in file_info.get('path', [])]
            length = file_info.get('length', 0)
            files_list.append({
                "index": idx,
                "path": path_components,
                "size": length,
                "selected": True
            })
    else:
        # Single-file torrent
        length = info.get('length', 0)
        files_list.append({
            "index": 1,
            "path": [root_name],
            "size": length,
            "selected": True
        })
        
    return root_name, files_list

def get_running_jobs_count() -> int:
    """Returns the number of active jobs currently running (not in 'Queued' phase)."""
    return sum(1 for j in active_jobs.values() if j.get("phase") != "Queued")
