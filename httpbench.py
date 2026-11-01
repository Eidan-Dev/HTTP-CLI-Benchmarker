#!/usr/bin/env python3
"""
httpbench - HTTP benchmark & stress-test command-line tool.

Installation:
    pip install aiohttp rich

Examples:
    python httpbench.py https://example.com -n 10000 -c 200
    python httpbench.py https://api.example.com/items -c 500 -d 60 --rps 3000
    python httpbench.py https://api.example.com/login -m POST \
        -H "Content-Type: application/json" -b '{"user":"a","pass":"b"}' \
        -c 100 -n 5000 --json report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from array import array
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

console = Console()


# ----------------------------------------------------------------- Metrics

@dataclass
class Stats:
    started: float = 0.0
    finished: float = 0.0
    sent: int = 0                      # requests reserved (sent or in flight)
    ok: int = 0                        # HTTP responses < 400
    http_errors: int = 0               # HTTP responses >= 400
    transport_errors: int = 0          # timeouts, refused connections, etc.
    bytes_recv: int = 0
    status: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)
    # All latencies, used for the final report (array('d') = 8 bytes per value)
    latencies: array = field(default_factory=lambda: array("d"))
    # Sliding window, used for live percentiles
    recent: deque = field(default_factory=lambda: deque(maxlen=5000))

    def record(self, latency: float, status: int, nbytes: int) -> None:
        self.latencies.append(latency)
        self.recent.append(latency)
        self.status[status] += 1
        self.bytes_recv += nbytes
        if status < 400:
            self.ok += 1
        else:
            self.http_errors += 1

    def record_error(self, kind: str) -> None:
        self.transport_errors += 1
        self.errors[kind] += 1

    @property
    def done(self) -> int:
        return self.ok + self.http_errors + self.transport_errors


def percentile(sorted_vals, q: float) -> float:
    """Percentile with linear interpolation on an already sorted list."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * q / 100
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def ms(seconds: float) -> str:
    return f"{seconds * 1000:,.1f} ms"


# ------------------------------------------------------------ Rate limiter

class Pacer:
    """
    Open-loop rate limiter: each request is scheduled on a regular time slot,
    independently of the server's response time.
    """

    def __init__(self, rps: Optional[float]):
        self.interval = 1.0 / rps if rps else 0.0
        self.next_slot = 0.0

    async def wait(self) -> None:
        if not self.interval:
            return
        now = time.perf_counter()
        if self.next_slot < now:
            self.next_slot = now
        slot = self.next_slot
        self.next_slot += self.interval
        if slot > now:
            await asyncio.sleep(slot - now)


# ------------------------------------------------------------ Benchmark core

async def send_one(session: aiohttp.ClientSession, args, stats: Stats) -> None:
    t0 = time.perf_counter()
    try:
        async with session.request(
            args.method,
            args.url,
            headers=args.headers,
            data=args.body,
            ssl=args.ssl,
        ) as resp:
            payload = await resp.read()      # measure the full download
            latency = time.perf_counter() - t0
            stats.record(latency, resp.status, len(payload))
    except asyncio.TimeoutError:
        stats.record_error("timeout")
    except aiohttp.ClientConnectorError:
        stats.record_error("connection")
    except aiohttp.ClientError as exc:
        stats.record_error(type(exc).__name__)
    except Exception as exc:                 # a worker must never die
        stats.record_error(type(exc).__name__)


async def worker(session, args, stats: Stats, pacer: Pacer, deadline: Optional[float]) -> None:
    while True:
        if deadline is not None and time.perf_counter() >= deadline:
            return
        if args.requests is not None and stats.sent >= args.requests:
            return
        stats.sent += 1                      # synchronous reservation (no race in asyncio)
        await pacer.wait()
        await send_one(session, args, stats)


# ------------------------------------------------------------ Live dashboard

