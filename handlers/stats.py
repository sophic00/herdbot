import asyncio
import os
import shutil

import config
import utils


async def stats_handler(event):
    """Handler for the /stats command."""
    user = await event.get_sender()
    if not user:
        return
    if not utils.is_authorized(user.id):
        await event.respond("❌ You are not authorized to use this bot.")
        return

    # Disk Space Usage
    try:
        total, used, free = shutil.disk_usage(config.DOWNLOAD_DIR)
        disk_total_str = utils.format_size(total)
        disk_used_str = utils.format_size(used)
        disk_free_str = utils.format_size(free)
        disk_percent = int((used / total) * 100)
        disk_bar = utils.make_progress_bar(disk_percent)
        disk_info = (
            f"💾 **Disk Space (Download volume):**\n"
            f"`[{disk_bar}] {disk_percent}%`\n"
            f"🔸 Used: `{disk_used_str}` of `{disk_total_str}`\n"
            f"🔸 Free: `{disk_free_str}`"
        )
    except Exception as e:
        disk_info = f"💾 **Disk Space:** Error retrieving stats: `{e}`"

    # CPU load average
    try:
        load1, load5, load15 = os.getloadavg()
        load_info = f"📊 **System Load (1m, 5m, 15m):** `{load1:.2f}, {load5:.2f}, {load15:.2f}`"
    except Exception:
        load_info = "📊 **System Load:** N/A"

    # RAM Memory Info
    mem_info = "🧠 **RAM Memory:** N/A"
    if await asyncio.to_thread(os.path.exists, "/proc/meminfo"):
        try:
            def read_meminfo():
                with open("/proc/meminfo") as f:
                    return f.readlines()
            lines = await asyncio.to_thread(read_meminfo)
            mem_total = 0
            mem_avail = 0
            for line in lines:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])  # kB
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1])  # kB
            if mem_total and mem_avail:
                mem_used = mem_total - mem_avail
                total_gb = mem_total / (1024 * 1024)
                used_gb = mem_used / (1024 * 1024)
                mem_percent = int((mem_used / mem_total) * 100)
                mem_bar = utils.make_progress_bar(mem_percent)
                mem_info = (
                    f"🧠 **RAM Memory Usage:**\n"
                    f"`[{mem_bar}] {mem_percent}%`\n"
                    f"🔸 Used: `{used_gb:.1f} GB` of `{total_gb:.1f} GB`"
                )
        except Exception:
            pass

    # Bot Uptime & Data Traffic Stats
    uptime_str = utils.get_uptime_string()
    total_dl, total_ul = await utils.get_total_stats()
    total_dl_str = utils.format_size(total_dl)
    total_ul_str = utils.format_size(total_ul)
    
    bot_info = (
        f"🤖 **Bot Uptime & Traffic:**\n"
        f"🔸 Uptime: `{uptime_str}`\n"
        f"🔸 Total Downloaded: `{total_dl_str}`\n"
        f"🔸 Total Uploaded: `{total_ul_str}`"
    )

    stats_text = (
        "⚙️ **Server Statistics:**\n\n"
        f"{disk_info}\n\n"
        f"{mem_info}\n\n"
        f"{load_info}\n\n"
        f"{bot_info}"
    )
    await event.respond(stats_text, parse_mode="markdown")


async def status_handler(event):
    """Handler for the /status command showing running tasks."""
    user = await event.get_sender()
    if not user:
        return
    if not utils.is_authorized(user.id):
        await event.respond("❌ You are not authorized to use this bot.")
        return

    active_jobs_snapshot = await utils.get_active_jobs_snapshot()
    running_jobs = {k: v for k, v in active_jobs_snapshot.items() if v.get("phase") != "Queued"}
    queued_jobs = {k: v for k, v in active_jobs_snapshot.items() if v.get("phase") == "Queued"}

    if not running_jobs and not queued_jobs:
        await event.respond("ℹ️ **No active or queued tasks running.**", parse_mode="markdown")
        return

    text = ""
    if running_jobs:
        text += "⏳ **Active Downloader Jobs:**\n\n"
        for job_id, job in running_jobs.items():
            percent = job.get("percent", 0)
            bar = utils.make_progress_bar(percent)
            text += (
                f"📂 **Name:** `{job.get('name')}`\n"
                f"🆔 **Job ID:** `{job_id}`\n"
                f"👤 **Started By:** {job.get('user')}\n"
                f"⚡ **Phase:** `{job.get('phase', 'Initializing')}`\n"
                f"`[{bar}] {percent}%`\n"
                f"🚀 **Speed:** `{job.get('speed', '0 B/s')}` | **ETA:** `{job.get('eta', 'N/A')}`\n"
                f"To cancel, send: `/cancel {job_id}`\n"
                f"─────────────────\n\n"
            )
            
    if queued_jobs:
        text += "💤 **Queued Jobs:**\n\n"
        queue_snapshot = await utils.get_job_queue_snapshot()
        for idx, q_job in enumerate(queue_snapshot, start=1):
            q_id = f"{q_job['chat_id']}_{q_job['message_id']}"
            if q_id in queued_jobs:
                job = queued_jobs[q_id]
                text += (
                    f"📂 **Name:** `{job.get('name')}`\n"
                    f"🆔 **Job ID:** `{q_id}`\n"
                    f"👤 **Started By:** {job.get('user')}\n"
                    f"🔢 **Queue Position:** `#{idx}`\n"
                    f"To cancel, send: `/cancel {q_id}`\n"
                    f"─────────────────\n\n"
                )
    await event.respond(text, parse_mode="markdown")
