# Setup and Running Instructions

This guide walks you through the configuration and deployment of HerdBot.

## Prerequisites

Ensure you have [Pixi](https://pixi.sh) installed. If it is not installed on your system, run:
```bash
curl -fsSL https://pixi.sh/install.sh | bash
```

---

## Configuration

### 1. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Open `.env` and set the following parameters:
- **`TELEGRAM_API_ID` & `TELEGRAM_API_HASH`:** Obtain these by creating an application on [my.telegram.org](https://my.telegram.org).
- **`TELEGRAM_BOT_TOKEN`:** Obtain this from [@BotFather](https://t.me/BotFather) on Telegram.
- **`AUTHORIZED_USERS`:** Comma-separated list of Telegram User IDs permitted to use the bot (e.g., `12345678,98765432`). If left empty, no authorization check is enforced.
- **`RCLONE_REMOTE_NAME`:** The name of your Rclone remote configuration (default is `gdrive`).
- **`RCLONE_UPLOAD_DIR`:** Target folder path in your Google Drive where files should be uploaded.
- **`DOWNLOAD_DIR`:** The temporary local storage directory used for active downloads (default is `./downloads`).

---

### 2. Configure Google Drive Remote
HerdBot utilizes `rclone` to handle chunked, recursive folder uploads. You must configure and authenticate the remote before starting the bot.

Run:
```bash
pixi run config-gdrive
```

Follow the interactive prompt:
1. Choose `n` to create a new remote.
2. Set the name to match `RCLONE_REMOTE_NAME` in your `.env` (default: `gdrive`).
3. Select `drive` (Google Drive) as the storage type.
4. Leave `client_id` and `client_secret` blank.
5. Select scope `1` (`drive` - full access to all files).
6. Complete the OAuth verification flow via the automatically opened browser window.
7. Save the configuration.

---

## Running the Bot

Start the bot session using:
```bash
pixi run start-bot
```

The bot will run interactively in your terminal. You can terminate the session using `Ctrl+C`.

---

## Command Usage

- `/start`: Starts the bot and lists available options.
- `/help`: Displays input formats and supported protocols.
- `/status`: Lists all currently running download and upload jobs, showing their progress bars, speeds, and ETAs.
- `/stats`: Displays host machine resources (disk partition usage, load averages, RAM memory usage).
