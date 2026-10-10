"""Official CLI schema 2 contract, independently checked against each request."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get('OP_BINARY', ROOT/'build'/('packer.exe' if sys.platform == 'win32' else 'packer')))
sys.path.insert(0, str(ROOT/'python'))
from packer_adapter import validation_3d as verify  # noqa: E402
REQUEST = dict(boxes=[dict(id='box è', width=100, length=100, height=100, quantity=1)],
               items=[dict(id='rod', width=150, length=8, height=8, rotation='free3d')],
               options=dict(support_mode='geometric', time_limit_ms=10000, max_candidates=4000, restarts=1))


class Schema2Tests(unittest.TestCase):
    def call(self, request):
        raw = request if isinstance(request, bytes) else json.dumps(request).encode()
        p = subprocess.run([str(BINARY)], input=raw, capture_output=True, timeout=15)
        self.assertEqual(p.stderr, b'')
        return p.returncode, json.loads(p.stdout)

    def solve(self, request):
        code, result = self.call(request)
        self.assertEqual(code, 0, result)
        verify.validate_result(request, result)
        return result

    def test_rod_and_effective_options(self):
        result = self.solve(REQUEST)
        self.assertEqual(result['version'], '0.4.1-free3d-dev')
        self.assertEqual(result['schema_version'], 2)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['clearance'], 0)
        self.assertEqual(result['stats']['options'], verify.validate_request(REQUEST)['options'])
        self.assertEqual(result['stats']['seed'], 42)
        self.assertIn(result['stats']['stop_reason'], verify.REASONS if hasattr(verify, 'REASONS') else
                      ['completed', 'search_exhausted', 'time_limit', 'candidate_limit'])
        item = result['bins'][0]['items'][0]
        self.assertFalse(set(item) & {'x', 'y', 'z', 'angle'})
        self.assertEqual(item['width'], 150)

    def test_ordinary_omitted_and_explicit_contact(self):
        request = copy.deepcopy(REQUEST)
        request['items'][0]['rotation'] = 'any'
        request['options'].pop('support_mode')
        a = self.call(request)[1]
        request['options']['support_mode'] = 'contact'
        b = self.call(request)[1]
        a['stats'].pop('elapsed_ms'); b['stats'].pop('elapsed_ms')
        self.assertEqual(a, b)
        self.assertEqual(a['support_mode'], 'contact')
        request['options']['support_mode'] = 'full_base'
        self.assertEqual(self.call(request)[1]['support_mode'], 'full_base')
        self.assertNotIn('schema_version', a)
        self.assertEqual(a['version'], '0.4.1')

    def test_forbidden_options_and_strict_fields(self):
        mutations = [lambda r: r['options'].update(support_mode='full_base'),
                     lambda r: r['options'].update(gap=1),
                     lambda r: r['options'].update(support_mode=None),
                     lambda r: r['options'].update(support_mode='other'),
                     lambda r: r['items'][0].update(diagonal=False),
                     lambda r: r['items'][0].update(orientation=[0,0,0,1]),
                     lambda r: r['items'].append(copy.deepcopy(r['items'][0])),
                     lambda r: r['boxes'].append(copy.deepcopy(r['boxes'][0])),
                     lambda r: r['items'][0].update(quantity=257),
                     lambda r: r['boxes'][0].update(quantity=-2),
                     lambda r: r['options'].update(clearance=float('inf')),
                     lambda r: r['items'][0].update(weight=-1)]
        for mutate in mutations:
            r = copy.deepcopy(REQUEST); mutate(r)
            with self.subTest(request=r):
                code, result = self.call(r)
                self.assertNotEqual(code, 0, result)
                self.assertIsInstance(result.get('error'), str)
        for clearance in (0, 1):
            r = dict(boxes=[], items=[], options=dict(support_mode='full_base', clearance=clearance))
            self.assertNotEqual(self.call(r)[0], 0)
        for raw in (b'{"boxes":[],"items":[],"options":{"support_mode":"geometric","seed":1,"seed":2}}',
                    b'{"boxes":[],"items":[],"options":{"support_mode":"geometric","clearance":1e999}}',
                    b'{"boxes":[],"items":[],"options":{"support_mode":"geometric","\xff":0}}',
                    b'['*18 + b']'*18, b' '*1048577):
            self.assertNotEqual(self.call(raw)[0], 0)

    def test_zero_boxes_stock_weight_and_margin(self):
        for boxes, items in (([], []), ([], REQUEST['items'])):
            self.solve(dict(boxes=boxes, items=items, options=dict(support_mode='geometric')))
        for stock, weight, clearance in ((0, 0, 0), (1, 2, 0), (1, 0, 0.1), (1, 0, 0)):
            r = dict(boxes=[dict(id='b', width=1, length=1, height=1, quantity=stock, max_weight=1)],
                     items=[dict(id='i', width=1, length=1, height=1, weight=weight, quantity=2, rotation='none')],
                     options=dict(support_mode='geometric', clearance=clearance, gap=0, max_candidates=1000))
            result = self.solve(r)
            self.assertEqual(len(result['bins']), int(stock == 1 and weight == 0 and clearance == 0))
            self.assertEqual(len(result['unpacked']), 2-len(result['bins']))

    def test_pose_double_round_trip_matches_direct_api(self):
        spec = importlib.util.spec_from_file_location('schema2_adapter', ROOT/'tests/free3d_capi.py')
        adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
        library = ROOT/'build'/('packer3d.dll' if sys.platform == 'win32' else 'libpacker3d.so')
        a = adapter.Adapter(library).pack(REQUEST)
        b = self.solve(REQUEST)
        # Separate executable/DLL compilations can round intermediate long-double
        # work differently. Same-process bit-exact serialization is tested in C.
        ai, bi = a['bins'][0]['items'][0], b['bins'][0]['items'][0]
        for field in ('center', 'orientation'):
            for x, y in zip(ai[field], bi[field]): self.assertAlmostEqual(x, y, delta=1e-12)
        r = dict(boxes=[dict(id='b', width=1.2345678901234567, length=2, height=3)],
                 items=[dict(id='i', width=0.12345678901234566, length=0.23456789012345678, height=0.3456789012345679,
                             rotation='none')], options=dict(support_mode='geometric', max_candidates=50))
        result = self.solve(r)
        self.assertEqual(result['bins'][0]['width'], r['boxes'][0]['width'])
        self.assertEqual(result['bins'][0]['items'][0]['width'], r['items'][0]['width'])

    def test_seeded_mixed_constraints_and_scales(self):
        rng = random.Random(617)
        for scale in (0.001, 1, 1000):
            r = dict(boxes=[dict(id='b', width=100*scale, length=100*scale, height=100*scale, quantity=2)],
                     items=[dict(id=str(i), width=rng.randint(5,45)*scale, length=8*scale, height=9*scale,
                                 rotation=mode, diagonal=mode=='free3d', quantity=2)
                            for i, mode in enumerate(('none','flat','any','free3d'))],
                     options=dict(support_mode='geometric', clearance=0.01*scale, max_candidates=500, restarts=1))
            with self.subTest(scale=scale): self.solve(r)

    def test_published_schemas(self):
        request_schema = json.loads((ROOT/'schemas/request-v2.json').read_text())
        result_schema = json.loads((ROOT/'schemas/result-v2.json').read_text())
        self.assertEqual(request_schema['properties']['options']['$ref'], '#/$defs/options')
        self.assertEqual(result_schema['properties']['schema_version']['const'], 2)
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return  # JSON Schema tooling is optional, never a runtime dependency.
        for schema in (request_schema, result_schema): Draft202012Validator.check_schema(schema)
        Draft202012Validator(request_schema).validate(REQUEST)
        result = self.solve(REQUEST)
        Draft202012Validator(result_schema).validate(result)
        bad = copy.deepcopy(result); bad['bins'][0]['items'][0]['angle'] = 0
        self.assertTrue(list(Draft202012Validator(result_schema).iter_errors(bad)))

    def test_input_limits_and_utf8_identity_bytes(self):
        r = dict(boxes=[], items=[dict(id='é'*31, width=0.0001, length=1e6, height=1, quantity=256)],
                 options=dict(support_mode='geometric', seed=4294967295))
        result = self.solve(r)
        self.assertEqual(len(result['unpacked']), 256)
        self.assertEqual(result['stats']['seed'], 4294967295)
        for field, value in (('id', 'é'*32), ('width', 0.000099999), ('length', 1000000.001)):
            invalid=copy.deepcopy(r); invalid['items'][0][field]=value
            self.assertNotEqual(self.call(invalid)[0], 0)
        invalid=copy.deepcopy(r); invalid['items'].append(dict(id='extra', width=1,length=1,height=1))
        self.assertNotEqual(self.call(invalid)[0], 0)
        invalid=copy.deepcopy(r)
        invalid['boxes']=[dict(id=str(i),width=1,length=1,height=1) for i in range(65)]
        self.assertNotEqual(self.call(invalid)[0], 0)

    def test_relative_weight_boundaries_match_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        schema = json.loads((ROOT/'schemas/result-v2.json').read_text())
        self.assertEqual(schema['$defs']['placement']['properties']['weight']['maximum'], 1e12)
        self.assertEqual(schema['$defs']['bin']['properties']['max_weight']['maximum'], 1e12)
        self.assertEqual(schema['$defs']['bin']['properties']['weight']['maximum'], 256e12)
        for capacity, weight, quantity in ((100000000000, 100000000000.00002, 1),
                                           (1e12, 500000000000.00006, 2)):
            r = dict(boxes=[dict(id='b', width=quantity, length=1, height=1, max_weight=capacity, quantity=1)],
                     items=[dict(id='i', width=1, length=1, height=1, weight=weight, quantity=quantity, rotation='none')],
                     options=dict(support_mode='geometric'))
            with self.subTest(capacity=capacity):
                result = self.solve(r)  # Includes authoritative independent Decimal60 validation.
                self.assertEqual(result['status'], 'complete')
                self.assertGreater(result['bins'][0]['weight'], capacity)
                if Draft202012Validator: Draft202012Validator(schema).validate(result)
                invalid_request = copy.deepcopy(r)
                invalid_request['items'][0]['weight'] += 0.01
                self.assertEqual(self.solve(invalid_request)['status'], 'partial')
                invalid_result = copy.deepcopy(result)
                for item in invalid_result['bins'][0]['items']: item['weight'] += 0.01
                invalid_result['bins'][0]['weight'] = sum(item['weight'] for item in invalid_result['bins'][0]['items'])
                with self.assertRaises(ValueError): verify.validate_result(invalid_request, invalid_result)


if __name__ == '__main__': unittest.main()
