"""Opt-in Docker integration: HC_INTEGRATION=1 python -m unittest discover -s tests -v."""
import asyncio
import os
import subprocess
import unittest
from aiohttp import ClientSession, ClientTimeout
from tools.containers import DOCKER, LANGUAGES, run_args
from tools.contract import check
from tools.resources import command, sample
from tools.suite import health


def docker(*args, check=True):
    return subprocess.run(DOCKER+list(args),check=check,capture_output=True,text=True)


@unittest.skipUnless(os.getenv('HC_INTEGRATION')=='1','set HC_INTEGRATION=1 after building images')
class ServicesTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.available_cpus=int(docker('info','--format','{{.NCPU}}').stdout.strip())
        if docker('network','inspect','hc-test',check=False).returncode:
            docker('network','create','hc-test')
        docker('rm','-f','hc-test-downstream',check=False)
        docker('run','-d','--name','hc-test-downstream','--network','hc-test','-p','18081:8080','hc-downstream')

    @classmethod
    def tearDownClass(cls):
        docker('rm','-f','hc-test-sut','hc-test-downstream',check=False)
        docker('network','rm','hc-test',check=False)

    async def start(self, language, cpus, path='data', workers=None):
        await command(DOCKER+['rm','-f','hc-test-sut'])
        args=run_args(language,cpus,'http://hc-test-downstream:8080/'+path,name='hc-test-sut',port=18080,network='hc-test')
        if workers is not None:
            for i,arg in enumerate(args):
                for key in ('WORKERS','GOMAXPROCS','DOTNET_PROCESSOR_COUNT','TOKIO_WORKER_THREADS'):
                    if arg.startswith(key+'='):
                        args[i]=key+'='+str(workers)
                if arg.startswith('JAVA_TOOL_OPTIONS='):
                    args[i]=arg.replace(f'ActiveProcessorCount={cpus}',f'ActiveProcessorCount={workers}')
        await command(DOCKER+args)
        await health('http://127.0.0.1:18080')

    async def test_common_contract_all_languages_and_quotas(self):
        await health('http://127.0.0.1:18081')
        for language in LANGUAGES:
            for cpus in (1,4):
                with self.subTest(language=language,cpus=cpus):
                    if cpus > self.available_cpus:
                        self.skipTest(f'Docker exposes only {self.available_cpus} CPUs; need {cpus}')
                    await self.start(language,cpus)
                    count=await check('http://127.0.0.1:18080','http://127.0.0.1:18081')
                    self.assertGreater(count,50)
                    counters=await sample(DOCKER,'hc-test-sut')
                    self.assertGreater(counters['memory_current'],0)
                    limits=await command(DOCKER+['inspect','hc-test-sut','--format','{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}'])
                    self.assertEqual(limits,f'{cpus*1000000000} 4294967296 4294967296')
                    async with ClientSession(timeout=ClientTimeout(total=2)) as client:
                        client._retry_connection=False
                        async with client.delete('http://127.0.0.1:18081/metrics') as response:await response.read()
                        async def io():
                            async with client.get('http://127.0.0.1:18080/io') as response:
                                self.assertEqual(response.status,200)
                                self.assertEqual(await response.read(),b'x'*1024)
                        await asyncio.gather(*(io() for _ in range(32)))
                        async with client.get('http://127.0.0.1:18081/metrics') as response:
                            self.assertEqual((await response.json())['calls'],32)

    async def test_downstream_faults_never_redirect_or_retry(self):
        await health('http://127.0.0.1:18081')
        for language in LANGUAGES:
            for mode in ('status','redirect','timeout','body','disconnect'):
                with self.subTest(language=language,mode=mode):
                    await self.start(language,1,'fault/'+mode)
                    await check('http://127.0.0.1:18080','http://127.0.0.1:18081',expect_io_error=True)

    async def test_four_workers_functionally_under_one_cpu_quota(self):
        # Exercises multi-process/runtime paths even on small CI hosts; never a 4-core performance test.
        from tools.common import cpu
        await health('http://127.0.0.1:18081')
        for language in LANGUAGES:
            with self.subTest(language=language):
                await self.start(language,1,workers=4)
                await check('http://127.0.0.1:18080','http://127.0.0.1:18081')
                async with ClientSession(timeout=ClientTimeout(total=2)) as client:
                    async def request(seed):
                        async with client.post('http://127.0.0.1:18080/cpu',json={'seed':seed}) as response:
                            self.assertEqual(response.status,200)
                            self.assertEqual(await response.json(),{'result':cpu(seed)})
                    await asyncio.gather(*(request(seed) for seed in range(16)))
