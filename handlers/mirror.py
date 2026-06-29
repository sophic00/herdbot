import logging
import os
import re
import shutil
import urllib.parse

import config
import utils
from downloaders.aria2 import run_aria2_download
from downloaders.rclone import run_rclone_upload

logger = logging.getLogger(__name__)

async def mirror_handler(event):
    """Main callback to handle link and file download/uploads."""
    user = await event.get_sender()
    if not user:
        return
        
    if not utils.is_authorized(user.id):
        await event.respond("❌ You are not authorized to use this bot.")
        return

    message = event.message
    
    # Ignore messages starting with slash (command routing)
    if message.text and message.text.strip().startswith("/"):
        return

    job_id = f"{event.chat_id}_{message.id}"
    job_dir = os.path.join(config.DOWNLOAD_DIR, f"job_{job_id}")
    
    target = None
    is_torrent_file = False
    filename = utils.get_filename(message)
    
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
        if message.text and not message.text.startswith("/"):
            await event.respond("❌ Unsupported format. Please send a direct download link, magnet link, .torrent file, or a media file.")
        return

    # Determine job display name
    user_display = user.first_name or f"User {user.id}"
    if filename:
        job_name = filename
    elif isinstance(target, str):
        if target.startswith("magnet:"):
            # Try to extract the display name 'dn' parameter from magnet link
            match = re.search(r"dn=([^&]+)", target)
            if match:
                job_name = urllib.parse.unquote(match.group(1))
            else:
                job_name = f"Torrent_Magnet_{job_id}"
        else:
            job_name = target.split("/")[-1] or f"DirectLink_{job_id}"
    else:
        job_name = f"Telegram_Media_{job_id}"

    # Register in global state
    utils.active_jobs[job_id] = {
        "user": user_display,
        "name": job_name,
        "phase": "Initializing",
        "percent": 0,
        "speed": "0 B/s",
        "eta": "N/A"
    }

    # Create job directory
    os.makedirs(job_dir, exist_ok=True)
    status_msg = await event.respond("⏳ *Initializing job...*")
    last_edit_state = {"time": 0, "text": ""}
    
    try:
        success = False
        
        # Download phase
        if isinstance(target, str):
            # Direct link or magnet link
            success = await run_aria2_download(target, job_dir, job_id, status_msg, last_edit_state)
        elif is_torrent_file:
            # Download torrent file first to a temp path
            await utils.edit_message_throttled(status_msg, "⏳ *Downloading .torrent file from Telegram...*", last_edit_state)
            temp_torrent = os.path.join(config.DOWNLOAD_DIR, f"temp_{job_id}.torrent")
            
            # Download using telethon progress callback
            last_edit_state["time"] = 0
            if job_id in utils.active_jobs:
                utils.active_jobs[job_id]["phase"] = "Downloading Telegram File"
                
            await event.client.download_media(
                target,
                file=temp_torrent,
                progress_callback=lambda r, t: utils.tg_progress_callback(r, t, status_msg, last_edit_state)
            )
            
            # Start aria2 with downloaded torrent file
            last_edit_state["time"] = 0
            success = await run_aria2_download(temp_torrent, job_dir, job_id, status_msg, last_edit_state)
            
            # Cleanup temp torrent file
            if os.path.exists(temp_torrent):
                os.remove(temp_torrent)
        else:
            # Generic Telegram file
            local_path = os.path.join(job_dir, job_name)
            
            # Download using telethon progress callback
            last_edit_state["time"] = 0
            if job_id in utils.active_jobs:
                utils.active_jobs[job_id]["phase"] = "Downloading Telegram File"
                
            await event.client.download_media(
                target,
                file=local_path,
                progress_callback=lambda r, t: utils.tg_progress_callback(r, t, status_msg, last_edit_state)
            )
            success = True
            
        if not success:
            await utils.edit_message_throttled(status_msg, "❌ *Download failed.* Check URL or torrent validity.", last_edit_state)
            shutil.rmtree(job_dir, ignore_errors=True)
            return
            
        # Check if downloaded anything
        downloaded_contents = os.listdir(job_dir)
        if not downloaded_contents:
            await utils.edit_message_throttled(status_msg, "❌ *Download completed, but no files found.*", last_edit_state)
            shutil.rmtree(job_dir, ignore_errors=True)
            return
            
        # Upload phase
        last_edit_state["time"] = 0
        await utils.edit_message_throttled(status_msg, "⏳ *Preparing to upload to Google Drive...*", last_edit_state)
        
        upload_success = await run_rclone_upload(job_dir, job_id, status_msg, last_edit_state)
        
        if upload_success:
            await utils.edit_message_throttled(
                status_msg, 
                f"✅ *Upload complete!*\n\n"
                f"📂 Folder: `{config.RCLONE_DEST_DIR}/{job_id}`\n"
                f"🧹 Local files cleaned up successfully.",
                last_edit_state
            )
        else:
            await utils.edit_message_throttled(status_msg, "❌ *Upload to Google Drive failed.*", last_edit_state)
            
    except Exception as e:
        logger.error(f"Error handling job {job_id}: {e}", exc_info=True)
        try:
            await utils.edit_message_throttled(status_msg, f"❌ *An error occurred:* `{str(e)}`", last_edit_state)
        except Exception:
            pass
    finally:
        # Guarantee cleanup of local files
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
        # Remove from active jobs
        utils.active_jobs.pop(job_id, None)
