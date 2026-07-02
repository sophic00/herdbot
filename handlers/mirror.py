import asyncio
import ipaddress
import logging
import os
import re
import shutil
import socket
import urllib.parse

from telethon import Button

import bencode
import config
import utils
from downloaders.aria2 import run_aria2_download
from downloaders.rclone import run_rclone_upload

logger = logging.getLogger(__name__)

def is_safe_url(url: str) -> bool:
    """Validate that the target URL scheme is strictly http, https or magnet, and does not point to local/private IPs."""
    if url.startswith("magnet:"):
        return True
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
            
        hostname = parsed.hostname
        if not hostname:
            return False
            
        try:
            ip = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback:
                return False
        except Exception:
            pass
            
        return True
    except Exception:
        return False

def get_dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total

def prune_unselected_files(job_dir: str, torrent_path: str, selected_indexes: list[int]):
    """Delete unselected placeholder files and empty directories in job_dir."""
    try:
        with open(torrent_path, 'rb') as f:
            data = f.read()
        torrent = bencode.bdecode(data)
        if not isinstance(torrent, dict):
            return
        info = torrent.get('info', {})
        if not isinstance(info, dict):
            return
            
        root_name = info.get('name', b'').decode('utf-8', errors='ignore')
        
        selected_paths = set()
        if 'files' in info:
            # Multi-file torrent
            for idx, file_info in enumerate(info['files'], start=1):
                if idx in selected_indexes:
                    path_components = [p.decode('utf-8', errors='ignore') for p in file_info.get('path', [])]
                    rel_path = os.path.join(root_name, *path_components)
                    selected_paths.add(os.path.normpath(rel_path))
        else:
            # Single-file torrent
            if 1 in selected_indexes:
                selected_paths.add(os.path.normpath(root_name))
                
        # Walk and delete unselected files
        for root, dirs, files in os.walk(job_dir, topdown=False):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, job_dir)
                norm_rel = os.path.normpath(rel_path)
                
                if file.endswith(".aria2"):
                    continue
                    
                if norm_rel not in selected_paths:
                    try:
                        os.remove(abs_path)
                    except Exception:
                        pass
            
            # Delete empty directories
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Error pruning unselected torrent files: {e}")

async def update_queue_positions(client):
    """Update the queue position messages for all remaining queued jobs."""
    queue_snapshot = await utils.get_job_queue_snapshot()
    for idx, queued_job in enumerate(queue_snapshot, start=1):
        q_id = f"{queued_job['chat_id']}_{queued_job['message_id']}"
        new_text = f"⏳ **Job added to queue.** Position: `#{idx}`\n\nTo cancel, send: `/cancel {q_id}`"
        try:
            await utils.edit_message_throttled(queued_job["status_msg"], new_text, {"time": 0, "text": ""})
        except Exception:
            pass

async def process_next_in_queue(client):
    """Automatically start the next job in the queue if concurrency limits allow."""
    if await utils.get_running_jobs_count() < config.MAX_CONCURRENT_JOBS:
        next_job = await utils.pop_from_job_queue()
        if next_job:
            # Update the queue position messages for all remaining queued jobs
            await update_queue_positions(client)
                
            # Start the next job
            asyncio.create_task(
                execute_mirror_job(
                    client=next_job["client"],
                    chat_id=next_job["chat_id"],
                    message_id=next_job["message_id"],
                    target=next_job["target"],
                    is_torrent_file=next_job["is_torrent_file"],
                    selected_indexes=next_job["selected_indexes"],
                    torrent_path=next_job["torrent_path"],
                    status_msg=next_job["status_msg"],
                    user_display=next_job["user_display"],
                    job_name=next_job["job_name"],
                    zip_content=next_job.get("zip_content", False)
                )
            )

