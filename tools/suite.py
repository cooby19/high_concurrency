"""Sequential, randomized six-language matrix with restart/warmup and audit artifacts."""
import argparse
import asyncio
import json
import platform
import random
import time
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout
from tools.common import ROOT
from tools.containers import LANGUAGES, run_args
from tools.contract import check
from tools.load import run
from tools.metrics import passes, repeat_summary
from tools.resources import command, monitor, sample, summary
from tools.search import capacity, InvalidRun

INVENTORY = 'uname -srm; cat /proc/sys/kernel/random/boot_id; cat /proc/cpuinfo | sed -n "1,28p"'


async def health(url):
    async with ClientSession(timeout=ClientTimeout(total=2)) as client:
        for _ in range(60):
            try:
                async with client.get(url+'/health') as response:
                    if response.status == 200:
                        return
            except Exception:
                pass
            await asyncio.sleep(.5)
    raise RuntimeError('Service did not become healthy: '+url)


class Suite:
    def __init__(self, config, output, smoke=False):
        self.config, self.output, self.smoke = config, Path(output), smoke
        self.docker = config['target']['docker']
        self.base = config['target']['url']
        self.downstream = config['downstream']['url']
        self.rng = random.Random(config.get('seed',20261003))
        self.serial = 0
        self.results = []

    async def start(self, language, cpus):
        # Only this dedicated benchmark container name is ever removed.
        old = await command(self.docker+['ps','-aq','--filter','name=^hc-sut$'])
        if old:
            await command(self.docker+['rm','-f','hc-sut'])
        await command(self.docker+run_args(language,cpus,self.config['downstream']['data_url'],network=self.config.get('network')))
        await health(self.base)

    async def downstream_metrics(self, reset=False):
        async with ClientSession(timeout=ClientTimeout(total=5)) as client:
            async with client.request('DELETE' if reset else 'GET', self.downstream+'/metrics') as response:
                response.raise_for_status()
                return await response.json()

    async def point(self, language, cpus, scenario, rate, kind, phases=None):
        self.serial += 1
        folder = self.output/f'{self.serial:04d}-{language}-{cpus}-{scenario}-{kind}'
        await self.start(language,cpus)
        await check(self.base)
        warmup = self.config.get('warmup_seconds', 120) if not self.smoke else 1
        if not self.smoke and warmup < 120:
            raise ValueError('Formal warmup cannot be shorter than 120 seconds')
        warmup_rate = rate/3 if kind == 'burst' else rate
        await run(self.base,scenario,[(warmup,warmup_rate)],str(folder)+'-warmup',seed=self.config.get('seed',20261003),max_lag_ms=self.config.get('max_lag_ms',10))
        await self.downstream_metrics(reset=True)
        rows, stop = [], asyncio.Event()
        rows.append(await sample(self.docker,'hc-sut'))
        task = asyncio.create_task(monitor(self.docker,'hc-sut',rows,stop))
        phases = phases or [(2 if self.smoke else 300,rate)]
        print(f'{language} {cpus}CPU {scenario} {kind} {rate:.3f} RPS',flush=True)
        try:
            result = await run(self.base,scenario,phases,folder,seed=self.config.get('seed',20261003),
                               max_inflight=self.config.get('max_inflight',10000),max_lag_ms=self.config.get('max_lag_ms',10))
        finally:
            stop.set()
            await task
        rows.append(await sample(self.docker,'hc-sut'))
        result['resources'] = summary(rows,result['correct'])
        result['downstream'] = await self.downstream_metrics()
        if scenario == 'io' and (result['downstream']['wait_p99_ms'] is None or result['downstream']['wait_p99_ms'] > self.config.get('downstream_max_p99_ms',25)):
            result['invalid_reasons'].append('downstream_delay_out_of_bounds')
        if result['resources']['oom_kills']:
            result['invalid_reasons'].append('service_oom')
        result.update({'language':language,'cpus':cpus,'kind':kind,'rate':rate,'folder':folder.name})
        result['valid'] = not result['invalid_reasons']
        (folder/'resources.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (folder/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        self.results.append(result)
        (self.output/'runs.json').write_text(json.dumps(self.results,indent=2)+'\n')
        return result

    async def execute(self, languages=LANGUAGES, quotas=(1,4)):
        self.output.mkdir(parents=True,exist_ok=False)
        formal = self.config.get('mode') == 'formal' and not self.smoke
        if formal and (set(languages)!=set(LANGUAGES) or set(quotas)!={1,4}):
            raise ValueError('Formal comparisons require all six languages and both CPU quotas')
        available=int(await command(self.docker+['info','--format','{{.NCPU}}']))
        if max(quotas)>available:
            raise ValueError(f'Target Docker exposes {available} CPUs; requested {max(quotas)}. For local validation only, use --cpus 1.')
        identities = {'load':await command(['sh','-c',INVENTORY])}
        for role in ('target','downstream'):
            identities[role] = await command(self.config[role].get('host_command',[])+['sh','-c',INVENTORY])
        boot_ids = [value.splitlines()[1] for value in identities.values()]
        if formal and len(set(boot_ids)) != 3:
            raise ValueError('Formal ranking requires three separate hosts (different boot IDs)')
        commit = await command(['git','rev-parse','HEAD'])
        dirty = bool(await command(['git','status','--porcelain']))
        if formal and dirty:
            raise ValueError('Commit all source/config changes before a formal run')
        images = {}
        versions = {}
        for language in languages:
            images[language] = json.loads(await command(self.docker+['image','inspect','hc-'+language,'--format','{{json .Id}}']))
            versions[language]=await command(self.docker+['run','--rm','--entrypoint','cat','hc-'+language,'/build-info.txt'])
        manifest = {'commit':commit,'dirty':dirty,'formal_eligible':formal,'local_only':not formal,
                    'config':self.config,'hosts':identities,'images':images,'runtime_versions':versions,'quotas':quotas,'python':platform.python_version(),
                    'generator_aiohttp':__import__('aiohttp').__version__,'started_unix':time.time(),'protocol':'HTTP/1.1, keep-alive, no TLS/compression/retries',
                    'memory_bytes':4*1024**3,'builds':json.loads((ROOT/'contract/builds.json').read_text())}
        (self.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        capacities = []
        for cpus in quotas:
            for scenario in ('json','cpu','io'):
                candidates = {}
                order = list(languages);self.rng.shuffle(order)
                for language in order:
                    if self.smoke:
                        candidates[language]=10.0
                    else:
                        found = await capacity(lambda rate:self.point(language,cpus,scenario,rate,'explore'))
                        candidates[language]=found['candidate']
                        (self.output/f'search-{language}-{cpus}-{scenario}.json').write_text(json.dumps(found,indent=2)+'\n')
                todo = set(languages)
                for attempt in range(20):
                    rounds = {language:[] for language in sorted(todo)}
                    for repeat in range(3):
                        order=sorted(todo);self.rng.shuffle(order)
                        for language in order:
                            r=await self.point(language,cpus,scenario,candidates[language],f'confirm-{attempt}-{repeat}')
                            if not r['valid']:
                                raise InvalidRun(str(r['invalid_reasons']))
                            rounds[language].append(r)
                    failed=set()
                    for language,results in rounds.items():
                        repeated=repeat_summary(results)
                        if repeated['all_pass']:
                            capacities.append({'language':language,'cpus':cpus,'scenario':scenario,'capacity':candidates[language],
                                               'repeats':repeated,'runs':[r['folder'] for r in results]})
                        else:
                            failed.add(language);candidates[language]*=.95
                    todo=failed
                    if not todo:
                        break
                if todo:
                    raise RuntimeError('Could not confirm capacity after 20 reductions')
                # The same absolute arrival rates for every language, in randomized repeated order.
                for rate in ([] if self.smoke else self.config.get('curve_rates',[100,200,400])):
                    for repeat in range(3):
                        order=list(languages);self.rng.shuffle(order)
                        for language in order:
                            await self.point(language,cpus,scenario,rate,f'curve-{repeat}')
                for language in order:
                    cap=candidates[language]
                    await self.point(language,cpus,scenario,.8*cap,'stability',[(2 if self.smoke else 1800,.8*cap)])
                    await self.point(language,cpus,scenario,1.5*cap,'burst',[(2 if self.smoke else 60,1.5*cap),(3 if self.smoke else 300,.5*cap)])
                (self.output/'capacities.json').write_text(json.dumps(capacities,indent=2)+'\n')
        from tools.report import report
        report(self.output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('config');parser.add_argument('--output',required=True);parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--languages',nargs='+',choices=LANGUAGES,default=list(LANGUAGES))
    parser.add_argument('--cpus',nargs='+',type=int,choices=[1,4],default=[1,4])
    args=parser.parse_args()
    asyncio.run(Suite(json.loads(Path(args.config).read_text()),args.output,args.smoke).execute(args.languages,args.cpus))
