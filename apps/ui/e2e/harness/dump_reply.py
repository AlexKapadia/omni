"""Dev-only diagnostic: send one command over the engine WS and pretty-print the
correlated reply payload, so we can diff the real contract against the UI
parser. Counts/keys only in practice — but this dumps the full structure to
find contract drift (never run against production data; synthetic seed only)."""

import argparse
import asyncio
import json
import sys
import uuid

import websockets


async def probe(url: str, name: str, payload: dict) -> int:
    async with websockets.connect(url) as ws:
        cmd = {"v": 1, "kind": "command", "name": name, "id": str(uuid.uuid4()), "payload": payload}
        await ws.send(json.dumps(cmd))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            msg = json.loads(raw)
            if msg.get("kind") != "reply" or msg.get("id") != cmd["id"]:
                continue
            reply = {"name": msg.get("name"), "payload": msg.get("payload")}
            print(json.dumps(reply, indent=2, default=str))
            return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--name", required=True)
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args()
    sys.exit(asyncio.run(probe(args.url, args.name, json.loads(args.payload))))


if __name__ == "__main__":
    main()
