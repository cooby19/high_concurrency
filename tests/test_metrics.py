import unittest
from tools.common import cpu
from tools.metrics import Accumulator, passes, percentile, recovery_seconds, repeat_summary, summarize
from tools.resources import parse
from tools.search import capacity, InvalidRun


def row(ms=20, ok=True, **extra):
    return {'scheduled_s':0,'latency_ms':ms,'lag_ms':0,'ok':ok,'content_error':False,**extra}


class MetricsTests(unittest.TestCase):
    def test_cpu_oracle_against_direct_reference(self):
        for seed in [0,1,42,2**31,2**32-1]:
            x=seed
            for _ in range(100000):x=(1664525*x+1013904223)%2**32
            self.assertEqual(cpu(seed),x)

    def test_failure_union_and_failed_latency(self):
        r=summarize([row(),row(2000,False,content_error=True,error='timeout',status=500)],1,2,2)
        self.assertEqual(r['failed'],1)
        self.assertEqual(r['failure_rate'],.5)
        self.assertEqual(r['content_errors'],1)
        self.assertEqual(r['latency']['p99_ms'],2000)
        self.assertEqual(r['failed_latency']['p99_ms'],2000)
        self.assertFalse(passes(r))

    def test_unsent_and_lag_make_run_invalid(self):
        r=summarize([row(),{'dropped':True,'lag_ms':11}],1,2,2)
        self.assertEqual(r['dropped'],1)
        self.assertEqual(r['sent_rps'],1)
        self.assertEqual(len(r['invalid_reasons']),2)

    def test_empty_never_passes(self):
        self.assertFalse(passes(summarize([],1,0,0)))
        self.assertIsNone(percentile([],.99))

    def test_three_repeats_and_median_not_average(self):
        values=[summarize([row(ms)],1,1,1) for ms in [1,2,100]]
        self.assertFalse(repeat_summary(values[:2])['all_pass'])
        self.assertTrue(repeat_summary(values)['all_pass'])
        self.assertEqual(repeat_summary(values)['p99_ms']['median'],2)

    def test_recovery_requires_consecutive_windows(self):
        records=[row(300 if 80<=i<90 else 20,scheduled_s=i) for i in range(60,130)]
        self.assertEqual(recovery_seconds(records,60,limit=70),60)
        self.assertIsNone(recovery_seconds([],60,limit=60))

    def test_streaming_histogram_preserves_slo_boundary(self):
        acc=Accumulator()
        acc.add(row(200.001))
        self.assertFalse(passes(acc.summary(1,1)))
        self.assertEqual(acc.summary(1,1)['latency']['p99_ms'],200.1)

    def test_cgroup_includes_throttle_and_oom(self):
        raw='usage_usec 123\nthrottled_usec 4\nnr_throttled 2\nmemory_current\n100\nmemory_peak\n200\nmemory_events\noom_kill 1\n'
        counters=parse(raw)
        self.assertEqual(counters['memory_peak'],200)
        self.assertEqual(counters['memory_oom_kill'],1)
        with self.assertRaises(ValueError):parse('usage_usec 1')


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_bracket_from_above_and_below(self):
        for limit in [25,450]:
            rates=[]
            async def measure(rate):
                rates.append(rate)
                return {'valid':True,'slo_pass':rate<=limit}
            result=await capacity(measure)
            self.assertLessEqual(result['candidate'],limit)
            self.assertGreater(result['upper'],limit)
            self.assertLessEqual((result['upper']-result['candidate'])/result['candidate'],.05)
            self.assertEqual(rates[0],100)

    async def test_invalid_not_treated_as_service_capacity(self):
        async def measure(rate):return {'valid':False,'slo_pass':False,'invalid_reasons':['generator']}
        with self.assertRaises(InvalidRun):await capacity(measure)


class ContractOracleTests(unittest.TestCase):
    def test_response_boolean_is_not_an_integer(self):
        from tools.common import matches
        self.assertFalse(matches(b'{"result":true}',{'result':1},'application/json'))
        self.assertTrue(matches(b'{"result":1.0}',{'result':1},'application/json'))
        self.assertFalse(matches(b'{"result":1,"extra":2}',{'result':1},'application/json'))
