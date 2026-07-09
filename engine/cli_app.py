"""Headless CLI for Omni engine operations."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.runtime_settings import load_engine_settings
from engine.stt.live_capture_service import LiveCaptureService
from engine.wiring.server_default_service_factories import MIGRATIONS_DIR


async def _cmd_list(args: argparse.Namespace) -> int:
    settings = load_engine_settings()
    hub = EventBroadcastHub()
    service = MeetingFinalizationService(settings.db_path, MIGRATIONS_DIR, hub)
    rows = await service.list_meetings()
    if args.json:
        from engine.enhance.meeting_summary_presenter import meeting_summary_payload

        print(json.dumps([meeting_summary_payload(r) for r in rows], indent=2))
    else:
        for row in rows:
            print(f"{row.id}\t{row.title}\t{row.started_at}")
    return 0


async def _cmd_get(args: argparse.Namespace) -> int:
    settings = load_engine_settings()
    hub = EventBroadcastHub()
    service = MeetingFinalizationService(settings.db_path, MIGRATIONS_DIR, hub)
    found = await service.get_meeting(args.meeting_id)
    if found is None:
        print("not found", file=sys.stderr)
        return 1
    row, segments, extraction = found
    from engine.enhance.meeting_summary_presenter import meeting_detail_payload

    print(json.dumps(meeting_detail_payload(row, segments, extraction), indent=2))
    return 0


async def _cmd_export(args: argparse.Namespace) -> int:
    settings = load_engine_settings()
    hub = EventBroadcastHub()
    service = MeetingFinalizationService(settings.db_path, MIGRATIONS_DIR, hub)
    result = await service.export_transcript(args.meeting_id, args.format)
    if result is None:
        print("not found", file=sys.stderr)
        return 1
    content = result["content"]
    if result.get("encoding") == "base64":
        data = base64.b64decode(str(content))
        if args.output:
            Path(args.output).write_bytes(data)
        else:
            sys.stdout.buffer.write(data)
        return 0
    text = str(content)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


async def _cmd_import(args: argparse.Namespace) -> int:
    settings = load_engine_settings()
    from engine.import_.media_import_service import import_media_file

    meeting_id = await import_media_file(
        settings.db_path, MIGRATIONS_DIR, args.path, args.title
    )
    print(meeting_id)
    return 0


async def _cmd_record(args: argparse.Namespace) -> int:
    settings = load_engine_settings()
    hub = EventBroadcastHub()
    capture = LiveCaptureService(db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR, hub=hub)
    await capture.preload_models()
    if not capture.is_stt_ready:
        print("STT models are not ready", file=sys.stderr)
        return 1
    meeting_id = await capture.start(args.title)
    print(meeting_id, file=sys.stderr)
    try:
        if args.duration is not None:
            await asyncio.sleep(args.duration)
        else:
            print("Recording… Press Ctrl+C to stop.", file=sys.stderr)
            while True:
                await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await capture.stop(reason="cli")
    print(meeting_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omni-cli", description="Omni headless CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List meetings")
    list_p.add_argument("--json", action="store_true")
    list_p.set_defaults(func=_cmd_list)

    get_p = sub.add_parser("get", help="Get meeting detail JSON")
    get_p.add_argument("meeting_id")
    get_p.set_defaults(func=_cmd_get)

    export_p = sub.add_parser("export", help="Export transcript")
    export_p.add_argument("meeting_id")
    export_p.add_argument("--format", choices=["srt", "vtt", "txt", "pdf", "docx", "md"], default="srt")
    export_p.add_argument("-o", "--output")
    export_p.set_defaults(func=_cmd_export)

    import_p = sub.add_parser("import", help="Import media file")
    import_p.add_argument("path")
    import_p.add_argument("--title")
    import_p.set_defaults(func=_cmd_import)

    record_p = sub.add_parser("record", help="Record a live meeting headlessly")
    record_p.add_argument("--title", default="CLI recording")
    record_p.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Stop after N seconds (default: until Ctrl+C)",
    )
    record_p.set_defaults(func=_cmd_record)

    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
