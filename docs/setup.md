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
- **`MAX_CONCURRENT_JOBS`:** The maximum number of parallel downloads/uploads allowed to run at the same time (default: `2`). Any additional jobs will be added to a queue.

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

## Selective Torrent Downloads

When you send a `.torrent` file or a magnet link to HerdBot, you will be prompted with two choices:
- `🚀 Download All`: Immediately downloads the entire torrent content.
- `📂 Select Files`: Spawns an interactive file/directory selector directly in Telegram using inline buttons.

### Navigating the File Browser:
- **Files**: Indicated by checkboxes. Click a file button (e.g. `[☐] file_name.mp4`) to toggle its download state.
- **Directories**: Indicated by folder emoji `📁`. Click to navigate inside the folder.
- **Back Navigation**: Click `◀️ Back` to return to the parent directory.
- **Bulk Toggle**: Click `Select All` or `Deselect All` to modify all files in the current folder.
- **Download**: Once you are satisfied with your selection, click `🚀 Start Download` to download and upload only the selected files.

---

## Command Usage

- `/start`: Starts the bot and lists available options.
- `/help`: Displays input formats and supported protocols.
- `/status`: Lists all currently running download and upload jobs, showing their progress bars, speeds, and ETAs.
- `/stats`: Displays host machine resources (disk partition usage, load averages, RAM memory usage).
- `/cancel <job_id>`: Cancels an active job (either downloading or uploading) and triggers immediate local filesystem cleanup.

---

## Development & Code Quality

Before committing changes, ensure that you run the lint and typecheck suites.

### Run Linting
To check for code formatting and import issues (using Ruff):
```bash
pixi run lint
```
To automatically fix format and import sorting:
```bash
pixi run ruff check --fix
```

### Run Typechecking
To verify types and ensure Python static compliance (using Pyright):
```bash
pixi run typecheck
```

### Run All Checks
To run all tests and quality verification tasks concurrently:
```bash
pixi run check
```
If this command exits with `exit code 0`, the codebase is compliant and ready to commit.
