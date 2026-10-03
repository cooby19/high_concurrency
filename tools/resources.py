"""Read the entire container cgroup v2, including every worker and child."""
import asyncio
import json
import shlex
import time

CGROUP = 'cat /sys/fs/cgroup/cpu.stat; echo memory_current; cat /sys/fs/cgroup/memory.current; echo memory_peak; cat /sys/fs/cgroup/memory.peak; echo memory_events; cat /sys/fs/cgroup/memory.events'


async def command(args):
    if args[0] == "ssh":
        args = args[:2] + [shlex.join(args[2:])]
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(f'{args[0]} exited {process.returncode}: {stderr.decode()[:300]}')
    return stdout.decode().strip()


def parse(raw):
    result = {}
    section = None
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2:
            result[('memory_' if section == 'memory_events' else '')+parts[0]] = int(parts[1])
        elif line in ('memory_current', 'memory_peak', 'memory_events'):
            section = line
        elif section:
            result[section] = int(line)
    required = {'usage_usec','throttled_usec','nr_throttled','memory_current','memory_peak','memory_oom_kill'}
    if not required <= result.keys():
        raise ValueError('Required cgroup v2 counters unavailable')
    return result


async def sample(prefix, name):
    return {'time': time.time(), **parse(await command(prefix+['exec', name, 'sh', '-c', CGROUP]))}


async def monitor(prefix, name, rows, stop, interval=1):
    while not stop.is_set():
        rows.append(await sample(prefix, name))
        try:
            await asyncio.wait_for(stop.wait(), interval)
        except asyncio.TimeoutError:
            pass


def summary(rows, correct):
    if len(rows) < 2:
        raise ValueError('Missing resource samples')
    first, last = rows[0], rows[-1]
    cpu = (last['usage_usec']-first['usage_usec'])/1e6
    return {'cpu_seconds': cpu, 'cpu_seconds_per_1000_correct': cpu*1000/correct if correct else None,
            'cpu_cores_average': cpu/(last['time']-first['time']),
            'throttled_seconds': (last['throttled_usec']-first['throttled_usec'])/1e6,
            'throttled_periods': last['nr_throttled']-first['nr_throttled'],
            'memory_mean_bytes': sum(r['memory_current'] for r in rows)/len(rows),
            'memory_peak_bytes': max(r['memory_peak'] for r in rows),
            'oom_kills': last['memory_oom_kill']-first['memory_oom_kill']}
