import asyncio
import logging
import os

from telethon import Button

import config
import utils

logger = logging.getLogger(__name__)

def build_directory_map(files_list):
    """Build unique integer IDs for every subdirectory in the torrent."""
    dir_map = {(): 0}
    id_map = {0: ()}
    next_id = 1
    
    for file in files_list:
        path = file["path"]
        # Folders are prefixes of the file path
        for i in range(len(path) - 1):
            dir_prefix = tuple(path[:i+1])
            if dir_prefix not in dir_map:
                dir_map[dir_prefix] = next_id
                id_map[next_id] = dir_prefix
                next_id += 1
                
    return dir_map, id_map

async def show_directory_view(client, chat_id, msg_id, job_id, dir_id):
    """Renders the file/directory browser using inline buttons."""
    session = utils.selection_sessions.get(job_id)
    if not session:
        return
        
    files = session["files"]
    dir_map = session["dir_map"]
    id_map = session["id_map"]
    root_name = session["root_name"]
    
    current_path = id_map.get(dir_id, ())
    
    # Identify items in the current directory
    subdirs = {}  # sub_name -> sub_id
    current_files = []  # list of file dicts
    
    for file in files:
        path = file["path"]
        # Check if file is inside the current directory path
        if len(path) > len(current_path) and tuple(path[:len(current_path)]) == current_path:
            remaining = path[len(current_path):]
            if len(remaining) == 1:
                # Direct file child
                current_files.append({
                    "index": file["index"],
                    "name": remaining[0],
                    "size": file["size"],
                    "selected": file["selected"]
                })
            else:
                # Subdirectory child
                sub_name = remaining[0]
                sub_path = current_path + (sub_name,)
                if sub_path in dir_map and sub_name not in subdirs:
                    subdirs[sub_name] = dir_map[sub_path]
                    
    # Build inline buttons
    buttons = []
    
    # 1. Add directories
    for sub_name, sub_id in sorted(subdirs.items()):
        buttons.append([Button.inline(f"📁 {sub_name}", data=f"dir:{job_id}:{sub_id}")])
        
    # 2. Add files (checkbox + name + size)
    for f in sorted(current_files, key=lambda x: x["name"]):
        cb_char = "✅" if f["selected"] else "☐"
        buttons.append([
            Button.inline(
                f"{cb_char} {f['name']} ({utils.format_size(f['size'])})", 
                data=f"file:{job_id}:{f['index']}:{dir_id}"
            )
        ])
        
    # 3. Add Navigation & Controls
    nav_row = []
    if dir_id != 0:
        parent_path = current_path[:-1]
        parent_id = dir_map.get(parent_path, 0)
        nav_row.append(Button.inline("◀️ Back", data=f"dir:{job_id}:{parent_id}"))
    buttons.append(nav_row)
    
    toggle_row = [
        Button.inline("Select All", data=f"sad:{job_id}:{dir_id}"),
        Button.inline("Deselect All", data=f"dad:{job_id}:{dir_id}")
    ]
    buttons.append(toggle_row)
    
    # Start download button
    buttons.append([Button.inline("🚀 Start Download", data=f"start:{job_id}")])
    
    # Render message text
    path_str = f"/{'/'.join(current_path)}" if current_path else "/"
    text = (
        f"📂 *Browsing:* `{root_name}{path_str}`\n\n"
        f"Please select the files/folders you want to download. "
        f"Toggle files with checkboxes or enter folders to explore."
    )
    
    await client.edit_message(chat_id, msg_id, text, buttons=buttons, parse_mode="Markdown")

async def prefetch_magnet_metadata(client, chat_id, msg_id, job_id, magnet_link) -> str | None:
    """Download magnet metadata (.torrent file) using aria2c metadata-only mode."""
    job_dir = os.path.join(config.DOWNLOAD_DIR, f"metadata_{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    
    # Update status message
    await client.edit_message(chat_id, msg_id, "⏳ *Fetching torrent metadata from peers... (This may take 10-30 seconds)*")
    
    cmd = [
        "aria2c",
        f"--dir={job_dir}",
        "--bt-metadata-only=true",
        "--save-metadata=true",
        "--bt-tracker-timeout=15",
        "--bt-stop-timeout=30",
        magnet_link
    ]
    
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        # Enforce 45s timeout for fetching metadata
        await asyncio.wait_for(process.wait(), timeout=45.0)
        
        if process.returncode == 0:
            # Find the saved .torrent file in job_dir
            for f in os.listdir(job_dir):
                if f.endswith(".torrent"):
                    torrent_path = os.path.join(job_dir, f)
                    # Copy to a persistent temp path
                    dest_path = os.path.join(config.DOWNLOAD_DIR, f"temp_{job_id}.torrent")
                    shutil_copy_file(torrent_path, dest_path)
                    shutil_rm_tree(job_dir)
                    return dest_path
        
    except TimeoutError:
        logger.warning(f"Metadata fetch timed out for job {job_id}")
        if process:
            try:
                process.terminate()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error fetching metadata for job {job_id}: {e}")
        
    shutil_rm_tree(job_dir)
    return None

def shutil_copy_file(src, dst):
    import shutil
    try:
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False

def shutil_rm_tree(path):
    import shutil
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)

