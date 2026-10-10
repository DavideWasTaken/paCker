"""Independent high precision witnesses and fixed-seed C/oracle comparisons."""
import copy
import _ctypes
import ctypes
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from geometry3d_oracle import vertices, inside, intersects, canonicalize, rod_pose

ROOT = Path(__file__).resolve().parents[1]


def pose(center=(1, 1, 1), sides=(2, 2, 2), q=(0, 0, 0, 1)):
    return dict(width=sides[0], length=sides[1], height=sides[2],
                center=list(center), orientation=list(q))


class OracleTests(unittest.TestCase):
    def test_known_transforms(self):
        fixtures = json.loads((ROOT / 'tests/fixtures/poses3d.json').read_text())
        for case in fixtures['poses']:
            with self.subTest(case=case['name']):
                actual = vertices(case['pose'])
                for a, expected in zip(actual, case['vertices']):
                    for x, y in zip(a, expected):
                        self.assertAlmostEqual(float(x), y, places=12)

    def test_analytic_contacts_and_tolerance(self):
        a = pose()
        for center in [(3, 1, 1), (3, 3, 1), (3, 3, 3)]:
            self.assertFalse(intersects(a, pose(center)))
        self.assertFalse(intersects(a, pose((3 - 5e-10, 1, 1))))
        self.assertTrue(intersects(a, pose((3 - 5e-9, 1, 1))))
        self.assertTrue(intersects(a, pose((3, 1, 1)), .1))
        self.assertTrue(inside(a, [2, 2, 2]))
        self.assertFalse(inside(a, [2, 2, 2], .1))

    def test_rod_is_a_solid_witness(self):
        p = rod_pose()
        self.assertTrue(inside(p, [100, 100, 100]))
        vs = vertices(p)
        spans = [float(max(v[k] for v in vs) - min(v[k] for v in vs)) for k in range(3)]
        self.assertAlmostEqual(spans[0], 95.525, delta=.01)
        self.assertAlmostEqual(spans[2], 93.135, delta=.01)
        self.assertEqual(len(set(vs)), 8)

    def test_skew_rods_require_edge_cross_axis(self):
        # All six face normals have overlapping projections. The crossed
        # long-edge normal (0,-1,1) separates the skew finite rods.
        from decimal import localcontext
        import geometry3d_oracle as oracle
        a = pose((0, 0, 0), (6, .2, .2))
        b = rod_pose(); b.update(width=6, length=.2, height=.2, center=[0, -.5, .5])
        with localcontext() as ctx:
            ctx.prec = 60
            va, vb = vertices(a), vertices(b)
            axes = oracle._faces(oracle._edges(va)) + oracle._faces(oracle._edges(vb))
            for axis in axes:
                pa, pb = [oracle._dot(v, axis) for v in va], [oracle._dot(v, axis) for v in vb]
                self.assertLess(min(pb), max(pa))
                self.assertLess(min(pa), max(pb))
        self.assertFalse(intersects(a, b))

    def test_invalid_data_is_not_a_valid_pose(self):
        for field, bad in [('width', 0), ('height', math.inf), ('length', 1e-5),
                           ('orientation', [0, 0, 0, 0]), ('orientation', [0, 0, 0, 2]),
                           ('orientation', [math.nan, 0, 0, 1]), ('center', [0, 0, math.inf])]:
            p = pose(); p[field] = bad
            with self.subTest(field=field, bad=bad):
                with self.assertRaises(ValueError):
                    vertices(p)
        for margin in [-1, math.inf, math.nan, 1e6 + 1]:
            with self.assertRaises(ValueError):
                inside(pose(), [2, 2, 2], margin)
        p = pose(q=(0, -1, 0, 0)); self.assertEqual(canonicalize(p)['orientation'], [0, 1, 0, 0])


class Pose(ctypes.Structure):
    _fields_ = [('width', ctypes.c_double), ('length', ctypes.c_double), ('height', ctypes.c_double),
                ('center', ctypes.c_double * 3), ('orientation', ctypes.c_double * 4)]


def cpose(p):
    return Pose(p['width'], p['length'], p['height'],
                (ctypes.c_double * 3)(*p['center']), (ctypes.c_double * 4)(*p['orientation']))


class DifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='packer3d-')
        zig = ROOT / '.tools/zig-x86_64-windows-0.15.2/zig.exe'
        zig = zig if zig.exists() else Path(shutil.which('zig') or zig)
        compiler = [str(zig) if zig.is_file() else (shutil.which('zig') or 'zig'), 'cc'] if sys.platform == 'win32' else [shutil.which('cc') or 'cc']
        lib = Path(cls.temp.name) / ('geometry3d.dll' if sys.platform == 'win32' else 'geometry3d.so')
        command = compiler + ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                              '-I' + str(ROOT / 'include'), str(ROOT / 'src/geometry3d.c'), '-o', str(lib)]
        if sys.platform != 'win32':
            command += ['-fPIC', '-lm']
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.op3_inside.argtypes = [ctypes.POINTER(Pose), ctypes.POINTER(ctypes.c_double), ctypes.c_double, ctypes.POINTER(ctypes.c_int)]
        cls.lib.op3_intersects.argtypes = [ctypes.POINTER(Pose), ctypes.POINTER(Pose), ctypes.c_double, ctypes.POINTER(ctypes.c_int)]
        cls.lib.op3_vertices.argtypes = [ctypes.POINTER(Pose), ctypes.POINTER(ctypes.c_double * 3)]
        cls.lib.op3_pose_canonicalize.argtypes = [ctypes.POINTER(Pose), ctypes.POINTER(Pose)]

    @classmethod
    def tearDownClass(cls):
        if sys.platform == 'win32':
            _ctypes.FreeLibrary(cls.lib._handle)
            del cls.lib
        cls.temp.cleanup()

    def check_inside(self, p, box, margin=0, agree=False):
        out = ctypes.c_int(55); cp = cpose(p)
        rc = self.lib.op3_inside(ctypes.byref(cp), (ctypes.c_double * 3)(*box), margin, ctypes.byref(out))
        try:
            expected = inside(p, box, margin)
        except ValueError:
            self.assertEqual((rc, out.value), (1, 0)); return
        self.assertIn(rc, (0, 2))
        if out.value:
            self.assertTrue(expected, (p, box, margin))
        if agree:
            self.assertEqual(bool(out.value), expected, (p, box, margin, rc))
        return rc, bool(out.value), expected

    def check_pair(self, a, b, margin=0, agree=False):
        ca, cb = cpose(a), cpose(b); out = ctypes.c_int(55)
        rc = self.lib.op3_intersects(ctypes.byref(ca), ctypes.byref(cb), margin, ctypes.byref(out))
        try:
            expected = intersects(a, b, margin)
        except ValueError:
            self.assertEqual((rc, out.value), (1, 1)); return
        self.assertIn(rc, (0, 2))
        if not out.value:
            self.assertFalse(expected, (a, b, margin))
        reverse = ctypes.c_int()
        rr = self.lib.op3_intersects(ctypes.byref(cb), ctypes.byref(ca), margin, ctypes.byref(reverse))
        self.assertEqual((rc, out.value), (rr, reverse.value))
        if agree:
            self.assertEqual(bool(out.value), expected, (a, b, margin, rc))
        return rc, bool(out.value), expected

    def test_fixtures_and_rod(self):
        fixtures = json.loads((ROOT / 'tests/fixtures/poses3d.json').read_text())
        for case in fixtures['poses']:
            out = ((ctypes.c_double * 3) * 8)(); cp = cpose(case['pose'])
            self.assertEqual(self.lib.op3_vertices(ctypes.byref(cp), out), 0)
            for a, expected in zip(out, case['vertices']):
                for x, y in zip(a, expected):
                    self.assertAlmostEqual(x, y, places=12)
        self.check_inside(rod_pose(), [100] * 3, agree=True)
        a = pose((0, 0, 0), (6, .2, .2))
        b = rod_pose(); b.update(width=6, length=.2, height=.2, center=[0, -.5, .5])
        self.check_pair(a, b, agree=True)

    def test_fixed_seed_well_separated_poses(self):
        rng = random.Random(530816)
        for _ in range(400):
            sides = [10 ** rng.uniform(-4, 6) for _ in range(3)]
            q = [rng.gauss(0, 1) for _ in range(4)]; norm = math.sqrt(sum(x*x for x in q))
            q = [x/norm for x in q]
            a = pose([rng.uniform(-2e6, 2e6) for _ in range(3)], sides, q)
            b = copy.deepcopy(a)
            if rng.randrange(2):
                b['center'] = [x + 4e6 for x in a['center']]
            else:
                b['center'] = [x + rng.uniform(-.1, .1)*min(sides) for x in a['center']]
            self.check_pair(a, b, rng.choice([0, .0001, 10]), agree=True)
            self.check_inside(a, [1e6]*3, agree=True)
            c = pose([5e5]*3, [s*.1 for s in sides], q)
            # Scale down cannot go below the API's minimum dimension.
            c.update(zip(('width', 'length', 'height'), [max(1e-4, s*.1) for s in sides]))
            self.check_inside(c, [1e6]*3, 10, agree=True)

    def test_boundary_and_numerical_uncertainty(self):
        rng = random.Random(82369); conservative = 0; uncertain = 0
        for _ in range(150):
            size = rng.choice([1e-4, 1, 1e6]); e = min(1e-9, size*1e-9)
            a = pose((size/2,)*3, (size,)*3)
            b = pose((1.5*size + rng.choice([-2, -.5, 0, .5, 2])*e, size/2, size/2), (size,)*3)
            rc, actual, expected = self.check_pair(a, b)
            uncertain += rc == 2; conservative += actual and not expected
            self.check_inside(a, [size]*3)
        for angle in [1e-18, 1e-14, 1e-10, .001]:
            for offset in [0, 5e-5, .001, 1]:
                a = pose((1e12, 1e12, 1e12), (1e6, 1e-4, 1e-4))
                b = pose((1e12, 1e12+offset, 1e12), (1e6, 1e-4, 1e-4), (0, 0, math.sin(angle/2), math.cos(angle/2)))
                rc, actual, expected = self.check_pair(a, b)
                uncertain += rc == 2; conservative += actual and not expected
        print(f'geometry3d boundaries: conservative rejections={conservative}, uncertain={uncertain}')

    def test_unrelated_rotations_and_cross_axis_separation(self):
        rng = random.Random(950237)
        for _ in range(500):
            def random_pose():
                q = [rng.gauss(0, 1) for _ in range(4)]
                n = math.sqrt(sum(x*x for x in q))
                return pose([rng.uniform(-4, 4) for _ in range(3)],
                            [rng.uniform(.2, 10) for _ in range(3)], [x/n for x in q])
            self.check_pair(random_pose(), random_pose(), rng.choice([0, .1, 1]), agree=True)

    def test_fail_closed_when_tiny_margin_cannot_be_resolved(self):
        # Exact cyclic axis permutation represented by a composed quaternion.
        # Large/small sides amplify interval uncertainty on zero matrix entries.
        # The oracle proves this exact fit, while C must reject if undecidable.
        a = pose((5e-5, 5e5, 5e-5), (1e6, 1e-4, 1e-4), (.5, .5, .5, .5))
        rc, actual, expected = self.check_inside(a, [1e-4, 1e6, 1e-4])
        self.assertTrue(expected)
        self.assertEqual((rc, actual), (2, False))
        print('geometry3d exact cyclic-permutation fit: oracle valid, C UNCERTAIN, rejected conservatively')

    def test_invalid_inputs_fail_closed(self):
        for key, values in [('width', [0, -1, 1e-5, 1e6+1, math.nan, math.inf]),
                            ('center', [[math.nan, 0, 0], [0, math.inf, 0]]),
                            ('orientation', [[0]*4, [0, 0, 0, 2], [0, 0, math.nan, 1]])]:
            for value in values:
                p = pose(); p[key] = value
                self.check_inside(p, [10]*3); self.check_pair(pose(), p)
        for margin in [-1, math.nan, math.inf, 1e6+1]:
            self.check_inside(pose(), [10]*3, margin); self.check_pair(pose(), pose(), margin)
        rng = random.Random(690213)
        for _ in range(60):
            p = pose([rng.uniform(-1e6, 1e6) for _ in range(3)],
                     [10**rng.uniform(-4, 6) for _ in range(3)])
            if rng.randrange(2):
                p['orientation'][3] = rng.choice([-2, 0, 2])
            else:
                p[rng.choice(['width', 'length', 'height'])] = rng.choice([-math.inf, math.nan, -1, 1e7])
            self.check_inside(p, [1e6]*3); self.check_pair(pose(), p)

    def test_quaternion_norm_boundary_status_and_propagation(self):
        # Exact binary64 input semantics place the first quaternion just INSIDE
        # the documented squared-norm threshold. Windows Python's 53-bit x87
        # arithmetic cannot certify that boundary, so INVALID is not permitted.
        cases = [(0.9999999999995001, True), (0.9999999999994998, False),
                 (0.99999999999949, False)]
        for w, valid in cases:
            p = pose(q=(0, 0, 0, w)); cp = cpose(p)
            if valid:
                self.assertTrue(inside(p, [2]*3))
            else:
                with self.assertRaises(ValueError):
                    vertices(p)
            out = Pose(); out.width = 99
            rc = self.lib.op3_pose_canonicalize(ctypes.byref(cp), ctypes.byref(out))
            self.assertIn(rc, (0, 2) if valid else (1, 2), (w, rc))
            if w == 0.99999999999949:
                self.assertEqual(rc, 1)  # Certainly beyond the threshold.
            if rc:
                self.assertEqual(bytes(out), bytes(Pose()))
            vs = ((ctypes.c_double * 3) * 8)()
            vs[0][0] = 99
            vr = self.lib.op3_vertices(ctypes.byref(cp), vs)
            self.assertEqual(vr, rc)
            if vr:
                self.assertTrue(all(value == 0 for vertex in vs for value in vertex))
            accepted = ctypes.c_int(99)
            ir = self.lib.op3_inside(ctypes.byref(cp), (ctypes.c_double*3)(2, 2, 2), 0, ctypes.byref(accepted))
            self.assertEqual(ir, rc)
            self.assertEqual(accepted.value, 0 if rc else 1)
            blocked = ctypes.c_int(99); other = cpose(pose((10, 10, 10)))
            hr = self.lib.op3_intersects(ctypes.byref(cp), ctypes.byref(other), 0, ctypes.byref(blocked))
            self.assertEqual(hr, rc)
            self.assertEqual(blocked.value, 1 if rc else 0)


if __name__ == '__main__':
    unittest.main()
