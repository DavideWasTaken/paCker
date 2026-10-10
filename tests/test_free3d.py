"""Engine behavior checked independently through the development C API adapter."""
import copy
import _ctypes
import ctypes as C
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('free3d_capi_adapter', ROOT / 'tests/free3d_capi.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def item(name='a', sides=(2, 3, 4), rotation='free3d', **extra):
    return dict(id=name, width=sides[0], length=sides[1], height=sides[2], rotation=rotation, **extra)


def box(name='box', sides=(10, 10, 10), **extra):
    return dict(id=name, width=sides[0], length=sides[1], height=sides[2], **extra)


def request(items=None, boxes=None, **options):
    return dict(items=[item()] if items is None else items, boxes=[box()] if boxes is None else boxes, options=dict(support_mode='geometric', time_limit_ms=1000, max_candidates=20000, restarts=2, **options))


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='free3d-search-')
        cls.dll = Path(cls.temp.name) / ('packer3d.dll' if sys.platform == 'win32' else 'packer3d.so')
        zig = ROOT / '.tools/zig-x86_64-windows-0.15.2/zig.exe'
        zig = zig if zig.exists() else Path(shutil.which('zig') or zig)
        compiler = [str(zig), 'cc'] if sys.platform == 'win32' else [shutil.which('cc') or 'cc']
        sources = [ROOT / 'src/geometry3d.c'] + [p for p in (ROOT / 'src/packer3d.c', ROOT / 'src/search3d.c', ROOT / 'src/oblique.c') if p.exists()]
        command = compiler + ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-I' + str(ROOT / 'include'), *map(str, sources), '-o', str(cls.dll)]
        if sys.platform != 'win32':
            command += ['-fPIC', '-lm']
        built = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)
        cls.adapter = api.Adapter(cls.dll)

    @classmethod
    def tearDownClass(cls):
        if sys.platform == 'win32':
            _ctypes.FreeLibrary(cls.adapter.lib._handle)
        del cls.adapter
        cls.temp.cleanup()

    def pack(self, req):
        result = self.adapter.pack(req)
        api.verify.validate_result(req, result)
        # These exact JSON doubles, including canonical quaternion, are verified.
        api.verify.validate_result(req, json.loads(json.dumps(result, allow_nan=False)))
        return result

    def test_empty_and_no_boxes(self):
        self.assertEqual(self.pack(request([]))['status'], 'complete')
        r = self.pack(request(boxes=[]))
        self.assertEqual((r['status'], len(r['unpacked'])), ('partial', 1))

    def test_orthogonal_multiple_items(self):
        r = self.pack(request([item(sides=(5, 5, 5), rotation='none', quantity=8)]))
        self.assertEqual((r['status'], len(r['bins'])), ('complete', 1))

    def test_rod_requires_tilt(self):
        r = request([item(sides=(150, 8, 8))], [box(sides=(100, 100, 100))])
        self.assertEqual(self.pack(r)['status'], 'complete')
        r['items'][0]['rotation'] = 'any'
        self.assertEqual(self.pack(r)['status'], 'partial')

    def test_parallel_tilted_rods(self):
        r = self.pack(request([item(sides=(150, 5, 5), quantity=2)], [box(sides=(100, 100, 100))]))
        self.assertEqual((r['status'], len(r['bins'])), ('complete', 1))

    def test_continuous_yaw_between_initial_samples(self):
        angle = math.radians(31.234)
        sides = (100 * math.cos(angle) + 2 * math.sin(angle) + .03,
                 100 * math.sin(angle) + 2 * math.cos(angle) + .03, 1)
        r = request([item(sides=(100, 2, 1), rotation='flat')], [box(sides=sides)])
        result = self.pack(r)
        self.assertEqual(result['status'], 'complete')
        q = result['bins'][0]['items'][0]['orientation']
        yaw = math.degrees(2 * math.atan2(q[2], q[3]))
        self.assertGreater(abs(yaw / 15 - round(yaw / 15)), .01)

    def test_rectangular_3d_and_contact_offsets(self):
        from geometry3d_oracle import inside, intersects
        # Construct a known fit independently: long axis along (90,70,60),
        # transverse axis (70,-90,0), two centers separated along that axis.
        norm = math.sqrt(90**2 + 70**2 + 60**2)
        n = [v/norm for v in (90, 70, 60)]
        norm2 = math.hypot(70, 90)
        y = [70/norm2, -90/norm2, 0]
        z = [n[1]*y[2]-n[2]*y[1], n[2]*y[0]-n[0]*y[2], n[0]*y[1]-n[1]*y[0]]
        m = [[n[k], y[k], z[k]] for k in range(3)]
        scale = 2*math.sqrt(1 + m[0][0] + m[1][1] + m[2][2])
        q = [(m[2][1]-m[1][2])/scale, (m[0][2]-m[2][0])/scale, (m[1][0]-m[0][1])/scale, scale/4]
        witness = [dict(width=118, length=3, height=5, orientation=q,
                        center=[b/2 + sign*y[k]*3.11/2 for k, b in enumerate((90,71,61))]) for sign in (-1, 1)]
        self.assertTrue(all(inside(p, (90,71,61), .1) for p in witness))
        self.assertFalse(intersects(*witness, .1))
        r = request([item(sides=(118, 3, 5), quantity=2)], [box(sides=(90, 71, 61))], clearance=.1)
        self.assertEqual(self.pack(r)['status'], 'complete')
        r['items'][0]['rotation'] = 'any'
        self.assertEqual(self.pack(r)['status'], 'partial')

    def test_invalid_options_identity_and_numbers(self):
        _, good = api.request_to_c(request())
        mutations = [lambda r: setattr(r.options, 'angle_step', 1.5),
                     lambda r: setattr(r.options, 'time_limit_ms', math.nan),
                     lambda r: setattr(r.options, 'clearance', math.inf),
                     lambda r: setattr(r.options, 'max_candidates', 0),
                     lambda r: setattr(r.options, 'restarts', 65),
                     lambda r: setattr(r.items[0], 'width', 0),
                     lambda r: setattr(r.items[0], 'weight', -1),
                     lambda r: setattr(r.items[0], 'rotation', 4),
                     lambda r: setattr(r.items[0], 'diagonal', 2),
                     lambda r: setattr(r.items[0], 'id', b''),
                     lambda r: setattr(r.items[0], 'id', b'a' * 64),
                     lambda r: setattr(r.boxes[0], 'quantity', -2),
                     lambda r: setattr(r.boxes[0], 'cost', math.inf)]
        for mutate in mutations:
            bad = copy.deepcopy(good); mutate(bad)
            out = api.Result()
            C.memset(C.byref(out), 0x55, C.sizeof(out))
            self.assertEqual(self.adapter.lib.op3_pack(C.byref(bad), C.byref(out), None, 0), 1)
            self.assertEqual(bytes(out), bytes(C.sizeof(out)))
        for kind in ('items', 'boxes'):
            bad = copy.deepcopy(good)
            getattr(bad, kind)[1] = getattr(bad, kind)[0]
            setattr(bad, 'item_count' if kind == 'items' else 'box_count', 2)
            self.assertEqual(self.adapter.lib.op3_pack(C.byref(bad), C.byref(api.Result()), None, 0), 1)

    def test_permissions_stay_per_item(self):
        for rotation, diagonal in [('none', True), ('flat', True), ('any', True), ('any', False)]:
            r = self.pack(request([item(sides=(150, 8, 8), rotation=rotation, diagonal=diagonal)], [box(sides=(100, 100, 100))]))
            self.assertEqual(r['status'], 'partial')
        r = self.pack(request([item(rotation='none'), item('flat', rotation='flat'), item('any', rotation='any', diagonal=False), item('tilt')]))
        self.assertEqual(r['status'], 'complete')

    def test_clearance_weight_stock_and_objective(self):
        r = self.pack(request([item(sides=(3, 3, 3), weight=1, quantity=3)], [box('cheap', max_weight=1, cost=1, quantity=2), box('large', max_weight=3, cost=5)], clearance=1))
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(r['stats']['total_cost'], 5)
        r = self.pack(request([item(weight=1e-20)], [box(max_weight=0)]))
        self.assertEqual(r['status'], 'partial')
        r = self.pack(request([item(quantity=2, weight=1)], [box(max_weight=1, quantity=1)]))
        self.assertEqual(len(r['unpacked']), 1)
        r = self.pack(request([item()], [box(quantity=0)]))
        self.assertEqual(len(r['unpacked']), 1)

    def test_candidate_stop_preserves_valid_partial_and_is_replayable(self):
        r = request([item(sides=(5, 5, 5), quantity=8)])
        r['options'].update(max_candidates=3, time_limit_ms=60000)
        a, b = self.pack(r), self.pack(r)
        self.assertEqual(a['bins'], b['bins'])
        self.assertEqual(a['unpacked'], b['unpacked'])
        self.assertEqual(a['stats']['candidates'], 3)
        self.assertTrue(a['stats']['budget_exhausted'])
        self.assertEqual(a['stats']['stop_reason'], 'candidate_limit')

    def test_xy_initialization_fraction(self):
        r = request([item(sides=(160, 14, 14), quantity=10)], [box(sides=(100, 100, 100))])
        r['options'].update(time_limit_ms=50, max_candidates=100)
        out = self.pack(r)
        self.assertLessEqual(out['stats']['xy_candidates'], 25)
        # Cooperative check reports actual phase duration without hiding overrun.
        self.assertLess(out['stats']['xy_elapsed_ms'], 32.5)

    def test_time_stop_keeps_incumbent(self):
        r = request([item(sides=(5, 5, 5), quantity=256)])
        r['options'].update(time_limit_ms=1, max_candidates=100000000, restarts=64)
        out = self.pack(r)
        self.assertTrue(out['stats']['timed_out'])
        self.assertGreaterEqual(out['stats']['elapsed_ms'], 1)

    def test_scale_limits(self):
        for scale in (1e-4, 1, 1e6):
            r = self.pack(request([item(sides=(scale, scale, scale), rotation='none')], [box(sides=(scale, scale, scale))]))
            self.assertEqual(r['status'], 'complete')

    def test_invalid_c_api_zeroes_result(self):
        _, good = api.request_to_c(request())
        for field, value in [('item_count', -1), ('box_count', 65)]:
            bad = copy.deepcopy(good); setattr(bad, field, value)
            result, err = api.Result(), C.create_string_buffer(4)
            C.memset(C.byref(result), 0x55, C.sizeof(result))
            rc = self.adapter.lib.op3_pack(C.byref(bad), C.byref(result), err, len(err))
            self.assertEqual(rc, 1)
            self.assertEqual(bytes(result), bytes(C.sizeof(result)))
            self.assertEqual(err.raw[-1], 0)
        bad = copy.deepcopy(good); bad.items[0].diagonal = 0
        result, err = api.Result(), C.create_string_buffer(256)
        self.assertEqual(self.adapter.lib.op3_pack(C.byref(bad), C.byref(result), err, len(err)), 1)
        self.assertIn(b'diagonal', err.value)
        self.assertEqual(self.adapter.lib.op3_pack(None, C.byref(result), None, 0), 1)
        self.assertEqual(self.adapter.lib.op3_pack(C.byref(good), None, None, 0), 1)


