"""Pure result calculations; failures are a union, never a sum of categories."""
import math
import statistics


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def latency(values):
    return {f'p{int(p * 100)}_ms': percentile(values, p) for p in (.5, .95, .99)}


def summarize(records, duration, scheduled, rate, max_lag_ms=10):
    sent = [r for r in records if not r.get('dropped', False)]
    good = [r for r in sent if r['ok']]
    bad = [r for r in sent if not r['ok']]
    content_errors = sum(r.get('content_error', False) for r in sent)
    p = latency([r['latency_ms'] for r in sent])
    lag = latency([r['lag_ms'] for r in records])
    reasons = []
    if len(sent) != scheduled:
        reasons.append('unsent_scheduled_requests')
    if any(r['lag_ms'] > max_lag_ms for r in records):
        reasons.append('generator_scheduling_lag')
    failure_rate = len(bad) / len(sent) if sent else 1.0
    return {
        'scheduled': scheduled, 'sent': len(sent), 'dropped': scheduled-len(sent),
        'correct': len(good), 'failed': len(bad), 'content_errors': content_errors,
        'target_rps': rate, 'sent_rps': len(sent)/duration,
        'goodput_rps': len(good)/duration, 'failure_rate': failure_rate,
        'latency': p, 'successful_latency': latency([r['latency_ms'] for r in good]),
        'failed_latency': latency([r['latency_ms'] for r in bad]), 'scheduling_lag': lag,
        'valid': not reasons, 'invalid_reasons': reasons,
        'slo_pass': bool(sent) and p['p99_ms'] <= 200 and failure_rate <= .001 and content_errors == 0,
    }


def passes(result):
    return result['valid'] and result['slo_pass']


def repeat_summary(results):
    """Do not average p99s; retain each repeat and use median/range."""
    out = {'all_pass': len(results) >= 3 and all(passes(r) for r in results)}
    for key, values in {
        'p99_ms': [r['latency']['p99_ms'] for r in results],
        'goodput_rps': [r['goodput_rps'] for r in results],
        'failure_rate': [r['failure_rate'] for r in results],
    }.items():
        values = [v for v in values if v is not None]
        out[key] = {'median': statistics.median(values), 'min': min(values), 'max': max(values)} if values else None
    return out


def recovery_seconds(records, overload_end, window=10, limit=300):
    streak = 0
    for start in range(0, limit, window):
        rows = [r for r in records if overload_end+start <= r['scheduled_s'] < overload_end+start+window]
        result = summarize(rows, window, len(rows), len(rows)/window)
        streak = streak+1 if passes(result) else 0
        if streak == 3:
            return start+window
    return None


class Histogram:
    """0.1 ms upper-bound bins keep long runs bounded without hiding SLO violations."""
    def __init__(self):
        from collections import Counter
        self.bins = Counter()
        self.count = 0

    def add(self, value):
        self.bins[math.ceil(value*10)] += 1
        self.count += 1

    def percentile(self, fraction):
        rank = math.ceil(self.count*fraction)
        seen = 0
        for value, count in sorted(self.bins.items()):
            seen += count
            if seen >= rank:
                return value/10
        return None

    def summary(self):
        return {f'p{int(p*100)}_ms':self.percentile(p) for p in (.5,.95,.99)}


class Accumulator:
    def __init__(self, max_lag_ms=10):
        self.scheduled=self.sent=self.correct=self.failed=self.content_errors=0
        self.lagged=False
        self.max_lag_ms=max_lag_ms
        self.all=Histogram();self.good=Histogram();self.bad=Histogram();self.lag=Histogram()

    def add(self, row):
        self.scheduled+=1
        self.lag.add(row['lag_ms'])
        self.lagged |= row['lag_ms'] > self.max_lag_ms
        if row.get('dropped'):
            return
        self.sent+=1
        self.correct+=row['ok']
        self.failed+=not row['ok']
        self.content_errors+=row['content_error']
        self.all.add(row['latency_ms'])
        (self.good if row['ok'] else self.bad).add(row['latency_ms'])

    def summary(self, duration, rate):
        reasons=[]
        if self.scheduled!=self.sent:reasons.append('unsent_scheduled_requests')
        if self.lagged:reasons.append('generator_scheduling_lag')
        failure=self.failed/self.sent if self.sent else 1
        return {'scheduled':self.scheduled,'sent':self.sent,'dropped':self.scheduled-self.sent,
                'correct':self.correct,'failed':self.failed,'content_errors':self.content_errors,
                'target_rps':rate,'sent_rps':self.sent/duration,'goodput_rps':self.correct/duration,
                'failure_rate':failure,'latency':self.all.summary(),'successful_latency':self.good.summary(),
                'failed_latency':self.bad.summary(),'scheduling_lag':self.lag.summary(),
                'valid':not reasons,'invalid_reasons':reasons,
                'slo_pass':bool(self.sent) and self.all.percentile(.99)<=200 and failure<=.001 and self.content_errors==0}
