# HerdBot

HerdBot is a modular Telegram downloader and uploader bot. It automates downloading files, direct URLs, magnet links, and torrent files to a local server, uploading them recursively to Google Drive, and cleaning up the local filesystem storage after successful transfers.

## Key Features

- **Protocols Supported:** Direct links (HTTP/HTTPS), Torrent files, Magnet links, and Telegram native media.
- **Large File Handling:** Utilizes Telethon (MTProto API) and `cryptg` to support downloading native Telegram files up to 2GB.
- **Robust Uploads:** Integrates with `rclone` to support chunked, multi-threaded uploads while preserving directory structures for multi-file torrents.
- **Auto-Cleanup:** Guarantees deletion of temporary files from local storage upon successful upload.
- **Queue & Metrics:** Includes `/status` to track active transfer statistics (speed, ETA, progress bars) and `/stats` for host server performance tracking.
- **Access Control:** Restricts usage to whitelisted Telegram User IDs.

## Project Structure

```text
herdbot/
├── bot.py                # Session entry point
├── config.py             # Config parsing & validation
├── utils.py              # Shared helpers & active jobs registry
├── downloaders/
│   ├── aria2.py          # aria2c downloader interface
│   └── rclone.py         # rclone uploader interface
└── handlers/
    ├── __init__.py       # Event router configuration
    ├── start.py          # /start and /help commands
    ├── stats.py          # /stats and /status commands
    └── mirror.py         # Link & media processing pipeline
```

## Documentation

For setup, Google Drive remote authentication, and running instructions, refer to [docs/setup.md](docs/setup.md).
