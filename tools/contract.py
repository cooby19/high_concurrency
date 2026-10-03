"""One executable contract suite for all implementations."""
import argparse
import asyncio
import json
from aiohttp import ClientSession, ClientTimeout
from yarl import URL
from tools.common import ROOT, matches


async def check(base, downstream=None, expect_io_error=False):
    cases = json.loads((ROOT / 'contract/fixtures.json').read_text())
    async with ClientSession(timeout=ClientTimeout(total=2), auto_decompress=False) as client:
        client._retry_connection = False
        if downstream:
            async with client.delete(downstream + '/metrics') as response:
                assert response.status == 200
        for case in cases:
            if case['path'] == '/io' and expect_io_error:
                case = dict(case, status=502, expected={'error': 'downstream_error'})
            raw = bytes.fromhex(case['hex']) if 'hex' in case else case.get('raw')
            if 'body' in case:
                raw = json.dumps(case['body'], separators=(',', ':')).encode()
            async with client.request(case.get('method', 'POST'), URL(base + case['path'], encoded=True), data=raw,
                                      headers={'Content-Type': case.get('type', 'application/json')}, allow_redirects=False) as response:
                body = await response.read()
                expected = b'x' * 1024 if case.get('binary') and not expect_io_error else case['expected']
                assert response.status == case['status'], f"{case['name']}: status {response.status}, {body[:200]!r}"
                assert matches(body, expected, response.headers.get('Content-Type', '')), f"{case['name']}: body {body[:200]!r}"
        if downstream:
            async with client.get(downstream + '/metrics') as response:
                metrics = await response.json()
                assert metrics['calls'] == 1, f"Expected exactly one downstream operation: {metrics}"
    return len(cases)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('url');p.add_argument('--downstream');p.add_argument('--expect-io-error', action='store_true')
    args = p.parse_args()
    print(f"Passed {asyncio.run(check(args.url, args.downstream, args.expect_io_error))} contract cases")
