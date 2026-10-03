"""Open-loop HTTP/1.1 load generator. Every scheduled arrival has one raw record."""
import argparse
import asyncio
import json
import math
from pathlib import Path
import resource
import time
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from tools.common import matches, workload
from tools.metrics import Accumulator, passes


async def run(base, scenario, phases, output, seed=20261003, max_inflight=10000, max_lag_ms=10):
    if not phases or max_inflight < 1 or max_lag_ms < 0:
        raise ValueError('Nonempty phases, positive inflight limit and nonnegative lag budget required')
    for duration, rate in phases:
        if not math.isfinite(duration) or not math.isfinite(rate) or duration <= 0 or rate <= 0:
            raise ValueError('Duration and RPS must be finite and positive')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    # All tasks consume from this producer at their scheduled times, independent of completions.
    aggregate = Accumulator(max_lag_ms)
    windows = {}
    raw = (output / "requests.jsonl").open("w", buffering=1024*1024)

    def record(row):
        raw.write(json.dumps(row, separators=(",", ":"))+"\n")
        aggregate.add(row)
        window = int(row["scheduled_s"]//10)*10
        if window not in windows:
            windows[window] = Accumulator(max_lag_ms)
        windows[window].add(row)
    pending = set()
    start = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_SELF)
    index = 0
    offsets = []
    offset = 0.0
    for duration, rate in phases:
        if duration <= 0 or rate <= 0:
            raise ValueError('Duration and RPS must be positive')
        offsets.append((offset, duration, rate))
        offset += duration
    async with ClientSession(connector=TCPConnector(limit=0), timeout=ClientTimeout(total=2),
                             auto_decompress=False, headers={'Accept-Encoding': 'identity'}) as client:
        client._retry_connection = False

        async def request(i, scheduled, rate):
            method, path, data, expected = workload(scenario, i, seed)
            began = time.perf_counter()
            row = {'index': i, 'scheduled_s': scheduled, 'started_s': began-start,
                   'lag_ms': max(0, (began-start-scheduled)*1000), 'target_rps': rate,
                   'ok': False, 'content_error': False, 'status': None, 'error': None}
            try:
                async with client.request(method, base+path, json=data if method == 'POST' else None,
                                          allow_redirects=False) as response:
                    body = await response.read()
                    row['latency_ms'] = (time.perf_counter()-began)*1000
                    row['status'] = response.status
                    row['content_error'] = response.status == 200 and not matches(body, expected, response.headers.get('Content-Type', ''))
                    row['ok'] = response.status == 200 and not row['content_error']
            except Exception as ex:
                row['latency_ms'] = (time.perf_counter()-began)*1000
                row['error'] = type(ex).__name__
            record(row)

        for phase_start, duration, rate in offsets:
            for n in range(math.ceil(duration*rate)):
                scheduled = phase_start+n/rate
                delay = start+scheduled-time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                lag = max(0, (time.perf_counter()-start-scheduled)*1000)
                if lag > max_lag_ms or len(pending) >= max_inflight:
                    record({'index': index, 'scheduled_s': scheduled, 'lag_ms': lag,
                                 'target_rps': rate, 'dropped': True})
                else:
                    task = asyncio.create_task(request(index, scheduled, rate))
                    pending.add(task)
                    task.add_done_callback(pending.discard)
                index += 1
                # Yield even when behind schedule to avoid starving already dispatched requests.
                if n % 64 == 0:
                    await asyncio.sleep(0)
        await asyncio.sleep(max(0, start+offset-time.perf_counter()))
        await asyncio.gather(*pending)
    elapsed = time.perf_counter()-start
    after = resource.getrusage(resource.RUSAGE_SELF)
    raw.close()
    result = aggregate.summary(offset, sum(duration*rate for duration,rate in phases)/offset)
    result.update({'scenario': scenario, 'seed': seed, 'duration_s': offset, 'elapsed_with_drain_s': elapsed,
                   'phases': phases, 'max_inflight': max_inflight, 'max_lag_ms': max_lag_ms,
                   'generator': {'cpu_seconds': after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                                 'peak_rss_kib': after.ru_maxrss},
                   'windows': []})
    for window_start, acc in sorted(windows.items()):
        duration = min(10, offset-window_start)
        target = sum(max(0, min(window_start+duration, phase_start+length)-max(window_start, phase_start))*rate for phase_start,length,rate in offsets)/duration
        result['windows'].append({'start_s': window_start, **acc.summary(duration, target)})
    if len(phases) == 2:
        streak = 0
        result['recovery_seconds'] = None
        for window in result['windows']:
            if window['start_s'] < phases[0][0] or window['start_s']+10 > offset:
                continue
            streak = streak+1 if passes(window) else 0
            if streak == 3:
                result['recovery_seconds'] = window['start_s']+10-phases[0][0]
                break
    (output / 'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('url');p.add_argument('scenario', choices=['json','cpu','io'])
    p.add_argument('--rps', type=float, default=100);p.add_argument('--seconds', type=float, default=10)
    p.add_argument('--output', required=True);p.add_argument('--seed', type=int, default=20261003)
    p.add_argument('--max-inflight', type=int, default=10000);p.add_argument('--max-lag-ms', type=float, default=10)
    a=p.parse_args()
    print(json.dumps(asyncio.run(run(a.url,a.scenario,[(a.seconds,a.rps)],a.output,a.seed,a.max_inflight,a.max_lag_ms)),indent=2))