def render(stats: Stats, args, state: dict, now: float) -> Panel:
    elapsed = now - stats.started
    dt = now - state["t"]
    inst_rps = (stats.done - state["done"]) / dt if dt > 0 else 0.0
    state["t"], state["done"] = now, stats.done

    if args.requests:
        pct = min(stats.done / args.requests, 1.0)
        progress = f"{stats.done:,}/{args.requests:,} req"
    else:
        pct = min(elapsed / args.duration, 1.0)
        progress = f"{elapsed:,.0f}s/{args.duration:g}s"

    width = 30
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)

    recent = sorted(stats.recent)
    avg_rps = stats.done / elapsed if elapsed > 0 else 0.0
    errors = stats.http_errors + stats.transport_errors
    codes = ", ".join(f"{c}: {n:,}" for c, n in sorted(stats.status.items())) or "-"

    grid = Table(show_header=False, box=None, padding=(0, 2))
    grid.add_column(style="bold cyan", justify="right")
    grid.add_column()
    grid.add_row("Progress", f"{bar} {pct * 100:5.1f}%  {progress}")
    grid.add_row("Requests/s", f"[bold green]{inst_rps:,.0f}[/]  (average {avg_rps:,.0f})")
    grid.add_row("Success / Errors", f"[green]{stats.ok:,}[/] / [red]{errors:,}[/]")
    grid.add_row(
        "Latency p50 / p95 / p99",
        f"{ms(percentile(recent, 50))} / {ms(percentile(recent, 95))} / {ms(percentile(recent, 99))}",
    )
    grid.add_row("HTTP codes", codes)

    return Panel(grid, title=f"[bold]httpbench[/] → {args.url}", border_style="blue")


async def ui_loop(stats: Stats, args, stop: asyncio.Event) -> None:
    state = {"t": time.perf_counter(), "done": 0}
    with Live(render(stats, args, state, time.perf_counter()),
              console=console, refresh_per_second=8) as live:
        while not stop.is_set():
            await asyncio.sleep(0.125)
            live.update(render(stats, args, state, time.perf_counter()))


