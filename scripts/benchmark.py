"""Body-MCP benchmark: sequential vs batched vs parallel execution.

Local fixtures only (file://). Measures REAL wall time; nothing is simulated.
Run:  python scripts/benchmark.py [reps]

Reports per mode: median/p95 ms, MCP-call count per task, verified completion rate.
"""
import asyncio
import os
import statistics
import sys
import time

os.environ.setdefault("BODY_MCP_BROWSER_MODE", "headless")
os.environ.setdefault("BODY_MCP_POLITE_DELAY_MS", "0")
os.environ.setdefault("BODY_MCP_CONFIG_DIR",
                      os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                                   ".config", "body_mcp"))


def fixture_url(name: str) -> str:
    return "file:///" + os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", name)
    ).replace("\\", "/")


async def sequential_run():
    from body_mcp import server
    url = fixture_url("test_page.html")
    t0 = time.perf_counter()
    seen = await server.eyes_see_browser(url)
    assert seen["success"]
    q = next(i for i in seen["data"]["inputs"] if i["placeholder"] == "Search the web")
    search = next(b for b in seen["data"]["buttons"] if b["text"] == "Search")
    r1 = await server.hands_type(q["ref"], "agents")
    r2 = await server.hands_click(search["ref"])
    r3 = await server.reflex_verify("Result A about agents")
    dt = (time.perf_counter() - t0) * 1000
    ok = all(x["success"] for x in (r1, r2)) and r3["found"]
    return dt, 4 if ok else 0, ok


async def batch_run():
    from body_mcp import server
    url = fixture_url("test_page.html")
    t0 = time.perf_counter()
    seen = await server.eyes_see_browser(url)
    assert seen["success"]
    q = next(i for i in seen["data"]["inputs"] if i["placeholder"] == "Search the web")
    search = next(b for b in seen["data"]["buttons"] if b["text"] == "Search")
    r = await server.hands_batch([
        {"type": "fill", "field_ref": q["ref"], "text": "agents"},
        {"type": "click", "target": search["ref"]},
        {"type": "verify_text", "expected": "Result A about agents"},
    ])
    dt = (time.perf_counter() - t0) * 1000
    ok = bool(r["success"])
    return dt, 2 if ok else 0, ok


async def parallel_run():
    from body_mcp import server
    t0 = time.perf_counter()
    result = await server.hands_parallel([
        {"id": "a", "actions": [{"type": "goto", "url": fixture_url("test_page.html")},
                                {"type": "verify_text", "expected": "Body-MCP Search"}]},
        {"id": "b", "actions": [{"type": "goto", "url": fixture_url("article.html")},
                                {"type": "verify_text", "expected": "computer-use agents"}]},
    ])
    dt = (time.perf_counter() - t0) * 1000
    ok = bool(result["success"])
    return dt, 1 if ok else 0, ok  # 1 call, 2 tasks


async def parallel_sequential_equivalent_run():
    t0 = time.perf_counter()
    # same two read-verifiable tasks performed sequentially via the shared page
    for name, expected in (("test_page.html", "Body-MCP Search"),
                           ("article.html", "computer-use agents")):
        from body_mcp import server
        seen = await server.eyes_see_browser(fixture_url(name))
        assert seen["success"]
        ver = await server.reflex_verify(expected)
        assert ver["found"]
    dt = (time.perf_counter() - t0) * 1000
    return dt, 4, True


def summarize(name, samples):
    times = [s[0] for s in samples]
    calls = [s[1] for s in samples]
    ok = sum(1 for s in samples if s[2])
    print(f"\n{name}")
    print(f"  runs:            {len(samples)}")
    print(f"  verified ok:     {ok}/{len(samples)}")
    print(f"  median:          {statistics.median(times):.0f} ms")
    print(f"  p95:             {max(times):.0f} ms" if len(times) < 20
          else f"  p95:             {sorted(times)[int(0.95 * len(times)) - 1]:.0f} ms")
    print(f"  calls per task:  {statistics.median(calls):.0f}")


async def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    from body_mcp import browser, permissions
    if not permissions.consent_acknowledged():
        print("NOTE: permissions not acknowledged — benchmark still runs (all actions allowlisted-low-risk).")
    try:
        samples_seq = [await sequential_run() for _ in range(reps)]
        samples_batch = [await batch_run() for _ in range(reps)]
        samples_par = [await parallel_run() for _ in range(reps)]
        samples_par_seq = [await parallel_sequential_equivalent_run() for _ in range(reps)]
    finally:
        await browser.shutdown_browser()
    print("=" * 60)
    print(f"Body-MCP benchmark — local file:// fixtures, {reps} reps each")
    print("=" * 60)
    summarize("Sequential tool calls (eyes->type->click->verify)", samples_seq)
    summarize("hands_batch (eyes->hands_batch{fill,click,verify})", samples_batch)
    summarize("hands_parallel (2 independent tasks, 1 call)", samples_par)
    summarize("Same 2 tasks, sequential", samples_par_seq)
    print("\nNotes: timings include Chromium page loads and are machine-dependent.")
    print("The point is round-trip reduction and verified completion, not click throughput.")


if __name__ == "__main__":
    asyncio.run(main())
