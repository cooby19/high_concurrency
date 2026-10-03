import asyncio
import json
import math
import multiprocessing
import os
import re
from aiohttp import web, ClientSession, ClientTimeout, TCPConnector


def integer(v, lo, hi):
    return type(v) in (int, float) and math.isfinite(v) and v == int(v) and lo <= v <= hi


def error(code, message):
    return web.json_response({'error': message}, status=code)


async def handler(request):
    path, _, query = request.raw_path.partition('?')
    methods = {'/health': 'GET', '/io': 'GET', '/json': 'POST', '/cpu': 'POST'}
    if path not in methods:
        return error(404, 'not_found')
    if request.method != methods[path]:
        return error(405, 'method_not_allowed')
    if query:
        return error(400, 'invalid_request')
    if path == '/health':
        return web.json_response({'status': 'ok'})
    if path == '/io':
        try:
            async with request.app['client'].get(os.environ['DOWNSTREAM_URL'], allow_redirects=False) as response:
                data = await response.content.read(1025)
                # read() may return a partial chunk; readexactly covers streamed responses.
                if len(data) < 1024:
                    data += await response.content.readexactly(1024 - len(data))
                extra = await response.content.read(1)
                if response.status != 200 or data != b'x' * 1024 or extra:
                    raise ValueError()
                return web.Response(body=data, content_type='application/octet-stream')
        except (Exception,):
            return error(502, 'downstream_error')
    if request.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
        return error(415, 'unsupported_media_type')
    try:
        raw = bytearray()
        async for chunk in request.content.iter_chunked(4096):
            raw.extend(chunk)
            if len(raw) > 4096:
                return error(413, 'payload_too_large')
        data = json.loads(raw.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(data, dict):
            raise ValueError()
        if path == '/cpu':
            if set(data) != {'seed'} or not integer(data['seed'], 0, 4294967295):
                raise ValueError()
            x = int(data['seed'])
            for _ in range(100000):
                x = (1664525 * x + 1013904223) & 0xffffffff
            return web.json_response({'result': x})
        if set(data) != {'id', 'name', 'values', 'padding'} or not integer(data['id'], 0, 4294967295) or not isinstance(data['name'], str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', data['name']) or not isinstance(data['values'], list) or len(data['values']) != 16 or not all(integer(v, -1000, 1000) for v in data['values']) or data['padding'] != 'x' * 896:
            raise ValueError()
        return web.json_response({'id': data['id'], 'name': data['name'], 'sum': sum(data['values']), 'padding': data['padding']})
    except (ValueError, TypeError, OverflowError):
        return error(400, 'invalid_request')


async def lifecycle(app):
    async with ClientSession(connector=TCPConnector(limit=0), timeout=ClientTimeout(total=1.5), auto_decompress=False, headers={'Accept-Encoding': 'identity'}) as client:
        client._retry_connection = False  # aiohttp 3.13.5: disable implicit GET replay
        app['client'] = client
        yield


def run():
    app = web.Application()
    app.cleanup_ctx.append(lifecycle)
    app.router.add_route('*', '/{path:.*}', handler)
    web.run_app(app, host='0.0.0.0', port=int(os.getenv('PORT', '8080')), reuse_port=True, access_log=None, print=None)


if __name__ == '__main__':
    workers = int(os.getenv('WORKERS', '1'))
    if workers == 1:
        run()
    else:
        processes = [multiprocessing.Process(target=run) for _ in range(workers)]
        for process in processes:
            process.start()
        try:
            while all(process.is_alive() for process in processes):
                processes[0].join(timeout=1)
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.join()
