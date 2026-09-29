#!/usr/bin/env python3
"""unpy-mcp benchmark harness (M0).

Two modes:
  replay  — run scenarios against vcr.py cassettes (no live Notion). Measures
            CPU time and peak RSS; good for CI and for spotting CPU/RAM
            regressions, blind to network latency.
  live    — run scenarios against real Notion (needs --token or NOTION_TOKEN_V2).
            Measures wall time per scenario; authoritative for latency wins.

Usage:
  python scripts/bench.py                      # replay mode against cassettes
  python scripts/bench.py --live --token XXX   # live mode
  python scripts/bench.py --scenario page_read --repeat 20
  python scripts/bench.py --json               # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "packages" / "unpy-core" / "src"
CLI_SRC = REPO / "packages" / "unpy-cli" / "src"
MCP_SRC = REPO / "packages" / "unpy-mcp" / "src"
for p in (str(SRC), str(CLI_SRC), str(MCP_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

FAKE_TOKEN = "bench-token-not-real"
REC_DIR = REPO / "tests" / "fixtures" / "recordings"

try:
    import psutil  # optional dev dep — wall RSS without tracemalloc overhead
except ImportError:
    psutil = None

IS_LIVE = False


def peak_rss_mb():
    """Peak RSS of this process in MB."""
    if psutil is not None:
        try:
            mem = psutil.Process(os.getpid()).memory_full_info()
            return (mem.rss + getattr(mem, "shared", 0)) / 1024 / 1024
        except Exception:
            pass
    # Fallback: ru_maxrss from resource (macOS: bytes, Linux: KB)
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def run_scenario(name, fn, repeat, token_v2):
    """Run one scenario repeat+1 times (first is warmup); return metrics."""
    wall_times, peak_traced, cpu_times = [], 0.0, []

    for i in range(repeat + 1):
        t0 = time.perf_counter()
        cpu0 = time.process_time()
        tracemalloc.start()
        result = fn(token_v2)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        wall = time.perf_counter() - t0
        cpu = time.process_time() - cpu0
        peak_traced = max(peak_traced, peak / 1024 / 1024)
        # warmup run (imports, caches) is measured for wall but excluded below
        wall_times.append(wall)
        cpu_times.append(cpu)

    # drop warmup run (imports, caches)
    times = wall_times[1:]
    cpu_timed = sorted(cpu_times[1:])
    return {
        "scenario": name,
        "mode": "live" if IS_LIVE else "replay",
        "repeat": repeat,
        "wall_s": {
            "min": round(min(times), 4),
            "median": round(sorted(times)[len(times) // 2], 4),
            "max": round(max(times), 4),
        },
        "cpu_s": round(cpu_timed[len(cpu_timed) // 2], 4),
        "peak_traced_mb": round(peak_traced, 2),
        "peak_rss_mb": round(peak_rss_mb(), 2),
        "result_type": type(result).__name__,
    }


def build_client(token_v2, use_cassette=True):
    """Create a NotionClient, wrapped in cassette if not live."""
    from unpy import NotionClient

    if IS_LIVE or not use_cassette:
        return NotionClient(token_v2=token_v2)
    import vcr

    my_vcr = vcr.VCR(
        record_mode="none",
        cassette_library_dir=str(REC_DIR),
        serializer="yaml",
        filter_headers=["cookie", "authorization"],
        match_on=["method", "scheme", "host", "path"],
    )
    with my_vcr.use_cassette("client_init.yaml"):
        return NotionClient(token_v2=token_v2)


# ---------------------------------------------------------------------------
# Scenarios — exercise the hot paths identified in the survey:
#   1. sequential per-record reads (Children.__iter__, get_block loops)
#   2. query_collection (fetch_all row walk + render)
#   3. markdown conversion (CPU-bound parser)
#   4. write batching (live only — real HTTP round trips)
# ---------------------------------------------------------------------------

def scenario_client_init(token_v2):
    client = build_client(token_v2)
    assert client.current_user is not None
    return client


def scenario_page_read(token_v2):
    """get_block on the recorded sample page + walk children (loadPageChunk)."""
    client = build_client(token_v2)
    page_id = _find_recorded_page_id() or "44444444-4444-4444-8444-444444444444"
    import vcr

    my_vcr = vcr.VCR(
        record_mode="none",
        cassette_library_dir=str(REC_DIR),
        serializer="yaml",
        filter_headers=["cookie", "authorization"],
        match_on=["method", "scheme", "host", "path"],
    )
    with my_vcr.use_cassette("loadPageChunk.yaml"):
        block = client.get_block(page_id)
    kids = list(block.children) if block else []
    return kids


def scenario_search_read(token_v2):
    """search + per-result get_block walk (sequential per-record path)."""
    client = build_client(token_v2)
    import vcr

    my_vcr = vcr.VCR(
        record_mode="none",
        cassette_library_dir=str(REC_DIR),
        serializer="yaml",
        filter_headers=["cookie", "authorization"],
        match_on=["method", "scheme", "host", "path"],
    )
    with my_vcr.use_cassette("search.yaml"):
        results = client.search_blocks("Benz", limit=5)
    return [b.id for b in results]


def scenario_markdown_roundtrip(token_v2):
    """CPU-bound CommonMark parse + notion_to_markdown segment walk."""
    from unpy import markdown as md

    sample = "# Head\n\nSome *emph* and `code` and [link](https://ex.com).\n\n- a\n- b\n  - nested\n"
    out = []
    for _ in range(200):
        out.append(md.notion_to_markdown(md.markdown_to_notion(sample)))
    return len(out)


def scenario_markdown_parse(token_v2):
    """CPU-bound CommonMark parse + notion_to_markdown segment walk."""
    from unpy import markdown as md

    sample = "# Head\n\nSome *emph* and `code` and [link](https://ex.com).\n\n- a\n- b\n  - nested\n"
    out = []
    for _ in range(200):
        out.append(md.notion_to_markdown(md.markdown_to_notion(sample)))
    return len(out)


_SCENARIOS = {
    "client_init": (scenario_client_init, "init + loadUserContent round trip"),
    "page_read": (scenario_page_read, "get_block + walk children (loadPageChunk)"),
    "search_read": (scenario_search_read, "search + per-result get_block (sequential)"),
    "markdown_200x": (scenario_markdown_roundtrip, "200x markdown <-> notion conversion (CPU)"),
}


def _find_recorded_page_id():
    """Pull a page-ish block id out of the loadPageChunk cassette."""
    try:
        import yaml

        with open(REC_DIR / "loadPageChunk.yaml") as f:
            cass = yaml.safe_load(f)
        for inter in cass.get("interactions", []):
            body = inter.get("request", {}).get("body", "")
            try:
                data = json.loads(body) if isinstance(body, str) else body
            except ValueError:
                continue
            pid = (data or {}).get("pageId")
            if pid:
                return pid
    except Exception:
        pass
    return None


def _find_any_collection_id():
    try:
        import yaml

        with open(REC_DIR / "queryCollection.yaml") as f:
            cass = yaml.safe_load(f)
        for inter in cass.get("interactions", []):
            body = inter.get("request", {}).get("body", "")
            try:
                data = json.loads(body) if isinstance(body, str) else body
            except ValueError:
                continue
            src = ((data or {}).get("source") or {})
            return src.get("id")
    except Exception:
        pass
    return None


# alias to keep naming consistent
_find_any_collection_id = _find_any_collection_id
_find_any_collection_id_name = _find_any_collection_id


def main():
    global IS_LIVE
    ap = argparse.ArgumentParser(description="unpy-mcp bench harness")
    ap.add_argument("--live", action="store_true", help="hit real Notion (needs token)")
    ap.add_argument("--token", default=None, help="token_v2 cookie value")
    ap.add_argument("--repeat", type=int, default=5, help="timed runs (plus warmup)")
    ap.add_argument("--scenario", action="append", default=None,
                    help="scenario name, repeatable; default: all")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    IS_LIVE = args.live
    token_v2 = args.token or os.environ.get("NOTION_TOKEN_V2")
    if IS_LIVE and not token_v2:
        ap.error("--live requires --token or NOTION_TOKEN_V2")

    wanted = args.scenario or list(_SCENARIOS)
    unknown = [w for w in wanted if w not in _SCENARIOS]
    if unknown:
        ap.error(f"unknown scenarios: {unknown}; known: {list(_SCENARIOS)}")

    results = []
    for name in wanted:
        fn, _desc = _SCENARIOS[name]
        results.append(run_scenario(name, fn, args.repeat, token_v2 or FAKE_TOKEN))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"unpy-mcp bench — mode={results[0]['mode']} repeat={args.repeat}")
        print(f"{'scenario':<20} {'wall median':>12} {'wall min':>10} {'cpu':>8} {'traced MB':>10} {'RSS MB':>8}")
        for r in results:
            w = r["wall_s"]
            print(f"{r['scenario']:<20} {w['median']:>12.4f} {w['min']:>10.4f} "
                  f"{r['cpu_s']:>8.4f} {r['peak_traced_mb']:>10.2f} {r['peak_rss_mb']:>8.2f}")

    # non-zero exit if any scenario produced nothing (missing fixtures etc.)
    return 0 if all(r["result_type"] != "NoneType" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())