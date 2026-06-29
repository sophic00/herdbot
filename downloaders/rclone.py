import re
import asyncio
import logging
import utils
import config

logger = logging.getLogger(__name__)

# Regex pattern for progress parsing
# Matches: Transferred:      123.45 MiB / 1.23 GiB, 10%, 15.2 MiB/s, ETA 1m15s
RCLONE_PROGRESS_RE = re.compile(
    r"Transferred:\s+(?P<uploaded>[\d\.]+\s*\w+)\s+/\s+(?P<total>[\d\.]+\s*\w+),\s+(?P<percent>\d+)%,\s+(?P<speed>[\d\.]+\s*\w+/s),\s+ETA\s+(?P<eta>[^\s]+)"
)

async def run_rclone_upload(source_dir: str, job_id: str, status_msg, last_edit_state: dict) -> bool:
    """Upload job folder contents to Google Drive using rclone and update active_jobs."""
    dest_path = f"{config.RCLONE_REMOTE}:{config.RCLONE_DEST_DIR}/{job_id}"
    
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
    
    if job_id in utils.active_jobs:
        utils.active_jobs[job_id]["phase"] = "Uploading"
        
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
            
            # Update global state
            if job_id in utils.active_jobs:
                utils.active_jobs[job_id].update({
                    "percent": percent,
                    "speed": speed,
                    "eta": eta,
                    "phase": "Uploading"
                })
                
            bar = utils.make_progress_bar(percent)
            progress_text = (
                f"📤 *Uploading to Google Drive...*\n"
                f"`[{bar}] {percent}%`\n"
                f"🔸 *Uploaded:* {uploaded} of {total}\n"
                f"🔸 *Speed:* {speed} | *ETA:* {eta}"
            )
            await utils.edit_message_throttled(status_msg, progress_text, last_edit_state)
            
    await process.wait()
    return process.returncode == 0
