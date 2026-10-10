"""Valid floor tilings missed by the original orthogonal search portfolio."""
import json
import copy
import os
from pathlib import Path
import subprocess
import sys
import unittest

from validate_result import validate

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get('OP_BINARY', str(ROOT / 'build' / ('packer.exe' if sys.platform == 'win32' else 'packer'))))


class OrdinaryQualityTests(unittest.TestCase):
    def test_unsupported_elevated_grid_does_not_exhaust_complete_order(self):
        # Disclosed development case with an independently validated packing.
        witness = json.loads((ROOT / 'tests/quality_budget_witness.json').read_text())
        request = witness['request']
        self.assertEqual(validate(request, witness['known_fit']), [])
        process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(validate(request, result), [])
        self.assertEqual(result['unpacked'], [])
        self.assertLessEqual(result['stats']['candidates'], request['options']['max_candidates'])
        self.assertFalse(result['stats']['timed_out'])

    def test_support_row_edges_leave_room_for_complete_continuation(self):
        witness = json.loads((ROOT / 'tests/quality_budget_witness.json').read_text())
        request = copy.deepcopy(witness['request'])
        request['options']['max_candidates'] = 5000
        self.assertEqual(validate(request, witness['known_fit']), [])
        process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(validate(request, result), [])
        self.assertEqual(result['unpacked'], [])
        self.assertLessEqual(result['stats']['candidates'], 5000)
        self.assertFalse(result['stats']['timed_out'])

    def test_completed_reinsertion_leaves_budget_for_later_cheaper_box(self):
        witness = json.loads((ROOT / 'tests/quality_support_witness.json').read_text())
        request = copy.deepcopy(witness['request'])
        medium_index = next(i for i, box in enumerate(request['boxes']) if box['id'] == 'medium')
        cheaper = dict(request['boxes'][medium_index], id='cheaper-medium', cost=.99)
        request['boxes'].insert(medium_index + 1, cheaper)
        request['options']['max_candidates'] = 1000000
        process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(validate(request, result), [])
        self.assertEqual(result['unpacked'], [])
        self.assertFalse(result['stats']['budget_exhausted'])
        self.assertEqual([b['type_id'] for b in result['bins']], ['cheaper-medium'])
        self.assertEqual(result['stats']['total_cost'], .99)

    def test_removing_two_placements_allows_supported_smaller_box(self):
        witness = json.loads((ROOT / 'tests/quality_support_witness.json').read_text())
        request = witness['request']
        self.assertEqual(validate(request, witness['known_fit']), [])
        process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(validate(request, result), [])
        self.assertEqual(result['unpacked'], [])
        self.assertEqual([b['type_id'] for b in result['bins']], ['medium'])

    def test_refinement_respects_stock_weight_and_gap(self):
        witness = json.loads((ROOT / 'tests/quality_witness.json').read_text())
        for restriction in ('stock', 'weight', 'gap'):
            request = copy.deepcopy(witness['request'])
            if restriction == 'stock':
                request['boxes'][0]['quantity'] = 0
            elif restriction == 'weight':
                request['boxes'][0]['max_weight'] = 8
            else:
                request['options']['gap'] = .01
            with self.subTest(restriction=restriction):
                process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                         capture_output=True, text=True, timeout=15)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(validate(request, result), [])
                self.assertEqual(result['unpacked'], [])
                self.assertEqual([b['type_id'] for b in result['bins']], ['large'])

    def test_small_shared_budgets_keep_valid_incumbents(self):
        witness = json.loads((ROOT / 'tests/quality_witness.json').read_text())
        for cap in (1, 4, 20, 100, 300):
            request = copy.deepcopy(witness['request'])
            request['options']['max_candidates'] = cap
            with self.subTest(cap=cap):
                process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                         capture_output=True, text=True, timeout=15)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(validate(request, result), [])
                self.assertGreater(sum(len(b['items']) for b in result['bins']), 0)
                self.assertLessEqual(result['stats']['candidates'], cap)
                self.assertTrue(result['stats']['budget_exhausted'])

    def test_completed_box_trials_share_search_work(self):
        request = dict(boxes=[dict(id='small', width=1, length=1, height=1),
                              dict(id='large', width=2, length=1, height=1)],
                       items=[dict(id='cube', width=1, length=1, height=1,
                                   rotation='any', diagonal=False)],
                       options=dict(restarts=8, max_candidates=1000,
                                    time_limit_ms=1000, seed=42))
        process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(validate(request, result), [])
        self.assertEqual([b['type_id'] for b in result['bins']], ['small'])
        self.assertLessEqual(result['stats']['candidates'], 16)
        self.assertFalse(result['stats']['budget_exhausted'])

    def test_beam_omits_boxes_that_cannot_improve_complete_incumbent(self):
        request = dict(boxes=[dict(id='small', width=1, length=1, height=1),
                              dict(id='large', width=2, length=1, height=1)],
                       items=[dict(id='cube', width=1, length=1, height=1,
                                   rotation='any', diagonal=False)],
                       options=dict(restarts=64, max_candidates=1000,
                                    time_limit_ms=1000, seed=42))
        process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual([b['type_id'] for b in result['bins']], ['small'])
        self.assertLessEqual(result['stats']['candidates'], 128)

    def test_bounded_refinement_finds_exact_floor_tiling(self):
        witness = json.loads((ROOT / 'tests/quality_witness.json').read_text())
        request = witness['request']
        placements = [dict(id=item['id'], instance=0, x=x+w/2, y=y+l/2,
                           z=0, width=w, length=l, height=1, angle=0, weight=1)
                      for item, (x, y, w, l) in zip(request['items'], witness['rectangles'])]
        box = dict(request['boxes'][0], id='bin-1', type_id='small',
                   max_weight=1e12, weight=9, items=placements)
        known_fit = dict(status='complete', bins=[box], unpacked=[],
                         stats=dict(box_count=1, total_cost=1, utilization=1))
        self.assertEqual(validate(request, known_fit), [])
        process = subprocess.run([str(BINARY)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(validate(request, result), [])
        self.assertEqual(result['unpacked'], [])
        self.assertEqual([b['type_id'] for b in result['bins']], ['small'])
        self.assertLessEqual(result['stats']['candidates'], 100000)


if __name__ == '__main__':
    unittest.main()
