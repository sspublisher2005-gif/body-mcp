"""LIVE proof of the research adapters through the real body-dev MCP server.

    python scripts/research_live.py "coding agent memory"

Calls research_source for every public source and the fallback chain, and prints
the real records. No accounts, no keys, no paid services.
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from body_mcp import server  # noqa: E402

QUERY = sys.argv[1] if len(sys.argv) > 1 else "coding agent memory"


async def main() -> int:
    print(f"query: {QUERY!r}\n")
    matrix = await server.research_sources()
    for entry in matrix["data"]["sources"]:
        flag = "READ " if entry["available"] else "BLOCK"
        print(f"  [{flag}] {entry['source']:<15} {entry['access']}")

    for source in ("hackernews", "reddit", "github_issues", "stackoverflow", "wikipedia",
                   "youtube"):
        started = time.time()
        result = await server.research_source(source, QUERY, 4)
        data = result.get("data", {})
        took = round((time.time() - started) * 1000)
        if result["success"]:
            items = data.get("items", [])
            print(f"\n== {source}: {len(items)} record(s) in {took} ms ==")
            for item in items[:4]:
                print(f"   - {item['title'][:66]!r}")
                print(f"     {item['url'][:88]}")
                print(f"     author={item['author']!r} date={item['created']!r} "
                      f"score={item['score']} comments={item['comments']}")
        else:
            print(f"\n== {source}: no records ({took} ms) ==")
            print(f"   reason: {result['message'][:140]}")
            if data.get("limitation"):
                print(f"   limitation: {str(data['limitation'])[:140]}")

    print("\n== fallback chain ==")
    chain = await server.research_any(QUERY, limit=4)
    print(f"   success={chain['success']} source={chain.get('data', {}).get('source')} "
          f"count={chain.get('data', {}).get('count')}")
    for entry in chain.get("data", {}).get("tried", []):
        print(f"   tried {entry['source']:<20} ok={entry['ok']} {entry['reason'][:80]}")
    return 0


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
