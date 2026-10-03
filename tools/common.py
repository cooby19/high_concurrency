import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PADDING = 'x' * 896


def cpu(seed):
    """Independent logarithmic affine composition oracle, not server's 100k loop."""
    a, c, acc_a, acc_c, n = 1664525, 1013904223, 1, 0, 100000
    while n:
        if n & 1:
            acc_a, acc_c = (a * acc_a) & 0xffffffff, (a * acc_c + c) & 0xffffffff
        a, c = (a*a) & 0xffffffff, (a*c+c) & 0xffffffff
        n >>= 1
    return (acc_a * seed + acc_c) & 0xffffffff


def workload(scenario, index, seed):
    value = (seed + index * 2654435761) & 0xffffffff
    if scenario == 'io':
        return 'GET', '/io', None, b'x' * 1024
    if scenario == 'cpu':
        return 'POST', '/cpu', {'seed': value}, {'result': cpu(value)}
    values = [((value + i * 97) % 2001) - 1000 for i in range(16)]
    data = {'id': value, 'name': f'item_{value}', 'values': values, 'padding': PADDING}
    expected = {'id': value, 'name': data['name'], 'sum': sum(values), 'padding': PADDING}
    return 'POST', '/json', data, expected


def equivalent(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(equivalent(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(equivalent(a, b) for a, b in zip(actual, expected))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and actual == expected
    return type(actual) == type(expected) and actual == expected


def matches(body, expected, content_type):
    if isinstance(expected, bytes):
        return content_type.split(';')[0] == 'application/octet-stream' and body == expected
    try:
        return content_type.split(';')[0] == 'application/json' and equivalent(json.loads(body), expected)
    except (ValueError, UnicodeError):
        return False
