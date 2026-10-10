"""Black-box contract tests. Run: python tests/test_cli.py [path/to/binary]."""
import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / 'build' / ('packer.exe' if sys.platform == 'win32' else 'packer')
BINARY = pathlib.Path(os.environ.get('OP_BINARY', str(DEFAULT_BINARY))).resolve()
if __name__ == '__main__' and len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
    BINARY = pathlib.Path(sys.argv.pop(1)).resolve()
REQUEST = {'boxes': [{'id': 'box', 'width': 180, 'length': 180, 'height': 30}],
           'items': [{'id': 'bar', 'width': 220, 'length': 30, 'height': 20}],
           'options': {'max_candidates': 10000, 'time_limit_ms': 10000}}


class CliTests(unittest.TestCase):
    def run_raw(self, payload, *args):
        self.assertTrue(BINARY.is_file(), f'CLI has not been implemented/built: {BINARY}')
        return subprocess.run([str(BINARY), *args], input=payload, capture_output=True, timeout=15)

    def run_json(self, payload):
        result = self.run_raw(json.dumps(payload).encode())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, b'')
        return json.loads(result.stdout)

    def assert_invalid(self, payload):
        result = self.run_raw(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIsInstance(json.loads(result.stdout).get('error'), str)

    def test_diagonal_result_contract(self):
        result = self.run_json(REQUEST)
        self.assertEqual(result['version'], '0.5.1')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['unpacked'], [])
        self.assertEqual(len(result['bins']), 1)
        box = result['bins'][0]
        self.assertEqual((box['id'], box['type_id']), ('bin-1', 'box'))
        self.assertEqual((box['width'], box['length'], box['height']), (180, 180, 30))
        item = box['items'][0]
        self.assertEqual((item['id'], item['instance']), ('bar', 0))
        self.assertGreater(item['angle'] % 90, 0)
        for key in ('x', 'y', 'z', 'width', 'length', 'height', 'angle', 'weight'):
            self.assertIsInstance(item[key], (int, float))
        for key in ('timed_out', 'budget_exhausted'):
            self.assertIsInstance(result['stats'][key], bool)

    def test_empty_and_missing_boxes(self):
        result = self.run_json({'boxes': [], 'items': []})
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['bins'], [])
        self.assertEqual(result['stats']['utilization'], 0)
        request = copy.deepcopy(REQUEST)
        request['boxes'] = []
        request['items'][0]['quantity'] = 3
        result = self.run_json(request)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['unpacked'], [{'id': 'bar', 'instance': i} for i in range(3)])

    def test_candidate_limit_on_last_orthogonal_pose(self):
        # All allowed orthogonal orientations of a cube are equivalent.
        # The last placement still records exhaustion when a prior item exists.
        for rotation, poses in (('none', 1), ('flat', 1), ('any', 1)):
            for quantity in (1, 2):
                request = {
                    'boxes': [dict(id='box', width=quantity, length=1, height=1, quantity=1)],
                    'items': [dict(id='unit', width=1, length=1, height=1,
                                   quantity=quantity, rotation=rotation, diagonal=False)],
                    'options': dict(restarts=1, max_candidates=quantity * poses, time_limit_ms=5000),
                }
                with self.subTest(rotation=rotation, quantity=quantity):
                    result = self.run_json(request)
                    self.assertEqual(result['unpacked'], [])
                    self.assertEqual(result['stats']['candidates'], quantity * poses)
                    self.assertEqual(result['stats']['restarts'], 1)
                    self.assertFalse(result['stats']['timed_out'])
                    self.assertEqual(result['stats']['budget_exhausted'], quantity == 2)
                    placements = result['bins'][0]['items']
                    self.assertEqual([(p['x'], p['y'], p['z'], p['angle']) for p in placements],
                                     [(instance + .5, .5, 0, 0) for instance in range(quantity)])

    def test_quotes_unicode_and_quantity(self):
        request = copy.deepcopy(REQUEST)
        request['boxes'][0].update(id='scatola "è" 🧰', width=400, length=400, height=80)
        request['items'][0].update(id='bar\\\n"é" 🧰', quantity=3, weight=2)
        result = self.run_json(request)
        items = [item for box in result['bins'] for item in box['items']]
        self.assertEqual(sorted(i['instance'] for i in items), [0, 1, 2])
        self.assertTrue(all(i['id'] == request['items'][0]['id'] for i in items))
        self.assertEqual(sum(b['weight'] for b in result['bins']), 6)

    def test_file_input_and_flags(self):
        with tempfile.TemporaryDirectory(prefix='oblique space ') as folder:
            path = pathlib.Path(folder) / 'input file.json'
            path.write_text(json.dumps(REQUEST), encoding='utf-8')
            result = self.run_raw(b'', str(path))
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)['status'], 'complete')
        for flag in ('--help', '--version'):
            result = self.run_raw(b'', flag)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b'paCker', result.stdout)
        self.assertNotEqual(self.run_raw(b'', 'missing-file.json').returncode, 0)
        self.assertNotEqual(self.run_raw(b'', '--unknown').returncode, 0)

    def test_unicode_file_path(self):
        with tempfile.TemporaryDirectory(prefix='oblique-unicode-') as folder:
            directory = pathlib.Path(folder) / '日本語 🧰'
            directory.mkdir()
            path = directory / 'richiesta è 📦.json'
            path.write_text(json.dumps(REQUEST), encoding='utf-8')
            result = self.run_raw(b'', str(path))
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)['status'], 'complete')

    def test_schema_and_ranges(self):
        invalid = [{}, [], None, {'boxes': {}, 'items': []}, {'boxes': [], 'items': [], 'extra': 1}]
        for key, value in [('width', 0), ('width', 1000001), ('weight', -1), ('quantity', 1.1),
                           ('quantity', 0), ('quantity', 257), ('rotation', 'tilt'), ('diagonal', 1),
                           ('id', ''), ('id', 'é' * 32), ('id', 1), ('weight', float('inf')),
                           ('length', None), ('unknown', 1)]:
            r = copy.deepcopy(REQUEST); r['items'][0][key] = value; invalid.append(r)
        for key, value in [('max_weight', -1), ('quantity', -2), ('quantity', 257), ('cost', -1)]:
            r = copy.deepcopy(REQUEST); r['boxes'][0][key] = value; invalid.append(r)
        for key, value in [('angle_step', 0), ('angle_step', 1.5), ('restarts', 65), ('seed', 4294967296),
                           ('max_candidates', 0), ('max_candidates', 100000001), ('time_limit_ms', 60001),
                           ('gap', -1), ('extra', 1)]:
            r = copy.deepcopy(REQUEST); r['options'][key] = value; invalid.append(r)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assert_invalid(payload)

    def test_duplicate_and_limits(self):
        for key in ('boxes', 'items'):
            request = copy.deepcopy(REQUEST); request[key] *= 2; self.assert_invalid(request)
        request = copy.deepcopy(REQUEST)
        request['boxes'] = [dict(request['boxes'][0], id=str(i)) for i in range(65)]
        self.assert_invalid(request)
        request = copy.deepcopy(REQUEST)
        request['items'] = [dict(request['items'][0], id=str(i), quantity=129) for i in range(2)]
        self.assert_invalid(request)
        self.assert_invalid(b'{"boxes":[],"items":[],"items":[]}')
        self.assert_invalid(b'{"boxes":[],"items":[],"options":{"seed":1,"seed":2}}')
        self.assert_invalid(b'{"boxes":[],"items":[]}' + b' ' * (1024 * 1024))

    def test_strict_json(self):
        for payload in [b'', b'{}{}', b'{"boxes":[],"items":[]} garbage', b'{"boxes":[],"items":[],}',
                        b'{"boxes":[],"items":[],"options":{"seed":01}}',
                        b'{"boxes":[],"items":[],"options":{"seed":1.}}',
                        b'{"boxes":[],"items":[],"options":{"seed":1e}}',
                        b'{"boxes":[],"items":[]}\x00',
                        b'{"boxes":[],"items":[],"options":{"seed":1e999}}',
                        b'{"boxes":[],"items":[],"options":{"seed":NaN}}',
                        b'{"boxes":[],"items":[],"x":"\xff"}']:
            with self.subTest(payload=payload): self.assert_invalid(payload)
        for identity in ['a\x00b', '\ud800', '\udc00']:
            request = copy.deepcopy(REQUEST); request['items'][0]['id'] = identity
            self.assert_invalid(request)
        self.assert_invalid(b'[' * 1000 + b']' * 1000)


if __name__ == '__main__':
    unittest.main()
