"""Capacity search separates an invalid infrastructure run from an SLO failure."""
from tools.metrics import passes


class InvalidRun(RuntimeError):
    pass


async def capacity(measure, start=100.0, tolerance=.05, attempts=40):
    low, high, rate = None, None, start
    history = []
    for _ in range(attempts):
        result = await measure(rate)
        history.append({'rate': rate, 'result': result})
        if not result['valid']:
            raise InvalidRun(', '.join(result['invalid_reasons']))
        if passes(result):
            low = rate
        else:
            high = rate
        if low is not None and high is not None:
            if (high-low)/low <= tolerance:
                return {'candidate': low, 'upper': high, 'history': history}
            rate = (low+high)/2
        elif low is not None:
            rate *= 2
        else:
            rate /= 2
    raise RuntimeError('No capacity bracket within search limit; increase attempts or inspect infrastructure')
