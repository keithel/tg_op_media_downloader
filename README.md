# Telegram Media Downloader (`tg-media-downloader`)

A high-performance CLI utility powered by **`uv`** and **Telethon** to selectively download media (photos, videos, files) from Telegram chats by **date range**, **timeframe (e.g. past day)**, or **message IDs**.

## Features

- **1Password CLI Integration**: Automatically retrieves `api_id` and `api_hash` from 1Password via `op` CLI (`Personal` vault → `Telegram` item).
- **Date & Time Filtering**:
  - Filter by relative days/hours (e.g. `--days 1` for past 24 hours, `--hours 12`).
  - Filter by specific date ranges (e.g. `--since 2026-09-01 --until 2026-09-03`).
- **Selective Message List**:
  - Download specific message IDs or ranges (e.g. `--messages 100,105,120-130`).
- **Interactive Chat Finder**:
  - `--list-chats` prints recent dialogs with their IDs, names, and usernames.
- **Media Type Filtering**:
  - `--media-type photos` (default), `videos`, or `all`.
- **Smart Progress & Resumption**:
  - Skips already downloaded files unless `--overwrite` is specified.
  - Shows real-time progress bar for downloads.

---

## Obtaining Telegram API Credentials (`api_id` and `api_hash`)

To connect to Telegram's API via Telethon, you need your own `api_id` and `api_hash`:

1. Log into [my.telegram.org](https://my.telegram.org) with your Telegram phone number and confirmation code.
2. Click on **API development tools**.
3. Fill out the **Create new application** form:
   - **App title:** Any title for your tool (e.g., `My Media Downloader` — avoid using the word `"Telegram"`).
   - **Short name:** 5–32 alphanumeric characters, letters and numbers only (**no spaces, underscores, or hyphens**, e.g., `mediadownloader01`).
   - **URL:** Can be left blank (or use `https://example.com`).
   - **Platform:** Select `Desktop` (or `Other`).
   - **Description:** A short note (e.g., `Personal script for downloading chat media`).
4. Click **Create application**.
5. Copy your **`App api_id`** and **`App api_hash`**.
6. Store them:
   - **In 1Password (Recommended):** In your `Personal` vault under an item titled `Telegram`, add fields named `api_id` and `api_hash`.
   - **Or as Environment Variables:** `export TELEGRAM_API_ID="your_id"` and `export TELEGRAM_API_HASH="your_hash"`.

---

## Quick Start (with `uv`)

Navigate to the project directory:

```bash
cd tg_media_downloader
```

### 1. List Recent Chats
Run this first to find the exact name or ID of the chat you want to download from:

```bash
uv run tg-media-downloader --list-chats
```

*(Note: On the very first run, Telegram will ask you in the terminal for your phone number and login code to create a local `.session` file. You will only need to do this once.)*

### 2. Download Images from the Past Day (Last 24 Hours)

```bash
uv run tg-media-downloader --chat "Chat Title or @username" --days 1
```

### 3. Download Images from the Last 12 Hours

```bash
uv run tg-media-downloader --chat "Chat Title or @username" --hours 12
```

### 4. Download from a Date Range

```bash
uv run tg-media-downloader --chat "Chat Title or @username" --since 2026-09-01 --until 2026-09-03
```

### 5. Download a Specific List of Messages

```bash
uv run tg-media-downloader --chat "Chat Title or @username" --messages 405,412,450-460
```

### 6. Download All Media Types (Photos, Videos, Documents)

```bash
uv run tg-media-downloader --chat "Chat Title or @username" --days 2 --media-type all
```

---

## 1Password Configuration

The script uses strictly scoped `op read` secret reference URIs. Before each request is dispatched to `op`, the script prints the exact URI to the terminal so you know exactly what is being requested before you authorize it:

```text
[*] Requesting from 1Password: op://Personal/Telegram/api_id
```

By default, the script looks for `api_id` and `api_hash` automatically:
- **Vault:** `Personal` (override with `--op-vault`)
- **Item:** `Telegram` (or specific item ID like `kaw4lihw37ckao47oeyf6llyie`, override with `--op-item`)
- **Section:** None by default (optional, override with `--op-section "<section>"`)
- **Fields:** `api_id` and `api_hash`

> **Note on Sections:** In 1Password, the section name is **usually not needed**, even if `api_id` and `api_hash` are stored inside a section. 1Password automatically resolves fields across all sections in the item as long as the field label is unique. You only need to specify `--op-section` if there are multiple fields with the exact same name across different sections in that same item.

> **Tip on Ambiguous Item Names:** If you have multiple items titled "Telegram" in your vault, you can pass `--op-item <item_id>` or rename the app configuration item in 1Password (e.g., to "Telegram API") to target it directly and avoid disambiguation lookups.

You can also bypass 1Password at any time by passing `--api-id` and `--api-hash`, or setting `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` environment variables.

---

## Command Reference

| Flag | Description | Default |
|------|-------------|---------|
| `--chat`, `-c` | Chat title, `@username`, phone number, or numeric ID | Required (unless `--list-chats`) |
| `--list-chats` | Lists your recent dialogs with their IDs and names | `False` |
| `--days`, `-d` | Download media from the past N days | None |
| `--hours` | Download media from the past N hours | None |
| `--since` | Download media sent after this date/time | None |
| `--until` | Download media sent before this date/time | None |
| `--messages`, `-m` | Specific message IDs or ranges (e.g. `10,12-15`) | None |
| `--media-type`, `-t` | Media type: `photos`, `videos`, or `all` | `photos` |
| `--output-dir`, `-o` | Output directory | `./downloads/<chat_name>/` |
| `--limit`, `-l` | Maximum number of files to download | None |
| `--overwrite` | Overwrite existing files instead of skipping | `False` |
| `--op-vault` | 1Password vault name | `Personal` |
| `--op-item` | 1Password item title or item ID | `Telegram` |
| `--op-section` | Optional 1Password section name | None |
| `--api-id` | Direct Telegram API ID override | None |
| `--api-hash` | Direct Telegram API Hash override | None |
| `--session` | Telegram session file name | `telegram_session` |

