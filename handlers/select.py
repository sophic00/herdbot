import asyncio
import logging
import os
import shutil

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

async def show_directory_view(client, chat_id, msg_id, job_id, dir_id, page=0):
    """Renders the file/directory browser using inline buttons with pagination."""
    session = await utils.get_selection_session(job_id)
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
                    
    # Combine subdirectories and files for pagination
    ITEMS_PER_PAGE = 10
    all_items = []
    for sub_name, sub_id in sorted(subdirs.items()):
        all_items.append(("dir", sub_name, sub_id))
    for f in sorted(current_files, key=lambda x: x["name"]):
        all_items.append(("file", f["name"], f))
        
    total_items = len(all_items)
    max_page = max(0, (total_items - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, max_page))
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = all_items[start_idx:end_idx]
    
    # Build inline buttons
    buttons = []
    
    # Render page items
    for item_type, name, data in page_items:
        if item_type == "dir":
            buttons.append([Button.inline(f"📁 {name}", data=f"dir:{job_id}:{data}:0")])
        else:
            cb_char = "✅" if data["selected"] else "☐"
            buttons.append([
                Button.inline(
                    f"{cb_char} {name} ({utils.format_size(data['size'])})", 
                    data=f"file:{job_id}:{data['index']}:{dir_id}:{page}"
                )
            ])
            
    # Add Prev/Next buttons if paginated
    pagination_row = []
    if page > 0:
        pagination_row.append(Button.inline("⏮️ Prev", data=f"dir:{job_id}:{dir_id}:{page-1}"))
    if end_idx < total_items:
        pagination_row.append(Button.inline("⏭️ Next", data=f"dir:{job_id}:{dir_id}:{page+1}"))
    if pagination_row:
        buttons.append(pagination_row)
        
    # Navigation & Controls
    nav_row = []
    if dir_id != 0:
        parent_path = current_path[:-1]
        parent_id = dir_map.get(parent_path, 0)
        nav_row.append(Button.inline("◀️ Back", data=f"dir:{job_id}:{parent_id}:0"))
    buttons.append(nav_row)
    
    toggle_row = [
        Button.inline("Select All", data=f"sad:{job_id}:{dir_id}:{page}"),
        Button.inline("Deselect All", data=f"dad:{job_id}:{dir_id}:{page}")
    ]
    buttons.append(toggle_row)
    
    # Start download button
    buttons.append([Button.inline("🚀 Start Download", data=f"start:{job_id}")])
    
    # Render message text
    path_str = f"/{'/'.join(current_path)}" if current_path else "/"
    page_info = f" \n📄 **Page:** `{page+1}/{max_page+1}`" if max_page > 0 else ""
    text = (
        f"📂 **Browsing:** `{root_name}{path_str}`{page_info}\n\n"
        f"Please select the files/folders you want to download. "
        f"Toggle files with checkboxes or enter folders to explore."
    )
    
    await client.edit_message(chat_id, msg_id, text, buttons=buttons, parse_mode="Markdown")

async def prefetch_magnet_metadata(client, chat_id, msg_id, job_id, magnet_link) -> str | None:
    """Download magnet metadata (.torrent file) using aria2c metadata-only mode."""
    job_dir = os.path.join(config.DOWNLOAD_DIR, f"metadata_{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    
    # Update status message
    await client.edit_message(chat_id, msg_id, "⏳ **Fetching torrent metadata from peers... (This may take 10-30 seconds)**")
    
    cmd = [
        "aria2c",
        f"--dir={job_dir}",
        "--bt-metadata-only=true",
        "--bt-save-metadata=true",
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
    try:
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False

def shutil_rm_tree(path):
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)

async def select_callback_handler(event):
    """Callback query router for directory selection & download initialization."""
    data = event.data.decode('utf-8')
    parts = data.split(":")
    if len(parts) < 2:
        await event.answer("❌ Invalid request.", alert=True)
        return
        
    action = parts[0]
    job_id = parts[1]
    
    client = event.client
    chat_id = event.chat_id
    msg_id = event.query.msg_id
    
    # Lazy import to avoid circular dependencies
    from handlers.mirror import start_mirror_job
    
    if action == "dl_all":
        # Delete selection menu and trigger full download
        session = await utils.pop_selection_session(job_id)
        if not session:
            await event.answer("❌ Session expired.", alert=True)
            return
            
        target = session["target"]
        is_torrent_file = session["is_torrent_file"]
        zip_content = session.get("zip_content", False)
        
        await client.edit_message(chat_id, msg_id, "⏳ **Initializing full download...**")
        asyncio.create_task(start_mirror_job(client, chat_id, msg_id, target, is_torrent_file, selected_indexes=None, zip_content=zip_content))
        await event.answer()
        
    elif action == "browser_init":
        session = await utils.get_selection_session(job_id)
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
                await client.edit_message(chat_id, msg_id, "❌ **Failed to retrieve torrent metadata.** Check tracker/peer availability.")
                await utils.pop_selection_session(job_id)
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
            await show_directory_view(client, chat_id, msg_id, job_id, 0, 0)
        except Exception as e:
            logger.error(f"Failed to parse torrent files for job {job_id}: {e}")
            await client.edit_message(chat_id, msg_id, f"❌ **Failed to parse torrent file:** `{e}`")
            await utils.pop_selection_session(job_id)
            
    elif action == "dir":
        dir_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        await event.answer()
        await show_directory_view(client, chat_id, msg_id, job_id, dir_id, page)
        
    elif action == "file":
        file_index = int(parts[2])
        dir_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        session = await utils.get_selection_session(job_id)
        if session:
            for f in session["files"]:
                if f["index"] == file_index:
                    f["selected"] = not f["selected"]
                    break
            await event.answer()
            await show_directory_view(client, chat_id, msg_id, job_id, dir_id, page)
        else:
            await event.answer("❌ Session expired.", alert=True)
            
    elif action in ("sad", "dad"):
        # Select/Deselect All in Directory
        dir_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        session = await utils.get_selection_session(job_id)
        if session:
            current_path = session["id_map"].get(dir_id, ())
            new_state = (action == "sad")
            
            for file in session["files"]:
                path = file["path"]
                if len(path) > len(current_path) and tuple(path[:len(current_path)]) == current_path:
                    file["selected"] = new_state
                    
            await event.answer()
            await show_directory_view(client, chat_id, msg_id, job_id, dir_id, page)
        else:
            await event.answer("❌ Session expired.", alert=True)
            
    elif action == "start":
        session = await utils.pop_selection_session(job_id)
        if not session:
            await event.answer("❌ Session expired.", alert=True)
            return
            
        # Get selected indexes
        selected_indexes = [f["index"] for f in session["files"] if f["selected"]]
        if not selected_indexes:
            await event.answer("❌ Please select at least one file to download.", alert=True)
            # Re-register session so they don't lose progress
            await utils.set_selection_session(job_id, session)
            return
            
        await event.answer("Starting download...", alert=False)
        await client.edit_message(chat_id, msg_id, "⏳ **Initializing selective download...**")
        
        zip_content = session.get("zip_content", False)
        
        # Trigger download job with selected indexes
        asyncio.create_task(
            start_mirror_job(
                client, 
                chat_id, 
                msg_id, 
                session["target"], 
                session["is_torrent_file"], 
                selected_indexes=selected_indexes,
                torrent_path=session.get("torrent_path"),
                zip_content=zip_content
            )
        )
