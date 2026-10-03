import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from aiohttp import web
from tools.load import run


class LoadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.active=self.peak=0
        async def handler(request):
            self.active+=1;self.peak=max(self.peak,self.active)
            await asyncio.sleep(.1)
            self.active-=1
            return web.Response(body=b'x'*1024,content_type='application/octet-stream')
        self.app=web.Application();self.app.router.add_get('/io',handler)
        self.runner=web.AppRunner(self.app);await self.runner.setup()
        self.site=web.TCPSite(self.runner,'127.0.0.1',0);await self.site.start()
        self.url='http://127.0.0.1:'+str(self.site._server.sockets[0].getsockname()[1])
        self.temp=tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        await self.runner.cleanup();self.temp.cleanup()

    async def test_open_loop_and_raw_records(self):
        folder=Path(self.temp.name)/'run'
        result=await run(self.url,'io',[(.5,40)],folder,max_lag_ms=100)
        self.assertGreaterEqual(self.peak,3)
        self.assertEqual(result['scheduled'],20)
        self.assertEqual(result['correct'],20)
        rows=[json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),20)
        self.assertAlmostEqual(max(r['scheduled_s'] for r in rows),.475)

    async def test_inflight_limit_is_not_hidden_success(self):
        result=await run(self.url,'io',[(.3,100)],Path(self.temp.name)/'drop',max_inflight=1,max_lag_ms=100)
        self.assertGreater(result['dropped'],0)
        self.assertFalse(result['valid'])
        self.assertLess(result['sent'],result['scheduled'])

    async def test_wrong_response_status_is_counted_as_failure(self):
        result=await run(self.url,'cpu',[(.1,10)],Path(self.temp.name)/'bad',max_lag_ms=100)
        self.assertEqual(result['failed'],1)
        self.assertFalse(result['slo_pass'])

    async def test_timeout_is_included_in_failure_latency(self):
        async def slow(request):
            await asyncio.sleep(2.2)
            return web.Response(body=b'x'*1024,content_type='application/octet-stream')
        app=web.Application();app.router.add_get('/io',slow)
        runner=web.AppRunner(app);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        try:
            result=await run(url,'io',[(.1,10)],Path(self.temp.name)/'timeout',max_lag_ms=100)
            self.assertEqual(result['failed'],1)
            self.assertGreaterEqual(result['failed_latency']['p99_ms'],1900)
            self.assertFalse(result['slo_pass'])
        finally:
            await runner.cleanup()

    async def test_200_with_wrong_content_is_a_content_error(self):
        async def wrong(request):
            return web.Response(body=b'y'*1024,content_type='application/octet-stream')
        app=web.Application();app.router.add_get('/io',wrong)
        runner=web.AppRunner(app);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        try:
            result=await run(url,'io',[(.1,10)],Path(self.temp.name)/'content',max_lag_ms=100)
            self.assertEqual(result['content_errors'],1)
            self.assertEqual(result['failed'],1)
            self.assertEqual(result['correct'],0)
            self.assertFalse(result['slo_pass'])
        finally:
            await runner.cleanup()
