import logging

import utils

logger = logging.getLogger(__name__)

async def cancel_handler(event):
    """Handler for the /cancel <job_id> command."""
    user = await event.get_sender()
    if not user:
        return
    if not utils.is_authorized(user.id):
        await event.respond("❌ You are not authorized to use this bot.")
        return

    # Parse args
    args = event.text.strip().split()
    if len(args) < 2:
        await event.respond("❌ Please provide a Job ID.\nUsage: `/cancel <job_id>`")
        return

    job_id = args[1].strip()
    
    if job_id not in utils.active_jobs:
        await event.respond(f"❌ Job `{job_id}` not found or already completed.")
        return

    # Mark as cancelled
    job = utils.active_jobs[job_id]
    job["cancelled"] = True
    
    # Terminate process if running
    process = job.get("process")
    if process:
        try:
            logger.info(f"Terminating process for job {job_id}")
            process.terminate()
        except Exception as e:
            logger.warning(f"Failed to terminate process for job {job_id}: {e}")

    await event.respond(f"⏳ *Cancellation request sent for job* `{job_id}`.")
