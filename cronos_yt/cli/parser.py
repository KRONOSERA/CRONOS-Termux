"""CLI flag declarations; no network or terminal side effects."""
from __future__ import annotations
import argparse
from .. import __version__
from ..settings import ALLOWED_AUDIO, ALLOWED_BITRATES

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CRONOS — authorized media downloads for Termux")
    p.add_argument("--url", action="append", default=[], help="YouTube HTTPS URL (repeatable)")
    p.add_argument("--mode", choices=["video", "music"], help="Download type")
    p.add_argument("--quality", default=None, help="Video quality: best or 144/240/360/480/720/1080/1440/2160")
    p.add_argument("--fps", type=int, choices=[30, 60], default=None)
    p.add_argument("--format", choices=ALLOWED_AUDIO, default=None, help="Music format")
    p.add_argument("--bitrate", type=int, choices=ALLOWED_BITRATES, default=None)
    p.add_argument("--playlist", action="store_true", help="Download playlist URL (requires --mode)")
    p.add_argument("--items", default="all", help="Playlist positions, e.g. 1-5,9 (requires --playlist)")
    p.add_argument("--playlist-search", default="", help="Playlist title filter (requires --playlist)")
    p.add_argument("--limit", type=int, default=None, help="Playlist item limit 1..500")
    p.add_argument("--output", help="Custom output directory")
    p.add_argument("--filename", help="Custom name for single item")
    p.add_argument("--lyrics-file", help="Your authorized UTF-8 lyrics file for music")
    p.add_argument("--yes", action="store_true", help="Affirm authorization for the specified media")
    p.add_argument("--confirm-queued", action="store_true", help="Renew authorization for queued jobs in this session (requires --run-queue --yes)")
    p.add_argument("--confirm-large-batch", action="store_true", help="Explicit approval for batches over the configured threshold")
    p.add_argument("--check", action="store_true", help="Check FFmpeg, Node.js and Python dependencies")
    p.add_argument("--update", action="store_true", help="Update engine from reviewed SHA-256 lock")
    p.add_argument("--update-unpinned", action="store_true", help="Explicit unreviewed extractor update; requires --yes")
    p.add_argument("--restore-engine", action="store_true", help="Restore versions saved before last engine update")
    p.add_argument("--install-share-handler", action="store_true", help="Opt-in Android share-sheet integration")
    p.add_argument("--enqueue", action="store_true", help="Save authorized --url jobs for later")
    p.add_argument("--run-queue", action="store_true", help="Run queued jobs (use --yes to affirm authorization)")
    p.add_argument("--queue-list", action="store_true", help="Show persistent queue")
    p.add_argument("--stats", action="store_true", help="Show local download statistics")
    p.add_argument("--library", action="store_true", help="Browse saved media without network requests")
    p.add_argument("--library-search", default="", help="Filter the --library inventory")
    p.add_argument("--library-kind", choices=["all", "video", "music"], default="all")
    p.add_argument("--library-export", help="Export local library to CSV or M3U (extension selects format)")
    p.add_argument("--doctor", action="store_true", help="Run read-only Termux diagnostics")
    p.add_argument("--backup", nargs="?", const="AUTO", help="Create private ZIP backup (optional destination)")
    p.add_argument("--queue-set-priority", nargs=2, type=int, metavar=("ITEM_ID", "LEVEL"),
                   help="Set 0..9 priority on a pending queue entry")
    p.add_argument("--subtitles", choices=["none", "manual", "automatic"], help="Override subtitle settings for this run")
    p.add_argument("--subtitle-languages", help="Override subtitle languages (e.g. en,ar)")
    p.add_argument("--ui-preview", action="store_true", help="Preview the home screen locally, without downloading")
    p.add_argument("--motion-preview", action="store_true", help="Preview offline CRONOS animations on your terminal")
    p.add_argument("--no-animation", action="store_true", help="Disable all motion during this run")
    p.add_argument("--version", action="version", version=f"CRONOS {__version__}")
    return p
