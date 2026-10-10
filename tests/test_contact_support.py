"""Independent validator: contact (default) versus full-base support."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from packer_adapter.ordinary_geometry import rests  # noqa: E402
from packer_adapter.validation_ordinary import validate  # noqa: E402


def request(mode=None):
    options = {} if mode is None else {'support_mode': mode}
    return {'boxes': [{'id': 'box', 'width': 40, 'length': 20, 'height': 25}],
            'items': [{'id': 'base', 'width': 20, 'length': 20, 'height': 10, 'rotation': 'none'},
                      {'id': 'top', 'width': 20, 'length': 20, 'height': 10, 'rotation': 'none'}],
            'options': options}


def result(top_x, top_z=10):
    placed = [dict(id='base', instance=0, x=10, y=10, z=0, width=20, length=20, height=10, angle=0, weight=0),
              dict(id='top', instance=0, x=top_x, y=10, z=top_z, width=20, length=20, height=10, angle=0, weight=0)]
    return {'version': '0.4.0', 'support_mode': 'contact', 'status': 'complete', 'unpacked': [],
            'bins': [{'id': 'bin-1', 'type_id': 'box', 'width': 40, 'length': 20, 'height': 25, 'weight': 0,
                      'items': placed}],
            'stats': {'box_count': 1, 'total_cost': 1, 'utilization': 8000/20000}}


class ContactTests(unittest.TestCase):
    def test_overhang_is_contact_but_not_full_base(self):
        self.assertEqual(validate(request(), result(25)), [])
        self.assertEqual(validate(request('contact'), result(25)), [])
        self.assertEqual(validate(request('full_base'), result(25)), ['unsupported footprint'])
        self.assertEqual(validate(request('contact'), result(25), require_support=True), ['unsupported footprint'])

    def test_floating_and_edge_contact_are_rejected(self):
        self.assertEqual(validate(request(), result(25, 11)), ['product rests on nothing'])
        self.assertEqual(validate(request(), result(30)), ['product rests on nothing'])
        self.assertEqual(validate(request(), result(30), require_support=False), [])

    def test_rotated_overlap_counts(self):
        base = dict(x=10, y=10, z=0, width=20, length=20, height=10, angle=0)
        self.assertTrue(rests(dict(base, z=10, x=32, angle=45), [base]))
        self.assertFalse(rests(dict(base, z=10, x=40, angle=45), [base]))


if __name__ == '__main__':
    unittest.main()
