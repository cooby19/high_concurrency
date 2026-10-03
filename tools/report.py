"""Generate a standalone Markdown report and standard Matplotlib SVG figures."""
import argparse
import itertools
import json
from pathlib import Path


def report(folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder=Path(folder)
    runs=json.loads((folder/'runs.json').read_text())
    manifest=json.loads((folder/'manifest.json').read_text())
    caps=json.loads((folder/'capacities.json').read_text())
    lines=['# High concurrency benchmark', '',
           '**LOCAL VALIDATION ONLY — not a formal ranking.**' if manifest['local_only'] else 'Separate-host measurements; interpret each scenario independently.',
           '',f"Source commit: `{manifest['commit']}`; dirty source: {manifest['dirty']}.",
           'HTTP/1.1, keep-alive, no TLS/compression/retries; 2 s timeout. Percentiles use 0.1 ms upper-bound bins.',
           '', '| Language | CPUs | Scenario | Confirmed RPS | p99 median [min, max] ms | Goodput median [min, max] |',
           '|---|---:|---|---:|---|---|']
    for cap in caps:
        p=cap['repeats']['p99_ms'];g=cap['repeats']['goodput_rps']
        lines.append(f"| {cap['language']} | {cap['cpus']} | {cap['scenario']} | {cap['capacity']:.2f} | {p['median']:.2f} [{p['min']:.2f}, {p['max']:.2f}] | {g['median']:.2f} [{g['min']:.2f}, {g['max']:.2f}] |")
    lines+=['','## Scaling','', '| Language | Scenario | 4-core / 1-core | Efficiency / 4 |','|---|---|---:|---:|']
    for one in (c for c in caps if c['cpus']==1):
        four=next((c for c in caps if c['cpus']==4 and c['language']==one['language'] and c['scenario']==one['scenario']),None)
        if four:
            ratio=four['capacity']/one['capacity']
            lines.append(f"| {one['language']} | {one['scenario']} | {ratio:.3f} | {ratio/4:.3f} |")
    lines+=['','## Differences requiring more evidence','']
    for a,b in itertools.combinations(caps,2):
        if (a['cpus'],a['scenario']) != (b['cpus'],b['scenario']):continue
        ar,br=a['repeats']['goodput_rps'],b['repeats']['goodput_rps']
        if max(ar['min'],br['min'])<=min(ar['max'],br['max']):
            lines.append(f"- {a['scenario']} / {a['cpus']} CPUs: {a['language']} vs {b['language']}: observed throughput ranges overlap; difference unclear.")
    lines+=['','## Curves','']
    for scenario in ('json','cpu','io'):
        for cpus in (1,4):
            subset=[r for r in runs if r['scenario']==scenario and r['cpus']==cpus and r['kind'].startswith(('explore','confirm','curve'))]
            if not subset:continue
            fig,axes=plt.subplots(1,2,figsize=(11,4))
            for language in sorted({r['language'] for r in subset}):
                rows=sorted((r for r in subset if r['language']==language and r['valid']),key=lambda r:r['rate'])
                axes[0].plot([r['rate'] for r in rows],[r['latency']['p99_ms'] for r in rows],'.',label=language)
                axes[1].plot([r['rate'] for r in rows],[100*r['failure_rate'] for r in rows],'.',label=language)
            axes[0].axhline(200,color='gray',linestyle='--');axes[1].axhline(.1,color='gray',linestyle='--')
            axes[0].set_ylabel('p99 latency (ms)');axes[1].set_ylabel('Failure rate (%)')
            for ax in axes:ax.set_xlabel('Absolute arrival rate (RPS)');ax.legend();ax.grid(alpha=.2)
            fig.suptitle(f'{scenario}, {cpus} CPUs — individual runs');fig.tight_layout()
            name=f'curves-{scenario}-{cpus}.svg';fig.savefig(folder/name);plt.close(fig)
            lines.append(f'![{scenario} {cpus} CPUs]({name})')
            fig,axes=plt.subplots(1,2,figsize=(11,4))
            for language in sorted({r['language'] for r in subset}):
                rows=[r for r in subset if r['language']==language and r['valid']]
                axes[0].plot([r['goodput_rps'] for r in rows],[r['latency']['p99_ms'] for r in rows],'.',label=language)
                axes[1].plot([r['goodput_rps'] for r in rows],[100*r['failure_rate'] for r in rows],'.',label=language)
            axes[0].set_ylabel('p99 latency (ms)');axes[1].set_ylabel('Failure rate (%)')
            for ax in axes:ax.set_xlabel('Correct successful throughput (RPS)');ax.legend();ax.grid(alpha=.2)
            fig.suptitle(f'{scenario}, {cpus} CPUs — goodput');fig.tight_layout()
            name=f'goodput-{scenario}-{cpus}.svg';fig.savefig(folder/name);plt.close(fig)
            lines.append(f'![{scenario} {cpus} CPUs goodput]({name})')
    lines+=['','## Stability, recovery, and resource costs','',
            '| Run | Valid | SLO | CPU-s / 1000 correct | Mean / peak MiB | Throttled s | Recovery s |',
            '|---|---|---|---:|---|---:|---|']
    for r in runs:
        resource=r['resources'];cost=resource['cpu_seconds_per_1000_correct']
        lines.append(f"| [{r['folder']}]({r['folder']}/summary.json) | {r['valid']} | {r['slo_pass']} | {format(cost,'.4f') if cost is not None else 'n/a'} | {resource['memory_mean_bytes']/2**20:.2f} / {resource['memory_peak_bytes']/2**20:.2f} | {resource['throttled_seconds']:.3f} | {r.get('recovery_seconds','n/a')} |")
        if r['kind'] in ('stability','burst'):
            rows=[json.loads(line) for line in (folder/r['folder']/'resources.jsonl').read_text().splitlines()]
            fig,axes=plt.subplots(4,1,figsize=(9,9),sharex=True)
            times=[x['time']-rows[0]['time'] for x in rows]
            axes[0].plot(times,[x['memory_current']/2**20 for x in rows]);axes[0].set_ylabel('Memory (MiB)')
            axes[1].plot(times[1:],[(b['usage_usec']-a['usage_usec'])/1e6/(b['time']-a['time']) for a,b in zip(rows,rows[1:])]);axes[1].set_ylabel('CPU cores');axes[1].set_xlabel('Seconds')
            axes[2].plot([w['start_s'] for w in r['windows']],[w['latency']['p99_ms'] for w in r['windows']]);axes[2].set_ylabel('p99 (ms)')
            axes[3].plot([w['start_s'] for w in r['windows']],[w['failure_rate']*100 for w in r['windows']]);axes[3].set_ylabel('Failures (%)');axes[3].set_xlabel('Seconds')
            fig.suptitle(r['folder']);fig.tight_layout();fig.savefig(folder/r['folder']/'resources.svg');plt.close(fig)
    lines+=['','## Resource time series','']
    lines += [f"![{r['folder']}]({r['folder']}/resources.svg)" for r in runs if r['kind'] in ('stability','burst')]
    lines+=['','## Invalid runs','']
    lines += [f"- {r['folder']}: {', '.join(r['invalid_reasons'])}" for r in runs if not r['valid']]
    lines+=['','## Interpretation','',
            'JSON includes parsing, validation and serialization. CPU includes exactly 100,000 uint32 rounds. I/O includes one 20 ms downstream request; these are separate workloads, with no overall winner.',
            'Use CPU usage/throttling with latency to identify CPU pressure; rising memory and delayed recovery suggest queue growth. This is evidence for investigation, not automatic attribution to a language.',
            'Raw requests, warmups, per-second cgroup samples, each repeat, configuration and image IDs are retained. A missing recovery value means no three consecutive complete 10 s passing windows were observed.',
            'Peak memory covers the container lifetime including warmup. Measured CPU includes monitoring overhead; use identical sampling intervals for all implementations.']
    (folder/'report.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');report(p.parse_args().folder)