async def start_mirror_job(client, chat_id, message_id, target, is_torrent_file, selected_indexes=None, torrent_path=None, status_msg=None, zip_content=False):
    """
    Checks concurrency limits and either executes the job immediately or queues it.
    """
    job_id = f"{chat_id}_{message_id}"
    
    # Resolve user display info
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

    # Check concurrency limit BEFORE registering to make it clean and robust (Issue 4, 9)
    running_jobs = await utils.get_running_jobs_count()
    phase = "Queued" if running_jobs >= config.MAX_CONCURRENT_JOBS else "Initializing"

    # Register in active_jobs
    job_data = {
        "user": user_display,
        "name": job_name,
        "phase": phase,
        "percent": 0,
        "speed": "0 B/s",
        "eta": "N/A",
        "status_msg": status_msg
    }
    await utils.set_active_job(job_id, job_data)

    if phase == "Queued":
        job_context = {
            "client": client,
            "chat_id": chat_id,
            "message_id": message_id,
            "target": target,
            "is_torrent_file": is_torrent_file,
            "selected_indexes": selected_indexes,
            "torrent_path": torrent_path,
            "user_display": user_display,
            "job_name": job_name,
            "status_msg": status_msg,
            "zip_content": zip_content
        }
        await utils.add_to_job_queue(job_context)
        pos = await utils.get_job_queue_length()
        
        queue_text = f"⏳ **Job added to queue.** Position: `#{pos}`\n\nTo cancel, send: `/cancel {job_id}`"
        
        if status_msg:
            await utils.edit_message_throttled(status_msg, queue_text, {"time": 0, "text": ""})
        else:
            status_msg = await client.send_message(chat_id, queue_text)
            job_context["status_msg"] = status_msg

        # Store status_msg in active_jobs so the cancel handler can find it
        await utils.update_active_job(job_id, {"status_msg": status_msg})
    else:
        # Execute immediately
        asyncio.create_task(
            execute_mirror_job(
                client, chat_id, message_id, target, is_torrent_file,
                selected_indexes, torrent_path, status_msg, user_display, job_name, zip_content
            )
        )

