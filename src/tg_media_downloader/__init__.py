import argparse
import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

import dateutil.parser
from telethon import TelegramClient, errors, utils
from telethon.tl.custom.message import Message


def read_1password_secret(uri: str) -> str:
    """Reads a single secret URI from 1Password and informs the user beforehand."""
    print(f"[*] Requesting from 1Password: {uri}")
    try:
        res = subprocess.run(
            ["op", "read", uri],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        if any(w in err.lower() for w in ["denied", "canceled", "cancelled"]):
            print(f"[!] 1Password access was denied or canceled for: {uri}")
        raise


def build_op_uri(vault: str, item: str, section: Optional[str], field: str) -> str:
    """Constructs an op:// secret reference URI, omitting section if empty."""
    if section and section.strip():
        return f"op://{vault}/{item}/{section.strip()}/{field}"
    return f"op://{vault}/{item}/{field}"


def fetch_credentials_from_1password(
    vault: str = "Personal",
    item: str = "Telegram",
    section: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Retrieves api_id and api_hash from 1Password using `op read` secret references.
    Restricts access strictly to the specified fields and announces each lookup.
    Defaults to looking up fields at the item root level (no section).
    """
    # Check if `op` is available
    try:
        subprocess.run(["op", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        raise RuntimeError("1Password CLI 'op' was not found in your PATH.")
    except subprocess.CalledProcessError:
        raise RuntimeError("1Password CLI 'op' error when checking version.")

    # Try direct secret references (op://<vault>/<item>/[<section>/]<field>)
    try:
        api_id = read_1password_secret(build_op_uri(vault, item, section, "api_id"))
        api_hash = read_1password_secret(build_op_uri(vault, item, section, "api_hash"))

        if api_id and api_hash:
            print("[+] Successfully authorized and retrieved API credentials.")
            return api_id, api_hash
    except subprocess.CalledProcessError as e:
        err = e.stderr or ""
        # If multiple items share the title 'Telegram', op returns candidate IDs in its error message.
        # We try reading only the specified secret field from those candidate IDs directly.
        match_ids = re.findall(r"vault\s+[\w-]+:\s+([a-z0-9]+)", err)
        for cid in match_ids:
            try:
                aid = read_1password_secret(build_op_uri(vault, cid, section, "api_id"))
                ahash = read_1password_secret(build_op_uri(vault, cid, section, "api_hash"))
                if aid and ahash:
                    print(f"[+] Successfully authorized and retrieved API credentials (entry '{cid}').")
                    return aid, ahash
            except subprocess.CalledProcessError:
                continue

        sec_path = f"{section.strip()}/" if section and section.strip() else ""
        raise RuntimeError(
            f"Could not read secret fields 'api_id' and 'api_hash' from "
            f"'op://{vault}/{item}/{sec_path}': {err.strip()}"
        )


def parse_message_ids(raw_str: str) -> Set[int]:
    """Parse comma-separated list of IDs and ranges (e.g., '101,102,105-108')."""
    ids: Set[int] = set()
    parts = [p.strip() for p in raw_str.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            try:
                start = int(start_str.strip())
                end = int(end_str.strip())
                for mid in range(min(start, end), max(start, end) + 1):
                    ids.add(mid)
            except ValueError:
                print(f"[!] Warning: invalid range '{part}', skipping.")
        else:
            try:
                ids.add(int(part))
            except ValueError:
                print(f"[!] Warning: invalid message ID '{part}', skipping.")
    return ids


def sanitize_filename(name: str) -> str:
    """Sanitizes strings for safe filesystem usage."""
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")


async def list_dialogs(client: TelegramClient, limit: int = 50) -> None:
    """Lists recent dialogs (chats/groups/channels) to help the user identify chat IDs or titles."""
    print(f"\n--- Recent Chats / Dialogs (up to {limit}) ---")
    count = 0
    async for dialog in client.iter_dialogs(limit=limit):
        count += 1
        dtype = "User" if dialog.is_user else ("Channel" if dialog.is_channel else "Group")
        username = f"@{dialog.entity.username}" if getattr(dialog.entity, "username", None) else "no username"
        print(f"{count:2d}. [{dtype}] {dialog.name} (ID: {dialog.id}) | {username}")
    print("---------------------------------------------\n")


def progress_bar(current: int, total: int, prefix: str = "") -> None:
    """Displays a simple progress indicator during media download."""
    if total > 0:
        percent = (current / total) * 100
        bar_len = 30
        filled = int(bar_len * current // total)
        bar = "=" * filled + "-" * (bar_len - filled)
        mb_curr = current / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        sys.stdout.write(f"\r{prefix}[{bar}] {percent:5.1f}% ({mb_curr:.2f}/{mb_total:.2f} MB)")
        sys.stdout.flush()


async def resolve_chat_entity(client: TelegramClient, chat_arg: str):
    """Resolves chat by id, username, or case-insensitive title match."""
    # Try as numeric id
    try:
        chat_id = int(chat_arg)
        return await client.get_entity(chat_id)
    except (ValueError, errors.RPCError):
        pass

    # Try standard get_entity (handles @username, invite links, etc...)
    try:
        return await client.get_entity(chat_arg)
    except Exception:
        pass

    # Try matching against recent dialog names (exact match first)
    search_lower = chat_arg.lower()
    async for dialog in client.iter_dialogs():
        if dialog.name and dialog.name.lower() == search_lower:
            return dialog.entity
        if getattr(dialog.entity, "username", None) and dialog.entity.username.lower() == search_lower.lstrip("@"):
            return dialog.entity

    # Fallback: substring match in dialog name
    async for dialog in client.iter_dialogs():
        if dialog.name and search_lower in dialog.name.lower():
            print(f"[*] Matched '{chat_arg}' to chat: {dialog.name} (ID: {dialog.id})")
            return dialog.entity

    raise ValueError(f"Could not find or resolve chat: '{chat_arg}'")


def build_filename(message: Message, chat_name: str) -> str:
    """Constructs a deterministic, descriptive filename for downloaded media."""
    dt_str = message.date.strftime("%Y%m%d_%H%M%S")
    msg_id = message.id

    if message.file and message.file.name:
        ext = Path(message.file.name).suffix
        stem = sanitize_filename(Path(message.file.name).stem)[:40]
        return f"{msg_id}_{dt_str}_{stem}{ext}"
    
    # Default extension based on media type
    ext = ".jpg"
    if message.photo:
        ext = ".jpg"
    elif message.video:
        ext = ".mp4"
    elif message.file and message.file.ext:
        ext = message.file.ext

    return f"{msg_id}_{dt_str}{ext}"


async def run_downloader(args: argparse.Namespace) -> None:
    # gather credentials
    api_id = args.api_id or os.getenv("TELEGRAM_API_ID")
    api_hash = args.api_hash or os.getenv("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        op_section = (args.op_section or "").strip() or None
        try:
            api_id, api_hash = fetch_credentials_from_1password(
                vault=args.op_vault,
                item=args.op_item,
                section=op_section,
            )
        except Exception as e:
            sys.exit(f"[!] Error retrieving credentials: {e}\n"
                     "You can also pass --api-id and --api-hash or set TELEGRAM_API_ID and TELEGRAM_API_HASH.")

    # Create telegram client
    session_file = args.session
    client = TelegramClient(session_file, int(api_id), api_hash)
    print("[*] Connecting to Telegram...")
    await client.start()

    # Check if the user just wants a list of chats
    if args.list_chats:
        await list_dialogs(client)
        await client.disconnect()
        return

    if not args.chat:
        print("[!] No --chat specified. Here are your recent chats:")
        await list_dialogs(client, limit=20)
        sys.exit("[!] Please rerun specifying --chat <name_or_id>.")

    # Resolve the chat
    entity = await resolve_chat_entity(client, args.chat)
    chat_title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(entity.id)
    print(f"[+] Target Chat: {chat_title} (ID: {entity.id})")

    # Determine date boundaries
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    since_dt: Optional[datetime.datetime] = None
    until_dt: Optional[datetime.datetime] = None

    if args.days is not None:
        since_dt = now_utc - datetime.timedelta(days=args.days)
    elif args.hours is not None:
        since_dt = now_utc - datetime.timedelta(hours=args.hours)

    if args.since:
        parsed_since = dateutil.parser.parse(args.since)
        if parsed_since.tzinfo is None:
            parsed_since = parsed_since.replace(tzinfo=datetime.timezone.utc)
        since_dt = parsed_since

    if args.until:
        parsed_until = dateutil.parser.parse(args.until)
        if parsed_until.tzinfo is None:
            parsed_until = parsed_until.replace(tzinfo=datetime.timezone.utc)
        until_dt = parsed_until

    if since_dt:
        print(f"[*] Filtering messages newer than: {since_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if until_dt:
        print(f"[*] Filtering messages older than: {until_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Message IDs filter
    target_msg_ids: Optional[Set[int]] = None
    if args.messages:
        target_msg_ids = parse_message_ids(args.messages)
        print(f"[*] Filtering for {len(target_msg_ids)} specific message ID(s)")

    # Create output directory if necessary
    output_dir = Path(args.output_dir or f"./downloads/{sanitize_filename(chat_title)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[+] Download destination: {output_dir.resolve()}\n")

    # Download messages
    download_count = 0
    skip_count = 0
    total_bytes = 0

    # Determine media filter predicate
    def matches_media_filter(msg: Message) -> bool:
        if args.media_type == "photos":
            return bool(msg.photo)
        elif args.media_type == "videos":
            return bool(msg.video)
        elif args.media_type == "all":
            return bool(msg.media)
        return bool(msg.photo)

    print("[*] Scanning messages...")

    # Fetch messages matching criteria
    iter_kwargs = {"reverse": True}
    if args.min_id is not None:
        iter_kwargs["min_id"] = args.min_id
    if args.max_id is not None:
        iter_kwargs["max_id"] = args.max_id
    if since_dt is not None:
        iter_kwargs["offset_date"] = since_dt

    async for msg in client.iter_messages(entity, **iter_kwargs):
        # Time boundary check
        msg_date = msg.date
        if since_dt and msg_date < since_dt:
            continue
        if until_dt and msg_date > until_dt:
            break

        # Specific message IDs filter
        if target_msg_ids is not None and msg.id not in target_msg_ids:
            continue

        # Media type filter
        if not matches_media_filter(msg):
            continue

        filename = build_filename(msg, chat_title)
        dest_path = output_dir / filename

        # Check existing
        if dest_path.exists() and not args.overwrite:
            skip_count += 1
            print(f"[-] [Skip] #{msg.id} ({msg_date.strftime('%Y-%m-%d %H:%M')}): {filename} already exists")
            continue

        print(f"\n[>] Downloading #{msg.id} ({msg_date.strftime('%Y-%m-%d %H:%M')}) -> {filename}")

        def p_cb(cur, tot):
            progress_bar(cur, tot, prefix="    ")

        try:
            downloaded = await msg.download_media(file=str(dest_path), progress_callback=p_cb)
            print()  # newline after progress bar
            if downloaded:
                download_count += 1
                fsize = Path(downloaded).stat().st_size
                total_bytes += fsize
                print(f"[✓] Saved {filename} ({fsize / (1024 * 1024):.2f} MB)")
        except Exception as e:
            print(f"\n[!] Failed to download message #{msg.id}: {e}")

        if args.limit and download_count >= args.limit:
            print(f"\n[*] Reached limit of {args.limit} downloads.")
            break

    await client.disconnect()

    print("\n" + "=" * 50)
    print(f"[✓] Completed!")
    print(f"    Downloaded: {download_count} files ({total_bytes / (1024 * 1024):.2f} MB)")
    print(f"    Skipped:    {skip_count} files")
    print(f"    Saved in:   {output_dir.resolve()}")
    print("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download media from Telegram chats by date range, message list, or hours.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # List your recent chats to get their names/IDs:
  uv run tg-media-downloader --list-chats

  # Download all photos from the past 24 hours:
  uv run tg-media-downloader --chat "MyChatName" --days 1

  # Download photos from the last 12 hours:
  uv run tg-media-downloader --chat "@mychannel" --hours 12

  # Download photos between specific dates:
  uv run tg-media-downloader --chat 123456789 --since 2026-09-01 --until 2026-09-03

  # Download specific message IDs:
  uv run tg-media-downloader --chat "MyGroup" --messages 450,452,500-510

  # Download all media (photos, videos, files):
  uv run tg-media-downloader --chat "MyGroup" --days 2 --media-type all
""",
    )

    # Target
    parser.add_argument("--chat", "-c", type=str, help="Chat title, @username, phone number, or chat ID.")
    parser.add_argument("--list-chats", action="store_true", help="List recent chats/dialogs and exit.")

    # Time filters
    parser.add_argument("--days", "-d", type=float, help="Download media from the past N days (e.g., 1 for past 24h).")
    parser.add_argument("--hours", type=float, help="Download media from the past N hours.")
    parser.add_argument("--since", type=str, help="Download media after this date/time (e.g. '2026-09-01' or '2026-09-01 14:00').")
    parser.add_argument("--until", type=str, help="Download media before this date/time.")

    # Message IDs filter
    parser.add_argument("--messages", "-m", type=str, help="Comma-separated list of message IDs/ranges (e.g. '100,102,110-120').")
    parser.add_argument("--min-id", type=int, help="Only download messages with ID >= min-id.")
    parser.add_argument("--max-id", type=int, help="Only download messages with ID <= max-id.")

    # Media type & limits
    parser.add_argument(
        "--media-type",
        "-t",
        choices=["photos", "videos", "all"],
        default="photos",
        help="Type of media to download (default: photos).",
    )
    parser.add_argument("--limit", "-l", type=int, default=None, help="Maximum number of media items to download.")
    parser.add_argument("--output-dir", "-o", type=str, help="Output directory path (default: ./downloads/<chat_name>).")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files instead of skipping.")

    # 1Password & Credentials
    parser.add_argument("--op-vault", default="Personal", help="1Password vault name (default: 'Personal').")
    parser.add_argument("--op-item", default="Telegram", help="1Password item title or ID (default: 'Telegram').")
    parser.add_argument(
        "--op-section",
        default=None,
        help="Optional 1Password section name. Usually not needed even if fields are in a section, unless duplicate field names exist.",
    )
    parser.add_argument("--api-id", type=str, help="Telegram API ID override.")
    parser.add_argument("--api-hash", type=str, help="Telegram API Hash override.")
    parser.add_argument("--session", default="telegram_session", help="Session file prefix (default: 'telegram_session').")

    args = parser.parse_args()

    try:
        asyncio.run(run_downloader(args))
    except KeyboardInterrupt:
        print("\n[!] Aborted by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()

