import asyncio
import logging
import os
import re
import shutil
import urllib.parse

from telethon import Button

import config
import utils
from downloaders.aria2 import run_aria2_download
from downloaders.rclone import run_rclone_upload

logger = logging.getLogger(__name__)

async def start_mirror_job(client, chat_id, message_id, target, is_torrent_file, selected_indexes=None, torrent_path=None, status_msg=None):
    """
    Core download, upload, and cleanup routine.
    Can be run immediately or triggered via callback query (all vs selective).
    """
    job_id = f"{chat_id}_{message_id}"
    job_dir = os.path.join(config.DOWNLOAD_DIR, f"job_{job_id}")
    
    # Resolve user info
    user_display = "User"
    try:
        sender = await client.get_entity(chat_id)
        user_display = sender.first_name or f"User {chat_id}"
    except Exception:
        pass

    # Resolve display job name
    filename = None
    if torrent_path:
        filename = os.path.basename(torrent_path)
        job_name = filename
    elif isinstance(target, str):
        if target.startswith("magnet:"):
            match = re.search(r"dn=([^&]+)", target)
            if match:
                job_name = urllib.parse.unquote(match.group(1))
            else:
                job_name = f"Torrent_Magnet_{job_id}"
        else:
            job_name = target.split("/")[-1] or f"DirectLink_{job_id}"
    else:
        filename = utils.get_filename(target)
        job_name = filename or f"Telegram_Media_{job_id}"
        
    if torrent_path and filename:
        job_name = filename

    # Register active job
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
    
    if not status_msg:
        status_msg = await client.send_message(chat_id, f"⏳ *Initializing job...*\n\nTo cancel, send: `/cancel {job_id}`")
        
    last_edit_state = {"time": 0, "text": ""}
    
    try:
        success = False
        
        # Download phase
        last_edit_state["time"] = 0
        if isinstance(target, str):
            # Direct link or magnet link (passes selected_indexes to aria2c)
            success = await run_aria2_download(target, job_dir, job_id, status_msg, last_edit_state, selected_indexes)
        elif is_torrent_file:
            # If torrent_path is not already provided, download it now
            if not torrent_path:
                await utils.edit_message_throttled(status_msg, f"⏳ *Downloading .torrent file from Telegram...*\n\nTo cancel, send: `/cancel {job_id}`", last_edit_state)
                torrent_path = os.path.join(config.DOWNLOAD_DIR, f"temp_{job_id}.torrent")
                
                last_edit_state["time"] = 0
                await client.download_media(
                    target,
                    file=torrent_path,
                    progress_callback=lambda r, t: utils.tg_progress_callback(r, t, status_msg, last_edit_state, job_id)
                )
            
            # Start aria2 with downloaded torrent file
            last_edit_state["time"] = 0
            success = await run_aria2_download(torrent_path, job_dir, job_id, status_msg, last_edit_state, selected_indexes)
        else:
            # Generic Telegram file
            local_path = os.path.join(job_dir, job_name)
            
            last_edit_state["time"] = 0
            if job_id in utils.active_jobs:
                utils.active_jobs[job_id]["phase"] = "Downloading Telegram File"
                
            await client.download_media(
                target,
                file=local_path,
                progress_callback=lambda r, t: utils.tg_progress_callback(r, t, status_msg, last_edit_state, job_id)
            )
            success = True
            
        if not success:
            if job_id in utils.active_jobs and utils.active_jobs[job_id].get("cancelled"):
                await utils.edit_message_throttled(status_msg, "❌ *Job cancelled by user.* Local files cleaned up.", last_edit_state)
            else:
                await utils.edit_message_throttled(status_msg, "❌ *Download failed.* Check URL or torrent validity.", last_edit_state)
            return
            
        # Check if downloaded anything
        downloaded_contents = os.listdir(job_dir)
        if not downloaded_contents:
            await utils.edit_message_throttled(status_msg, "❌ *Download completed, but no files found.*", last_edit_state)
            return
            
        # Upload phase
        last_edit_state["time"] = 0
        await utils.edit_message_throttled(status_msg, f"⏳ *Preparing to upload to Google Drive...*\n\nTo cancel, send: `/cancel {job_id}`", last_edit_state)
        
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
            if job_id in utils.active_jobs and utils.active_jobs[job_id].get("cancelled"):
                await utils.edit_message_throttled(status_msg, "❌ *Job cancelled by user.* Local files cleaned up.", last_edit_state)
            else:
                await utils.edit_message_throttled(status_msg, "❌ *Upload to Google Drive failed.*", last_edit_state)
                
    except asyncio.CancelledError:
        logger.info(f"Job {job_id} was cancelled by user.")
        try:
            await utils.edit_message_throttled(status_msg, "❌ *Job cancelled by user.* Local files cleaned up.", last_edit_state)
        except Exception:
            pass
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
        if torrent_path and os.path.exists(torrent_path):
            os.remove(torrent_path)
        utils.active_jobs.pop(job_id, None)

async def mirror_handler(event):
    """Main callback to handle new incoming messages with links/files."""
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

    # Check if it's a torrent or magnet link
    is_magnet = isinstance(target, str) and target.startswith("magnet:")
    
    if is_torrent_file or is_magnet:
        # Prompt selection menu first
        temp_torrent_path = None
        if is_torrent_file:
            # Download torrent file first to a temp path so we can parse it
            temp_torrent_path = os.path.join(config.DOWNLOAD_DIR, f"temp_{job_id}.torrent")
            await event.client.download_media(target, file=temp_torrent_path)
            
        # Register in selection_sessions
        utils.selection_sessions[job_id] = {
            "target": target,
            "is_torrent_file": is_torrent_file,
            "torrent_path": temp_torrent_path,
            "chat_id": event.chat_id,
            "message_id": message.id
        }
        
        # Send prompt
        buttons = [
            [
                Button.inline("🚀 Download All", data=f"dl_all:{job_id}"),
                Button.inline("📂 Select Files", data=f"browser_init:{job_id}")
            ]
        ]
        await event.respond(
            "⚡ *Torrent/Magnet detected!*\nChoose how you want to download:",
            buttons=buttons,
            parse_mode="Markdown"
        )
    else:
        # Direct download link or normal media file (runs immediately)
        asyncio.create_task(start_mirror_job(event.client, event.chat_id, message.id, target, is_torrent_file))