async def execute_mirror_job(client, chat_id, message_id, target, is_torrent_file, selected_indexes, torrent_path, status_msg, user_display, job_name, zip_content=False):
    """The actual download, upload, and cleanup routine."""
    job_id = f"{chat_id}_{message_id}"
    job_dir = os.path.join(config.DOWNLOAD_DIR, f"job_{job_id}")
    
    # Ensure job state reflects initialization
    job = await utils.get_active_job(job_id)
    if job:
        await utils.update_active_job(job_id, {"phase": "Initializing", "status_msg": status_msg})
    else:
        await utils.set_active_job(job_id, {
            "user": user_display,
            "name": job_name,
            "phase": "Initializing",
            "percent": 0,
            "speed": "0 B/s",
            "eta": "N/A",
            "status_msg": status_msg
        })
        
    if not status_msg:
        status_msg = await client.send_message(chat_id, f"⏳ **Initializing job...**\n\nTo cancel, send: `/cancel {job_id}`")
        await utils.update_active_job(job_id, {"status_msg": status_msg})
    else:
        # Edit the status message if it was previously queued
        await utils.edit_message_throttled(
            status_msg, 
            f"⏳ **Initializing job...**\n\nTo cancel, send: `/cancel {job_id}`", 
            {"time": 0, "text": ""}
        )
        await utils.update_active_job(job_id, {"status_msg": status_msg})
        
    last_edit_state = {"time": 0, "text": ""}
    
    try:
        success = False
        
        # Download phase
        last_edit_state["time"] = 0
        if isinstance(target, str):
            # Direct link or magnet link
            success = await run_aria2_download(target, job_dir, job_id, status_msg, last_edit_state, selected_indexes)
        elif is_torrent_file:
            # If torrent_path is not already provided, download it now
            if not torrent_path:
                await utils.edit_message_throttled(status_msg, f"⏳ **Downloading .torrent file from Telegram...**\n\nTo cancel, send: `/cancel {job_id}`", last_edit_state)
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
            await utils.update_active_job(job_id, {"phase": "Downloading Telegram File"})
                
            await client.download_media(
                target,
                file=local_path,
                progress_callback=lambda r, t: utils.tg_progress_callback(r, t, status_msg, last_edit_state, job_id)
            )
            success = True
            
        if not success:
            job = await utils.get_active_job(job_id)
            if job and job.get("cancelled"):
                await utils.edit_message_throttled(status_msg, "❌ **Job cancelled by user.** Local files cleaned up.", last_edit_state)
            else:
                await utils.edit_message_throttled(status_msg, "❌ **Download failed.** Check URL or torrent validity.", last_edit_state)
            return
            
        # Prune unselected files for selective torrent download (Issue 12 / Moderate)
        if selected_indexes is not None and torrent_path:
            await utils.edit_message_throttled(status_msg, "🧹 **Pruning unselected placeholder files...**", last_edit_state)
            await asyncio.to_thread(prune_unselected_files, job_dir, torrent_path, selected_indexes)

        # Clean up any leftover .aria2 control files before checking folder contents or uploading
        def cleanup_aria2_sync():
            for root_dir, _, files in os.walk(job_dir):
                for file in files:
                    if file.endswith(".aria2"):
                        try:
                            os.remove(os.path.join(root_dir, file))
                        except Exception:
                            pass
        await asyncio.to_thread(cleanup_aria2_sync)

        # Check if downloaded anything
        downloaded_contents = await asyncio.to_thread(os.listdir, job_dir)
        if not downloaded_contents:
            await utils.edit_message_throttled(status_msg, "❌ **Download completed, but no files found.**", last_edit_state)
            return
            
        # Record download stats
        downloaded_size = await asyncio.to_thread(get_dir_size, job_dir)
        await utils.add_download_stats(downloaded_size)
            
        # Zipping phase
        if zip_content:
            await utils.edit_message_throttled(status_msg, "🤐 **Zipping downloaded contents...**", last_edit_state)
            
            zip_filename = f"{job_name}.zip"
            temp_zip_path = os.path.join(config.DOWNLOAD_DIR, f"temp_{job_id}.zip")
            
            try:
                # Offload zipping to executor to avoid blocking the event loop
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: shutil.make_archive(
                        temp_zip_path[:-4],  # shutil.make_archive appends .zip automatically
                        'zip',
                        job_dir
                    )
                )
                
                # Delete all local downloaded files in the folder
                await asyncio.to_thread(shutil.rmtree, job_dir, ignore_errors=True)
                await asyncio.to_thread(os.makedirs, job_dir, exist_ok=True)
                
                # Move the newly created zip file into job_dir
                await asyncio.to_thread(shutil.move, temp_zip_path, os.path.join(job_dir, zip_filename))
                
                # Update downloaded contents array so that GD Index link matches the zip file
                downloaded_contents = [zip_filename]
            except Exception as e:
                logger.error(f"Zipping failed: {e}", exc_info=True)
                await utils.edit_message_throttled(status_msg, f"⚠️ **Zipping failed:** `{e}`. Proceeding to upload raw files.", last_edit_state)
                # Cleanup temp zip if it exists
                if await asyncio.to_thread(os.path.exists, temp_zip_path):
                    try:
                        await asyncio.to_thread(os.remove, temp_zip_path)
                    except Exception:
                        pass
            
        # Upload phase
        last_edit_state["time"] = 0
        await utils.edit_message_throttled(status_msg, f"⏳ **Preparing to upload to Google Drive...**\n\nTo cancel, send: `/cancel {job_id}`", last_edit_state)
        
        # Calculate size before move/upload, as rclone move will delete files from job_dir
        upload_size = await asyncio.to_thread(get_dir_size, job_dir)
        
        upload_success = await run_rclone_upload(job_dir, job_id, status_msg, last_edit_state)
        
        if upload_success:
            await utils.add_upload_stats(upload_size)
            link_text = ""
            if config.GD_INDEX_URL:
                index_base = config.GD_INDEX_URL.rstrip("/")
                if config.RCLONE_ISOLATE_JOBS:
                    path_part = f"{config.RCLONE_DEST_DIR}/{job_id}"
                else:
                    if downloaded_contents and len(downloaded_contents) == 1:
                        path_part = f"{config.RCLONE_DEST_DIR}/{downloaded_contents[0]}"
                    else:
                        path_part = config.RCLONE_DEST_DIR
                index_url = f"{index_base}/{urllib.parse.quote(path_part)}"
                link_text = f"🔗 **Index Link:** [Click Here]({index_url})\n"

            dest_folder = f"{config.RCLONE_DEST_DIR}/{job_id}" if config.RCLONE_ISOLATE_JOBS else config.RCLONE_DEST_DIR
            await utils.edit_message_throttled(
                status_msg, 
                f"✅ **Upload complete!**\n\n"
                f"📂 Folder: `{dest_folder}`\n"
                f"{link_text}"
                f"🧹 Local files cleaned up successfully.",
                last_edit_state
            )
        else:
            job = await utils.get_active_job(job_id)
            if job and job.get("cancelled"):
                await utils.edit_message_throttled(status_msg, "❌ **Job cancelled by user.** Local files cleaned up.", last_edit_state)
            else:
                await utils.edit_message_throttled(status_msg, "❌ **Upload to Google Drive failed.**", last_edit_state)
                
    except asyncio.CancelledError:
        logger.info(f"Job {job_id} was cancelled by user.")
        try:
            await utils.edit_message_throttled(status_msg, "❌ **Job cancelled by user.** Local files cleaned up.", last_edit_state)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error handling job {job_id}: {e}", exc_info=True)
        try:
            await utils.edit_message_throttled(status_msg, "❌ **An error occurred while processing your request.** Please check the logs for details.", last_edit_state)
        except Exception:
            pass
    finally:
        # Guarantee cleanup of local files
        if await asyncio.to_thread(os.path.exists, job_dir):
            await asyncio.to_thread(shutil.rmtree, job_dir, ignore_errors=True)
        if torrent_path and await asyncio.to_thread(os.path.exists, torrent_path):
            try:
                await asyncio.to_thread(os.remove, torrent_path)
            except Exception as e:
                logger.warning(f"Failed to remove torrent path {torrent_path}: {e}")
            
        await utils.pop_active_job(job_id)
        # Dequeue the next task
        await process_next_in_queue(client)