class AdapterConversionTests(unittest.TestCase):
    def setUp(self):
        self.req = request()
        self.normalized, self.crequest = api.request_to_c(self.req)
        self.result = api.Result()
        self.result.placement_count = self.result.bin_count = 1
        self.result.placements[0] = api.Placement(0, 0, api.Pose(2, 3, 4, (C.c_double*3)(1, 1.5, 2), (C.c_double*4)(0, 0, 0, 1)))
        self.result.bins[0] = api.Bin(0, 0)
        self.result.total_cost = 1
        self.result.utilization = 24/1000
        self.result.elapsed_ms = 1
        self.result.candidates = self.result.restarts = 1
        self.result.stop_reason = 1

    def convert(self, result=None):
        return api.result_to_json(self.normalized, self.crequest, self.result if result is None else result)

    def rejects(self, mutate):
        bad = copy.deepcopy(self.result)
        mutate(bad)
        with self.assertRaises(ValueError):
            self.convert(bad)

    def test_valid_struct_is_preserved_and_independently_verified(self):
        result = self.convert()
        self.assertEqual(api.verify.validate_result(self.req, result), (0, 1, 1, 1000))
        pose = result['bins'][0]['items'][0]
        self.assertEqual([pose[k] for k in ('width', 'length', 'height')], [2, 3, 4])
        self.assertEqual(pose['center'], list(self.result.placements[0].pose.center))
        self.assertEqual(pose['orientation'], list(self.result.placements[0].pose.orientation))

    def test_returned_pose_dimensions_must_match_originals(self):
        for dimension in ('width', 'length', 'height'):
            for value in (0, 7, math.nan, math.inf):
                with self.subTest(dimension=dimension, value=value):
                    self.rejects(lambda r: setattr(r.placements[0].pose, dimension, value))

    def test_counts_are_bounded_and_consistent(self):
        for field in ('placement_count', 'bin_count', 'unpacked_count'):
            for value in (-1, 2, 257):
                with self.subTest(field=field, value=value):
                    self.rejects(lambda r: setattr(r, field, value))
        self.rejects(lambda r: setattr(r, 'bin_count', 0))

    def test_indices_never_use_python_negative_indexing(self):
        for field, values in [('item_index', (-1, 1, 256)), ('bin_index', (-1, 1, 256))]:
            for value in values:
                with self.subTest(field=field, value=value):
                    self.rejects(lambda r: setattr(r.placements[0], field, value))
        for value in (-1, 1, 64):
            self.rejects(lambda r: setattr(r.bins[0], 'box_index', value))
        for value in (-1, 1, 256):
            bad = copy.deepcopy(self.result)
            bad.placement_count = bad.bin_count = 0
            bad.unpacked_count = 1
            bad.unpacked[0] = value
            bad.stop_reason = 0
            with self.assertRaises(ValueError):
                self.convert(bad)

    def test_duplicate_missing_and_empty_bin_instances_rejected(self):
        self.normalized, self.crequest = api.request_to_c(request([item(quantity=2)]))
        bad = copy.deepcopy(self.result)
        bad.placement_count = 2
        bad.placements[1] = bad.placements[0]
        with self.assertRaises(ValueError):
            self.convert(bad)
        bad.placement_count = 1; bad.unpacked_count = 1; bad.unpacked[0] = 0
        with self.assertRaises(ValueError):
            self.convert(bad)
        bad.unpacked[0] = 1; bad.bin_count = 2; bad.bins[1] = bad.bins[0]
        with self.assertRaises(ValueError):
            self.convert(bad)

    def test_stop_reason_flags_and_counters_are_not_coerced(self):
        for value in (-1, 4):
            self.rejects(lambda r: setattr(r, 'stop_reason', value))
        for field in ('timed_out', 'budget_exhausted'):
            for value in (-1, 1, 2):
                self.rejects(lambda r: setattr(r, field, value))
        for field in ('candidates', 'xy_candidates', 'restarts'):
            self.rejects(lambda r: setattr(r, field, -1))
            self.rejects(lambda r: setattr(r, field, 1000000000))
        self.rejects(lambda r: setattr(r, 'xy_candidates', 2))
        self.rejects(lambda r: setattr(r, 'stop_reason', 0))
        for reason, flag in [(2, 'timed_out'), (3, 'budget_exhausted')]:
            bad = copy.deepcopy(self.result)
            bad.stop_reason = reason
            setattr(bad, flag, 1)
            with self.assertRaises(ValueError):
                self.convert(bad)  # Matching flags cannot assert an early stop.

    def test_nonfinite_and_negative_output_numbers_rejected(self):
        for field in ('total_cost', 'utilization', 'elapsed_ms', 'xy_elapsed_ms'):
            for value in (-1, math.nan, math.inf):
                self.rejects(lambda r: setattr(r, field, value))
        for value in (-1, math.nan, math.inf):
            self.rejects(lambda r: setattr(r.bins[0], 'weight', value))
        for field, count in [('center', 3), ('orientation', 4)]:
            for i in range(count):
                for value in (math.nan, math.inf, -math.inf):
                    self.rejects(lambda r: getattr(r.placements[0].pose, field).__setitem__(i, value))
        self.rejects(lambda r: setattr(r, 'xy_elapsed_ms', 2))


if __name__ == '__main__':
    unittest.main()
