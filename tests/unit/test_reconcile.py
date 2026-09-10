import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]


class Accounting(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('reconcile',ROOT/'scripts/reconcile.py')
        self.module=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)

    def test_sender_equations_include_failure_first_success_and_copy(self):
        counts=dict(generated=1,original_attempts=1,retry_attempts=2,not_attempted=0,
                    send_attempts=3,send_pending=0,tx_fail=1,transmitted=2,
                    first_transmitted=1,additional_copies=1,never_transmitted=0)
        self.assertEqual(self.module.sender_errors(counts),[])
        for field in counts:
            bad=dict(counts);bad[field]+=1
            with self.subTest(field=field):self.assertTrue(self.module.sender_errors(bad))
        pending=dict(generated=1,original_attempts=0,retry_attempts=0,not_attempted=1,
                    send_attempts=0,send_pending=0,tx_fail=0,transmitted=0,
                    first_transmitted=0,additional_copies=0,never_transmitted=1)
        self.assertEqual(self.module.sender_errors(pending),[])

    def test_missing_negative_or_noninteger_counters_are_not_zero(self):
        self.assertTrue(self.module.sender_errors({}))
        for value in (-1,1.0,True,None):
            self.assertTrue(self.module.sender_errors({'generated':value}))

    def test_missing_owner_report_is_not_successful_reconciliation(self):
        result=self.module.reconcile(None,None,'lockstep',sensors=[],controls=[])
        self.assertFalse(result['eligible'])
        self.assertIn('missing owner report',result['errors'])
