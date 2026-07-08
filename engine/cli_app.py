"""Headless CLI for Omni engine operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.runtime_settings import load_engine_settings
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
    content = await service.export_transcript(args.meeting_id, args.format)
    if content is None:
        print("not found", file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content)
    return 0


async def _cmd_import(args: argparse.Namespace) -> int:
    settings = load_engine_settings()
    from engine.import_.media_import_service import import_media_file

    meeting_id = await import_media_file(
        settings.db_path, MIGRATIONS_DIR, args.path, args.title
    )
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
    export_p.add_argument("--format", choices=["srt", "vtt", "txt"], default="srt")
    export_p.add_argument("-o", "--output")
    export_p.set_defaults(func=_cmd_export)

    import_p = sub.add_parser("import", help="Import media file")
    import_p.add_argument("path")
    import_p.add_argument("--title")
    import_p.set_defaults(func=_cmd_import)

    args = parser.parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
