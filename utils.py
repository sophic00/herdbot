import asyncio
import logging
import time

from telethon.tl.types import DocumentAttributeFilename

import config

logger = logging.getLogger(__name__)

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

def get_filename(message) -> str | None:
    """Safely extract filename from a message's document attributes."""
    if not message.media or not message.document:
        return None
    for attr in message.document.attributes:
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
        f"📥 *Downloading file from Telegram...*\n"
        f"`[{bar}] {percent}%`\n"
        f"🔸 *Downloaded:* {rec_str} of {tot_str}\n\n"
        f"To cancel, send: `/cancel {job_id}`"
    )
    await edit_message_throttled(status_msg, progress_text, last_edit_state)