async def run(args, stats: Stats) -> None:
    deadline = time.perf_counter() + args.duration if args.duration else None
    connector = aiohttp.TCPConnector(limit=args.concurrency, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    stop = asyncio.Event()
    pacer = Pacer(args.rps)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        stats.started = time.perf_counter()
        ui = None if args.quiet else asyncio.create_task(ui_loop(stats, args, stop))
        workers = [
            asyncio.create_task(worker(session, args, stats, pacer, deadline))
            for _ in range(args.concurrency)
        ]
        try:
            await asyncio.gather(*workers)
        finally:
            stats.finished = time.perf_counter()
            stop.set()
            if ui:
                await ui


# ----------------------------------------------------------------- Report

def summarize(stats: Stats, args) -> None:
    if not stats.started:
        console.print("[yellow]No requests were executed.[/]")
        return

    total_time = max(stats.finished - stats.started, 1e-9)
    lat = sorted(stats.latencies)
    errors = stats.http_errors + stats.transport_errors
    rps = stats.done / total_time

    console.rule("[bold]Results")
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column(style="bold cyan", justify="right")
    t.add_column()
    t.add_row("Requests", f"{stats.done:,}  (success {stats.ok:,}, errors {errors:,})")
    t.add_row("Duration", f"{total_time:.2f} s")
    t.add_row("Average throughput", f"[bold green]{rps:,.1f} req/s[/]")
    t.add_row("Data received", f"{stats.bytes_recv / 1e6:,.2f} MB")

    report_latency = {}
    if lat:
        mean = statistics.fmean(lat)
        std = statistics.pstdev(lat) if len(lat) > 1 else 0.0
        t.add_row("Latency min", ms(lat[0]))
        t.add_row("Latency mean", f"{ms(mean)}  (stdev {ms(std)})")
        for q in (50, 90, 95, 99):
            t.add_row(f"Latency p{q}", ms(percentile(lat, q)))
        t.add_row("Latency max", ms(lat[-1]))
        report_latency = {
            "min_ms": lat[0] * 1000,
            "mean_ms": mean * 1000,
            "stdev_ms": std * 1000,
            **{f"p{q}_ms": percentile(lat, q) * 1000 for q in (50, 90, 95, 99)},
            "max_ms": lat[-1] * 1000,
        }
    console.print(t)

    if stats.status:
        st = Table(title="HTTP status codes", box=None)
        st.add_column("Code", style="bold")
        st.add_column("Occurrences", justify="right")
        for code, n in sorted(stats.status.items()):
            color = "green" if code < 400 else "red"
            st.add_row(f"[{color}]{code}[/]", f"{n:,}")
        console.print(st)

    if stats.errors:
        et = Table(title="Transport errors", box=None)
        et.add_column("Type", style="bold red")
        et.add_column("Occurrences", justify="right")
        for kind, n in stats.errors.most_common():
            et.add_row(kind, f"{n:,}")
        console.print(et)
        if stats.errors.get("connection", 0) > 0:
            console.print(
                "[dim]Tip: mass connection errors are often caused by the file descriptor "
                "limit (ulimit -n). Try `ulimit -n 65535`.[/]"
            )

    if args.json:
        report = {
            "url": args.url,
            "method": args.method,
            "concurrency": args.concurrency,
            "requests": stats.done,
            "ok": stats.ok,
            "http_errors": stats.http_errors,
            "transport_errors": stats.transport_errors,
            "duration_s": total_time,
            "rps": rps,
            "bytes_received": stats.bytes_recv,
            "status_codes": {str(k): v for k, v in sorted(stats.status.items())},
            "error_types": dict(stats.errors),
            "latency": report_latency,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        console.print(f"JSON report written to [bold]{args.json}[/]")


# -------------------------------------------------------------------- CLI

def parse_args():
    p = argparse.ArgumentParser(
        description="httpbench - ultra-fast HTTP benchmark & stress-test tool",
    )
    p.add_argument("url", help="target URL (http:// or https://)")
    p.add_argument("-n", "--requests", type=int, help="total number of requests")
    p.add_argument("-d", "--duration", type=float, help="maximum duration in seconds")
    p.add_argument("-c", "--concurrency", type=int, default=50,
                   help="number of simultaneous requests (default: 50)")
    p.add_argument("-m", "--method", default="GET", help="HTTP method (default: GET)")
    p.add_argument("-H", "--header", action="append", default=[], metavar="'Key: value'",
                   help="HTTP header (repeatable)")
    p.add_argument("-b", "--body", help="request body, or @file")
    p.add_argument("-t", "--timeout", type=float, default=10.0,
                   help="timeout per request in seconds (default: 10)")
    p.add_argument("--rps", type=float, help="limit to N requests per second")
    p.add_argument("-k", "--insecure", action="store_true",
                   help="do not verify the SSL certificate")
    p.add_argument("--json", metavar="FILE", help="export the report as JSON")
    p.add_argument("-q", "--quiet", action="store_true", help="disable live display")
    args = p.parse_args()

    if not args.url.startswith(("http://", "https://")):
        p.error("the URL must start with http:// or https://")
    if args.concurrency < 1:
        p.error("--concurrency must be >= 1")
    if not args.requests and not args.duration:
        args.requests = 1000  # default value

    headers = {}
    for h in args.header:
        key, sep, value = h.partition(":")
        if not sep:
            p.error(f"invalid header: {h!r} (expected format: 'Key: value')")
        headers[key.strip()] = value.strip()
    args.headers = headers

    body = args.body
    if body and body.startswith("@"):
        with open(body[1:], "rb") as f:
            body = f.read()
    args.body = body

    args.method = args.method.upper()
    args.ssl = False if args.insecure else None
    return args


def main() -> None:
    args = parse_args()
    stats = Stats()
    try:
        asyncio.run(run(args, stats))
    except KeyboardInterrupt:
        if not stats.finished:
            stats.finished = time.perf_counter()
        console.print("\n[yellow]Interrupted: partial report.[/]")
    summarize(stats, args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        console.print(f"[red]Fatal error: {exc}[/]")
        sys.exit(1)