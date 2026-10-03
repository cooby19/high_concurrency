"""Independent controlled downstream. Metrics are read/reset outside the measured interval."""
import asyncio
import os
import time
from aiohttp import web
from tools.metrics import Histogram


def create_app(delay=0.020):
    app = web.Application()
    app['samples'] = Histogram()
    app['calls'] = 0

    async def data(request):
        start = time.perf_counter()
        app['calls'] += 1
        await asyncio.sleep(delay)
        app['samples'].add((time.perf_counter() - start) * 1000)
        return web.Response(body=b'x' * 1024, content_type='application/octet-stream')

    async def metrics(request):
        samples = app['samples']
        value = {'calls': app['calls'], 'completed': samples.count, 'wait_p99_ms': samples.percentile(.99)}
        if request.method == 'DELETE':
            app['calls'] = 0
            app['samples'] = Histogram()
        return web.json_response(value)

    async def fault(request):
        app['calls'] += 1
        mode = request.match_info['mode']
        if mode == 'timeout':
            await asyncio.sleep(1.7)
        if mode == 'status':
            return web.Response(status=503)
        if mode == 'redirect':
            raise web.HTTPFound('/data')
        if mode == 'disconnect':
            request.transport.close()
            return web.Response()
        return web.Response(body=b'y' * 1024)

    app.router.add_get('/data', data)
    app.router.add_route('*', '/metrics', metrics)
    app.router.add_get('/fault/{mode}', fault)
    app.router.add_get('/health', lambda r: web.json_response({'status': 'ok'}))
    return app


if __name__ == '__main__':
    web.run_app(create_app(), host='0.0.0.0', port=int(os.getenv('PORT', '8080')), access_log=None, print=None)
