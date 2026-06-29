# HerdBot 🤖
HerdBot is a Telegram Bot designed to download files and torrents on a local server, upload them to Google Drive, and then cleanly delete them from the local server.

By utilizing **Telethon** and the **Telegram MTProto API**, HerdBot runs with high API limits and supports downloading large Telegram files (up to 2GB).

## Features
- **Accepts Multiple Formats:**
  1. Telegram files (Documents, Videos, Audio, Voice notes, etc.)
  2. Direct download links (`http://` or `https://`)
  3. `.torrent` files
  4. Magnet links (`magnet:?xt=urn:...`)
- **Seamless Uploads:** Uploads files and folders directly to your Google Drive while keeping the directory structure intact for torrents.
- **Clean Execution:** Automatically deletes local copies after successful upload.
- **No Seeding:** For torrents, it stops seeding immediately after the download completes.
- **Visual Progress Bars:** Shows real-time speed, ETA, and progress bars on Telegram for both downloading and uploading phases, as well as Telegram native file downloads.
- **Access Control:** Whitelist specific Telegram User IDs to prevent unauthorized usage of your bot.

---

## Prerequisites
Ensure you have [Pixi](https://pixi.sh) installed. If you do not, you can install it using:
```bash
curl -fsSL https://pixi.sh/install.sh | bash
```

---

## Setup Instructions

### 1. Configure Environment Variables
Copy `.env.example` to `.env` and fill in the values:
```bash
cp .env.example .env
```

Open `.env` and configure:
1. **`TELEGRAM_API_ID` & `TELEGRAM_API_HASH`:** Create an application on [my.telegram.org](https://my.telegram.org) under the "API development tools" section to retrieve these.
2. **`TELEGRAM_BOT_TOKEN`:** Generate a token by speaking to [@BotFather](https://t.me/BotFather) on Telegram.
3. **`AUTHORIZED_USERS`:** A comma-separated list of your Telegram User IDs (e.g., `12345678,987654321`). You can find your user ID using bots like [@userinfobot](https://t.me/userinfobot). If left empty, anyone can access the bot.
4. **`RCLONE_REMOTE_NAME`:** The name of the rclone remote (default is `gdrive`).
5. **`RCLONE_UPLOAD_DIR`:** The destination directory on Google Drive where files will be uploaded (default is `TelegramBotUploads`).

---

### 2. Configure Google Drive in Rclone
HerdBot uses `rclone` internally to communicate with Google Drive. You must authenticate it once before running the bot:

Run the following command in your terminal:
```bash
pixi run config-gdrive
```

Follow the interactive setup steps:
1. Press `n` to create a new remote.
2. Name it exactly what you set in `.env` (default is `gdrive`).
3. Choose the storage type by finding the number for **Google Drive** (usually searching for `drive`).
4. Leave `client_id` and `client_secret` blank to use default credentials.
5. For scope, choose option `1` (Full access to all files, `drive`).
6. Leave `root_folder_id` and `service_account_file` blank.
7. Choose `n` for Edit advanced config (default is `n`).
8. Choose `y` for Use auto config. A browser window will open to authenticate your Google account and grant permissions to rclone.
9. Choose `n` for Configure this as a Shared Drive (unless you are using one).
10. Confirm and save the configuration by pressing `y`.

---

### 3. Run the Bot
To start the Telegram bot, run:
```bash
pixi run start-bot
```

Once started, open a chat with your bot on Telegram, send `/start`, and begin sending files or links!
