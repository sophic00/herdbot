import asyncio
import logging
import os
import re

import utils

logger = logging.getLogger(__name__)

# Regex pattern for progress parsing
# Matches: [#368305 1.2MiB/20MiB(6%) CN:1 DL:2.1MiB ETA:8s]
ARIA2_PROGRESS_RE = re.compile(
    r"\[#(?P<gid>[a-f0-9]+)\s+(?P<downloaded>[^/]+)/(?P<total>[^\(]+)\((?P<percent>\d+)%\)"
    r".*?DL:(?P<speed>[^\s\]]+)"
    r"(?:\s+ETA:(?P<eta>[^\s\]]+))?\]"
)

async def run_aria2_download(target: str, job_dir: str, job_id: str, status_msg, last_edit_state: dict, selected_indexes: list[int] | None = None) -> bool:
    """Run aria2c as a subprocess and stream progress back to Telegram & update active_jobs."""
    os.makedirs(job_dir, exist_ok=True)
    
    cmd = [
        "aria2c",
        f"--dir={job_dir}",
        "--seed-time=0",
        "--summary-interval=1",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M"
    ]
    
    if selected_indexes:
        indexes_str = ",".join(str(idx) for idx in selected_indexes)
        cmd.append(f"--select-file={indexes_str}")
        
    cmd.append(target)
    
    logger.info(f"Starting aria2c download: {cmd}")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    
    metadata_downloading = False
    
    # Store process handle and initialize phase
    if job_id in utils.active_jobs:
        utils.active_jobs[job_id]["process"] = process
        utils.active_jobs[job_id]["phase"] = "Downloading"
        
    assert process.stdout is not None
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
            
            # Update global state
            if job_id in utils.active_jobs:
                utils.active_jobs[job_id].update({
                    "percent": percent,
                    "speed": f"{speed}/s",
                    "eta": eta,
                    "phase": "Downloading"
                })
                
            bar = utils.make_progress_bar(percent)
            progress_text = (
                f"📥 *Downloading...*\n"
                f"`[{bar}] {percent}%`\n"
                f"🔸 *Downloaded:* {downloaded} of {total}\n"
                f"🔸 *Speed:* {speed}/s | *ETA:* {eta}\n\n"
                f"To cancel, send: `/cancel {job_id}`"
            )
            await utils.edit_message_throttled(status_msg, progress_text, last_edit_state)
            metadata_downloading = False
        elif "0B/0B" in line or "DL:0B" in line or "DL:0.00B" in line or "DL:0B/s" in line:
            # Handle metadata downloading phase
            if not metadata_downloading:
                metadata_downloading = True
                if job_id in utils.active_jobs:
                    utils.active_jobs[job_id].update({
                        "percent": 0,
                        "speed": "0 B/s",
                        "eta": "N/A",
                        "phase": "Downloading Metadata"
                    })
                await utils.edit_message_throttled(
                    status_msg, 
                    f"📥 *Connecting to peers / downloading metadata...*\n\nTo cancel, send: `/cancel {job_id}`", 
                    last_edit_state
                )
                
    await process.wait()
    return process.returncode == 0
