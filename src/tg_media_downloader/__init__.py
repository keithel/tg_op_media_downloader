"""
tg-media-downloader

A high-performance CLI utility and Python package to selectively download media
from Telegram chats by date range, timeframe, or message IDs.
"""

from .downloader import (
    fetch_credentials_from_1password,
    list_dialogs,
    main,
    run_downloader,
)

__all__ = [
    "fetch_credentials_from_1password",
    "list_dialogs",
    "main",
    "run_downloader",
]
