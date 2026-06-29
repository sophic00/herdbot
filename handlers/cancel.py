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

    job = utils.active_jobs[job_id]
    job["cancelled"] = True
    
    # Handle queued job cancellation
    if job.get("phase") == "Queued":
        # Remove from queue list
        utils.job_queue = [q for q in utils.job_queue if f"{q['chat_id']}_{q['message_id']}" != job_id]
        
        # Update status message if available
        status_msg = job.get("status_msg")
        if status_msg:
            try:
                await utils.edit_message_throttled(status_msg, "❌ *Job cancelled by user.* (Removed from queue)", {"time": 0, "text": ""})
            except Exception:
                pass
                
        # Remove from active registry
        utils.active_jobs.pop(job_id, None)
        
        # Recalculate and update the remaining queue positions
        from handlers.mirror import process_next_in_queue
        await process_next_in_queue(event.client)
        
        await event.respond(f"✅ Queued job `{job_id}` has been cancelled and removed from the queue.")
        return
    
    # Terminate process if running (active download/upload)
    process = job.get("process")
    if process:
        try:
            logger.info(f"Terminating process for job {job_id}")
            process.terminate()
        except Exception as e:
            logger.warning(f"Failed to terminate process for job {job_id}: {e}")

    await event.respond(f"⏳ *Cancellation request sent for job* `{job_id}`.")
