#!/usr/bin/env python3
"""
Simple async benchmark for FIXTranslator parse endpoint.

Usage:
  python tools/bench_send.py --url http://localhost:9000/parse --concurrency 50 --count 5000

This will send `count` messages using `concurrency` tasks and print throughput/latency.
"""
import argparse
import asyncio
import time
import statistics
import aiohttp

SAMPLE = "8=FIX.4.4|9=176|35=D|49=CLIENT12|56=BROKER03|11=BENCH{n}|55=EUR/USD|54=1|38=1000|40=2|44=1.1850|60=20250929-12:00:00|10=000|"

async def worker(name, queue, url, session, latencies):
    while True:
        n = await queue.get()
        if n is None:
            queue.task_done()
            break
        payload = {"raw": SAMPLE.format(n=n)}
        t0 = time.perf_counter()
        try:
            async with session.post(url, json=payload, timeout=10) as resp:
                await resp.text()
        except Exception as e:
            print(f"worker {name} error: {e}")
        finally:
            t1 = time.perf_counter()
            latencies.append(t1 - t0)
            queue.task_done()

async def run(url, concurrency, total):
    queue = asyncio.Queue()
    for i in range(total):
        queue.put_nowait(i)
    for _ in range(concurrency):
        queue.put_nowait(None)  # sentinel per worker

    latencies = []
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(worker(f"w{i}", queue, url, session, latencies)) for i in range(concurrency)]
        t0 = time.perf_counter()
        await queue.join()
        t1 = time.perf_counter()
        for t in tasks:
            t.cancel()
    # report stats
    total_time = t1 - t0
    rps = total / total_time if total_time>0 else 0
    print(f"Sent {total} requests in {total_time:.2f}s — RPS: {rps:.2f}")
    if latencies:
        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=100)[94]
        p99 = statistics.quantiles(latencies, n=100)[98]
        print(f"Latency p50 {p50*1000:.2f}ms p95 {p95*1000:.2f}ms p99 {p99*1000:.2f}ms")
    else:
        print("No latencies recorded")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:9000/parse")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.concurrency, args.count))

if __name__ == "__main__":
    main()
