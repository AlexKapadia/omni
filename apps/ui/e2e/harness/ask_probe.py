"""Health-gate probe: prove the REAL engine answers a REAL ask.query before the
suite records anything. Connects over the pinned WS protocol, sends one
ask.query, and prints a counts-only verdict (never the answer text or any key).

Exit 0 only when the engine returns a genuine ask.answer with no_answer=false;
exit non-zero (fail loud) otherwise — we never proceed against a broken stack.
"""

import argparse
import asyncio
import json
import sys
import uuid

import websockets


async def probe(url: str, query: str) -> int:
    async with websockets.connect(url) as ws:
        cmd = {"v": 1, "kind": "command", "name": "ask.query", "id": str(uuid.uuid4()),
               "payload": {"query": query}}
        await ws.send(json.dumps(cmd))
        # Read frames until our correlated reply arrives (skip heartbeats/events).
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            msg = json.loads(raw)
            if msg.get("kind") != "reply" or msg.get("id") != cmd["id"]:
                continue
            name = msg.get("name")
            payload = msg.get("payload", {})
            if name == "ask.answer":
                no_answer = bool(payload.get("no_answer", True))
                citations = payload.get("citations", []) or []
                latency = payload.get("latency", {})
                print(
                    f"ask.answer: no_answer={no_answer} citations={len(citations)} "
                    f"retrieval_ms={latency.get('retrieval_ms')} synthesis_ms={latency.get('synthesis_ms')}"
                )
                return 0 if (not no_answer and len(citations) > 0) else 2
            print(f"ask refused: name={name} code={payload.get('code')} message={payload.get('message')}")
            return 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--query", default="What did we agree on the Northwind renewal?")
    args = parser.parse_args()
    sys.exit(asyncio.run(probe(args.url, args.query)))


if __name__ == "__main__":
    main()