async def mirror_handler(event):
    """Main callback to handle new incoming messages with links/files."""
    user = await event.get_sender()
    if not user:
        return
        
    if not utils.is_authorized(user.id):
        await event.respond("❌ You are not authorized to use this bot.")
        return

    message = event.message
    
    # Check if command is /zip
    zip_content = False
    is_zip_cmd = False
    if message.text and message.text.strip().startswith("/zip"):
        is_zip_cmd = True
        zip_content = True
    
    # Ignore messages starting with slash (command routing), unless it is /zip
    if message.text and message.text.strip().startswith("/"):
        if not is_zip_cmd:
            return

    job_id = f"{event.chat_id}_{message.id}"
    
    target = None
    is_torrent_file = False
    if is_zip_cmd:
        # Check if there is text after /zip
        text_parts = message.text.strip().split(maxsplit=1)
        if len(text_parts) > 1:
            potential_target = text_parts[1].strip()
            if is_safe_url(potential_target):
                target = potential_target
        
        # If no target found in text, check if it's a reply
        if not target and message.is_reply:
            reply_msg = await message.get_reply_message()
            if reply_msg:
                filename = utils.get_filename(reply_msg)
                if reply_msg.document:
                    if filename and filename.lower().endswith(".torrent"):
                        is_torrent_file = True
                    target = reply_msg.document
                elif reply_msg.video:
                    target = reply_msg.video
                elif reply_msg.audio:
                    target = reply_msg.audio
                elif reply_msg.voice:
                    target = reply_msg.voice
                elif reply_msg.text:
                    text = reply_msg.text.strip()
                    if is_safe_url(text):
                        target = text
                        
        if not target:
            await event.respond("❌ Please provide a link with `/zip <link>` or reply to a downloadable message/file with `/zip`.")
            return
    else:
        # Standard flow
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
            if is_safe_url(text):
                target = text
                
        if not target:
            if message.text and not message.text.startswith("/"):
                if not event.is_group:
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
        await utils.set_selection_session(job_id, {
            "target": target,
            "is_torrent_file": is_torrent_file,
            "torrent_path": temp_torrent_path,
            "chat_id": event.chat_id,
            "message_id": message.id,
            "zip_content": zip_content
        })
        
        # Send prompt
        buttons = [
            [
                Button.inline("🚀 Download All", data=f"dl_all:{job_id}"),
                Button.inline("📂 Select Files", data=f"browser_init:{job_id}")
            ]
        ]
        await event.respond(
            "⚡ **Torrent/Magnet detected!**\nChoose how you want to download:",
            buttons=buttons,
            parse_mode="Markdown"
        )
    else:
        # Direct download link or normal media file (runs immediately)
        await start_mirror_job(event.client, event.chat_id, message.id, target, is_torrent_file, zip_content=zip_content)
