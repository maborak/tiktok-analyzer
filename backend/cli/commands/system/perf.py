"""Lives-list performance benchmark CLI.

Measures the wall-clock latency of the three endpoints the
`/admin/tiktok` Lives page fires on mount, plus a Promise.all-style
concurrent batch that mirrors the page's actual call pattern. Output
is human-readable to stdout and (optionally) JSON for A/B diffing
across phases.

Usage:
    # Baseline before any changes:
    python cli.py system tiktok perf endpoints \\
        --token "$TOKEN" \\
        --label phase-0-baseline \\
        --json-out .claude/tracking/perf/phase-0-baseline.json

    # After shipping a phase:
    python cli.py system tiktok perf endpoints \\
        --token "$TOKEN" \\
        --label phase-1-frontend \\
        --json-out .claude/tracking/perf/phase-1-frontend.json

    # Diff:
    python cli.py system tiktok perf compare \\
        .claude/tracking/perf/phase-0-baseline.json \\
        .claude/tracking/perf/phase-1-frontend.json
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import click
import httpx


# Endpoint(s) fired on cold mount of /admin/tiktok. Post Phase 2
# this collapses to one bundle endpoint that returns subs+summary+totals
# in a single response. Earlier phases timed three separate endpoints;
# old baseline JSON files still load fine — the compare command tolerates
# different endpoint shapes by only diffing entries present in both.
ENDPOINTS = (
    ("GET /admin/tiktok/lives/bundle",  "/admin/tiktok/lives/bundle"),
)


@click.group(name="perf")
def perf_group() -> None:
    """Performance tests for the /admin/tiktok lives list."""


@perf_group.command(name="endpoints")
@click.option("--base-url", default="http://localhost:9020", show_default=True,
              help="API base URL (omit trailing slash).")
@click.option("--token", envvar="PHOVEU_ADMIN_TOKEN", required=True,
              help="Admin JWT. Falls back to $PHOVEU_ADMIN_TOKEN.")
@click.option("--runs", type=int, default=20, show_default=True,
              help="Warm Promise.all batches to time.")
@click.option("--warmup", type=int, default=3, show_default=True,
              help="Untimed warmup batches to fill the service-layer cache.")
@click.option("--label", default="unlabeled", show_default=True,
              help="Tag stored in the JSON output (e.g. phase-1-frontend).")
@click.option("--json-out", "json_out", type=click.Path(dir_okay=False),
              help="Write report JSON to this path.")
def perf_endpoints_cmd(
    base_url: str,
    token: str,
    runs: int,
    warmup: int,
    label: str,
    json_out: Optional[str],
) -> None:
    """Time the /admin/tiktok Lives page's network call.

    Cold-miss timing fires the bundle endpoint as the very first
    request after the script starts — useful right after a uvicorn
    restart to capture the empty-cache wall-clock. (Pre-Phase 2
    baselines time three endpoints; the JSON shape is forward-
    compatible.)

    Warm timing mirrors the steady-state poll: one request per
    cycle, p50 / p95 across `runs`."""
    report = asyncio.run(
        _run_endpoints(base_url, token, runs, warmup, label),
    )
    _print_report(report)
    if json_out:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))
        click.secho(f"\nWrote {path}", fg="green")


async def _run_endpoints(
    base_url: str,
    token: str,
    runs: int,
    warmup: int,
    label: str,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0, headers=headers) as client:
        # First batch is the cold mount: time each endpoint as a
        # standalone request so we can see which one is dominating.
        cold: dict[str, dict[str, Any]] = {}
        for name, path in ENDPOINTS:
            t0 = time.perf_counter()
            r = await client.get(path)
            dt_ms = (time.perf_counter() - t0) * 1000
            cold[name] = {
                "ms": round(dt_ms, 2),
                "status": r.status_code,
                "bytes": len(r.content),
            }

        # Warm batches: mirror Promise.all([listLives, livesSummary,
        # livesTotals]). httpx.AsyncClient reuses the HTTP/1.1 keep-
        # alive connection pool, so this captures real polled-tab
        # behaviour rather than a brand-new-TCP round-trip.
        warm_batches: list[dict[str, Any]] = []
        for i in range(warmup + runs):
            t0 = time.perf_counter()
            responses = await asyncio.gather(*[client.get(p) for _, p in ENDPOINTS])
            total_ms = (time.perf_counter() - t0) * 1000
            per = {
                name: {
                    "status": r.status_code,
                    "bytes": len(r.content),
                }
                for (name, _), r in zip(ENDPOINTS, responses)
            }
            warm_batches.append({"total_ms": round(total_ms, 2), "per": per})
        timed = warm_batches[warmup:]

    totals = [b["total_ms"] for b in timed]
    warm_summary = {
        "total_p50_ms": round(statistics.median(totals), 2),
        "total_p95_ms": round(_p95(totals), 2),
        "total_min_ms": round(min(totals), 2),
        "total_max_ms": round(max(totals), 2),
        "total_mean_ms": round(statistics.mean(totals), 2),
        "runs": len(timed),
    }
    return {
        "label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "warmup": warmup,
        "cold": cold,
        "warm": warm_summary,
    }


def _p95(values: list[float]) -> float:
    """`statistics.quantiles(n=20)[-1]` is the 95th percentile when
    n≥20, but errors on smaller samples. Fall back to `max()` for
    short runs."""
    if len(values) < 20:
        return max(values)
    return statistics.quantiles(values, n=20)[18]


def _print_report(r: dict[str, Any]) -> None:
    click.secho(f"\n=== {r['label']} ===", fg="cyan", bold=True)
    click.echo(f"  {r['timestamp']}  ({r['base_url']})\n")

    click.secho("  Cold mount — each endpoint, sequential, empty service cache:", bold=True)
    cold_total = 0.0
    for name, info in r["cold"].items():
        status_col = "green" if info["status"] == 200 else "red"
        click.echo(
            f"    {name:46s} "
            f"{info['ms']:7.1f} ms  "
            f"{info['bytes']:>8d} B  "
        )
        click.secho(f"      status={info['status']}", fg=status_col, nl=False)
        click.echo("")
        cold_total += info["ms"]
    click.secho(f"    TOTAL (sequential):                          {cold_total:7.1f} ms\n", bold=True)

    click.secho(f"  Warm Promise.all — all 3 endpoints concurrent, x{r['warm']['runs']} runs:", bold=True)
    click.echo(f"    p50:  {r['warm']['total_p50_ms']:7.1f} ms")
    click.echo(f"    p95:  {r['warm']['total_p95_ms']:7.1f} ms")
    click.echo(f"    min:  {r['warm']['total_min_ms']:7.1f} ms")
    click.echo(f"    max:  {r['warm']['total_max_ms']:7.1f} ms")
    click.echo(f"    mean: {r['warm']['total_mean_ms']:7.1f} ms")


@perf_group.command(name="compare")
@click.argument("baseline", type=click.Path(exists=True, dir_okay=False))
@click.argument("current",  type=click.Path(exists=True, dir_okay=False))
def perf_compare_cmd(baseline: str, current: str) -> None:
    """Diff two perf-endpoints JSON reports (baseline vs current).

    Negative deltas = current is faster. The p50 row is the headline
    "did the page get faster" number; per-endpoint cold-miss deltas
    tell you which layer absorbed the work."""
    b = json.loads(Path(baseline).read_text())
    c = json.loads(Path(current).read_text())

    click.secho(
        f"\nBaseline: {b['label']}  ({b['timestamp']})\n"
        f"Current:  {c['label']}  ({c['timestamp']})\n",
        fg="cyan", bold=True,
    )

    click.secho("Cold mount — per endpoint:", bold=True)
    for name in b["cold"]:
        b_ms = b["cold"][name]["ms"]
        c_ms = c["cold"].get(name, {}).get("ms")
        if c_ms is None:
            click.echo(f"  {name:46s} {b_ms:7.1f} → (missing)")
            continue
        delta = c_ms - b_ms
        pct = (delta / b_ms * 100) if b_ms > 0 else 0.0
        colour = "green" if delta < 0 else "yellow" if delta < 50 else "red"
        click.echo(
            f"  {name:46s} {b_ms:7.1f} → {c_ms:7.1f} ms  "
        )
        click.secho(f"    ({delta:+7.1f} ms, {pct:+6.1f}%)", fg=colour)

    click.echo("")
    click.secho("Warm Promise.all (p50):", bold=True)
    bp = b["warm"]["total_p50_ms"]
    cp = c["warm"]["total_p50_ms"]
    delta = cp - bp
    pct = (delta / bp * 100) if bp > 0 else 0.0
    colour = "green" if delta < 0 else "yellow" if delta < 25 else "red"
    click.echo(f"  {bp:7.1f} → {cp:7.1f} ms")
    click.secho(f"    ({delta:+7.1f} ms, {pct:+6.1f}%)", fg=colour)

    click.secho("Warm Promise.all (p95):", bold=True)
    bp = b["warm"]["total_p95_ms"]
    cp = c["warm"]["total_p95_ms"]
    delta = cp - bp
    colour = "green" if delta < 0 else "yellow" if delta < 50 else "red"
    click.echo(f"  {bp:7.1f} → {cp:7.1f} ms")
    click.secho(f"    ({delta:+7.1f} ms)", fg=colour)
