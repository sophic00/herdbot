import utils


async def start_handler(event):
    user = await event.get_sender()
    if not user:
        return
    if not utils.is_authorized(user.id):
        await event.respond("❌ You are not authorized to use this bot.")
        return

    welcome_text = (
        f"Hi {user.first_name or 'there'}! 👋\n\n"
        f"I am a Downloader & Uploader Bot. Send me one of the following:\n"
        f"1. A direct download link (http/https)\n"
        f"2. A torrent magnet link (`magnet:...`)\n"
        f"3. A `.torrent` file\n"
        f"4. Any other Telegram file (document, video, audio, etc.)\n\n"
        f"Available commands:\n"
        f"• /start - Welcome message\n"
        f"• /help - Detailed instructions\n"
        f"• /status - Show currently running jobs\n"
        f"• /stats - Show server performance & disk stats\n"
        f"• /zip - Reply to a file or use `/zip <link>` to upload as ZIP"
    )
    await event.respond(welcome_text)

async def help_handler(event):
    user = await event.get_sender()
    if not user:
        return
    if not utils.is_authorized(user.id):
        await event.respond("❌ You are not authorized to use this bot.")
        return

    help_text = (
        "💡 *HerdBot Help Guide*\n\n"
        "How to download and upload files:\n"
        "1. *Direct Link:* Paste any direct HTTP/HTTPS download link.\n"
        "2. *Magnet Link:* Paste any torrent magnet link starting with `magnet:?`.\n"
        "3. *Torrent File:* Upload a `.torrent` file directly as a document.\n"
        "4. *Telegram Files:* Upload any media file (video, document, music, etc.) directly to the bot.\n\n"
        "All downloads are saved temporarily, uploaded recursively to Google Drive, and then deleted from the server storage.\n\n"
        "🔧 *Available Commands:*\n"
        "• `/start` - Start the bot\n"
        "• `/help` - Show this help menu\n"
        "• `/status` - Check live status of all active download/upload tasks\n"
        "• `/stats` - View server disk space usage and processor load info\n"
        "• `/zip` - Zip content before uploading (usage: `/zip <link>` or reply to a file/message with `/zip`)"
    )
    await event.respond(help_text, parse_mode="markdown")