async def select_callback_handler(event):
    """Callback query router for directory selection & download initialization."""
    data = event.data.decode('utf-8')
    parts = data.split(":")
    action = parts[0]
    job_id = parts[1]
    
    client = event.client
    chat_id = event.chat_id
    msg_id = event.query.msg_id
    
    # Lazy import to avoid circular dependencies
    from handlers.mirror import start_mirror_job
    
    if action == "dl_all":
        # Delete selection menu and trigger full download
        session = utils.selection_sessions.pop(job_id, None)
        target = session["target"] if session else None
        is_torrent_file = session["is_torrent_file"] if session else False
        
        if not target:
            await event.answer("❌ Session expired.", alert=True)
            return
            
        await client.edit_message(chat_id, msg_id, "⏳ *Initializing full download...*")
        asyncio.create_task(start_mirror_job(client, chat_id, msg_id, target, is_torrent_file, selected_indexes=None))
        await event.answer()
        
    elif action == "browser_init":
        session = utils.selection_sessions.get(job_id)
        if not session:
            await event.answer("❌ Session expired.", alert=True)
            return
            
        target = session["target"]
        is_torrent_file = session["is_torrent_file"]
        
        # If it's a magnet link, we must pre-fetch metadata first
        if not is_torrent_file:
            await event.answer("Fetching metadata...", alert=False)
            torrent_path = await prefetch_magnet_metadata(client, chat_id, msg_id, job_id, target)
            if not torrent_path:
                await client.edit_message(chat_id, msg_id, "❌ *Failed to retrieve torrent metadata.* Check tracker/peer availability.")
                utils.selection_sessions.pop(job_id, None)
                return
            session["torrent_path"] = torrent_path
            session["is_torrent_file"] = True
            
        # Parse torrent files
        try:
            root_name, files_list = utils.parse_torrent_files(session["torrent_path"])
            dir_map, id_map = build_directory_map(files_list)
            
            session.update({
                "root_name": root_name,
                "files": files_list,
                "dir_map": dir_map,
                "id_map": id_map
            })
            
            await event.answer()
            await show_directory_view(client, chat_id, msg_id, job_id, 0)
        except Exception as e:
            logger.error(f"Failed to parse torrent files for job {job_id}: {e}")
            await client.edit_message(chat_id, msg_id, f"❌ *Failed to parse torrent file:* `{e}`")
            utils.selection_sessions.pop(job_id, None)
            
    elif action == "dir":
        dir_id = int(parts[2])
        await event.answer()
        await show_directory_view(client, chat_id, msg_id, job_id, dir_id)
        
    elif action == "file":
        file_index = int(parts[2])
        dir_id = int(parts[3])
        session = utils.selection_sessions.get(job_id)
        if session:
            for f in session["files"]:
                if f["index"] == file_index:
                    f["selected"] = not f["selected"]
                    break
            await event.answer()
            await show_directory_view(client, chat_id, msg_id, job_id, dir_id)
        else:
            await event.answer("❌ Session expired.", alert=True)
            
    elif action in ("sad", "dad"):
        # Select/Deselect All in Directory
        dir_id = int(parts[2])
        session = utils.selection_sessions.get(job_id)
        if session:
            current_path = session["id_map"].get(dir_id, ())
            new_state = (action == "sad")
            
            for file in session["files"]:
                path = file["path"]
                if len(path) > len(current_path) and tuple(path[:len(current_path)]) == current_path:
                    file["selected"] = new_state
                    
            await event.answer()
            await show_directory_view(client, chat_id, msg_id, job_id, dir_id)
        else:
            await event.answer("❌ Session expired.", alert=True)
            
    elif action == "start":
        session = utils.selection_sessions.pop(job_id, None)
        if not session:
            await event.answer("❌ Session expired.", alert=True)
            return
            
        # Get selected indexes
        selected_indexes = [f["index"] for f in session["files"] if f["selected"]]
        if not selected_indexes:
            await event.answer("❌ Please select at least one file to download.", alert=True)
            # Re-register session so they don't lose progress
            utils.selection_sessions[job_id] = session
            return
            
        await event.answer("Starting download...", alert=False)
        await client.edit_message(chat_id, msg_id, "⏳ *Initializing selective download...*")
        
        # Trigger download job with selected indexes
        asyncio.create_task(
            start_mirror_job(
                client, 
                chat_id, 
                msg_id, 
                session["target"], 
                session["is_torrent_file"], 
                selected_indexes=selected_indexes,
                torrent_path=session.get("torrent_path")
            )
        )
