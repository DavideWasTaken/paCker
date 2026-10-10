"""Analytic ordinary packing cases; no solver participates in these checks."""
import copy
import math
import unittest

from validate_result import full_support, polygon, validate


def fixture(poses, gap=0, capacity=1e12):
    items = [dict(id=str(i), width=p['width'], length=p['length'],
                  height=p['height'], weight=p.get('weight', 0))
             for i, p in enumerate(poses)]
    placements = [dict(p, id=str(i), instance=0, weight=p.get('weight', 0))
                  for i, p in enumerate(poses)]
    box = dict(id='box', width=1000000, length=1000000, height=1000000,
               max_weight=capacity, cost=1)
    request = dict(boxes=[box], items=items, options=dict(gap=gap))
    weight = math.fsum(p['weight'] for p in placements)
    result = dict(status='complete', bins=[dict(box, id='bin-1', type_id='box',
                  weight=weight, items=placements)], unpacked=[],
                  stats=dict(box_count=1, total_cost=1,
                             utilization=sum(p['width']*p['length']*p['height']
                                             for p in placements)/1e18))
    return request, result


def pose(**kwargs):
    return dict(dict(x=2, y=2, z=0, width=1, length=1, height=1, angle=0), **kwargs)


class OrdinaryValidatorTests(unittest.TestCase):
    def assert_invalid(self, request, result, message=None):
        try:
            errors = validate(request, result)
        except Exception as exc:
            self.fail(f'validator raised {type(exc).__name__}: {exc}')
        self.assertIsInstance(errors, list)
        self.assertTrue(errors, 'invalid output was accepted')
        self.assertTrue(all(isinstance(error, str) for error in errors))
        if message:
            self.assertIn(message, errors)

    def test_thin_overlap_is_linear_not_area(self):
        request, result = fixture([pose(length=.0001), pose(x=2.99, length=.0001)])
        self.assert_invalid(request, result, 'overlapping products')
        result['bins'][0]['items'][1]['x'] = 3
        self.assertEqual(validate(request, result), [])

    def test_pair_gap_shortfall_while_wall_gap_passes(self):
        request, result = fixture([pose(), pose(x=3.1)], gap=.2)
        self.assert_invalid(request, result, 'XY gap shortfall')
        result['bins'][0]['items'][1]['x'] = 3.2
        self.assertEqual(validate(request, result), [])

    def test_vertical_contact_removes_xy_gap_requirement(self):
        request, result = fixture([pose(), pose(z=1)], gap=.2)
        self.assertEqual(validate(request, result), [])

    def test_small_scale_overlap_and_wall_violation(self):
        request, result = fixture([pose(x=.001, y=.001, width=.0001, length=.0001,
                                        height=.0001),
                                   pose(x=.00109, y=.001, width=.0001,
                                        length=.0001, height=.0001)])
        self.assert_invalid(request, result, 'overlapping products')
        result['bins'][0]['items'][1]['x'] = .0011
        self.assertEqual(validate(request, result), [])
        result['bins'][0]['items'][0]['x'] = .00005 - 1e-10
        self.assert_invalid(request, result, 'outside XY walls')

    def test_long_thin_quarter_turn_has_exact_axes(self):
        p = pose(x=.00005, y=500000, width=1000000, length=.0001,
                 height=.0001, angle=90)
        request, result = fixture([p])
        self.assertEqual(min(x for x, y in polygon(p)), 0)
        self.assertEqual(validate(request, result), [])
        result['bins'][0]['items'][0]['x'] -= 1e-10
        self.assert_invalid(request, result, 'outside XY walls')

    def test_long_support_missing_strip_is_not_area_forgiven(self):
        p = pose(x=500000, width=1000000, length=.0001, height=.0001, z=1)
        a = pose(x=250000 - .000001, width=500000 - .000002,
                 length=.0001, height=1)
        b = pose(x=750000, width=500000, length=.0001, height=1)
        self.assertFalse(full_support(p, [a, b]))
        a.update(x=250000, width=500000)
        self.assertTrue(full_support(p, [a, b]))

    def test_support_contact_plane_uses_item_scale(self):
        p = pose(width=.0001, length=.0001, height=.0001, z=1)
        base = pose(height=1-1e-10)
        self.assertFalse(full_support(p, [base]))
        base['height'] = 1
        self.assertTrue(full_support(p, [base]))

    def test_zero_capacity_rejects_positive_tiny_weight(self):
        request, result = fixture([pose(weight=1e-12)], capacity=0)
        self.assert_invalid(request, result, 'weight capacity exceeded')
        request['items'][0]['weight'] = result['bins'][0]['items'][0]['weight'] = 0
        result['bins'][0]['weight'] = 0
        self.assertEqual(validate(request, result), [])

    def test_forbidden_face_and_rotation(self):
        request, result = fixture([pose(width=1, length=2, height=3)])
        request['items'][0]['rotation'] = 'flat'
        result['bins'][0]['items'][0].update(width=3, height=1)
        self.assert_invalid(request, result, 'forbidden face orientation')
        request['items'][0]['rotation'] = 'any'
        self.assertEqual(validate(request, result), [])
        request['items'][0]['diagonal'] = False
        result['bins'][0]['items'][0]['angle'] = .000001
        self.assert_invalid(request, result, 'diagonal forbidden')
        result['bins'][0]['items'][0]['angle'] = 90
        self.assertEqual(validate(request, result), [])

    def test_malformed_request_returns_errors(self):
        request, result = fixture([pose()])
        variants = [None, [], {}, dict(request, boxes=None), dict(request, items=[None]),
                    dict(request, options=[])]
        for field, value in [('width', True), ('height', -1), ('length', float('nan')),
                             ('quantity', .5), ('weight', '1'), ('id', []),
                             ('rotation', []), ('diagonal', 1)]:
            bad = copy.deepcopy(request); bad['items'][0][field] = value; variants.append(bad)
        bad = copy.deepcopy(request); bad['items'].append(copy.deepcopy(bad['items'][0])); variants.append(bad)
        for bad in variants:
            with self.subTest(request=bad): self.assert_invalid(bad, result)

    def test_malformed_result_returns_errors(self):
        request, result = fixture([pose()])
        variants = [None, [], {}, dict(result, bins=None), dict(result, unpacked=[None]),
                    dict(result, stats=None), dict(result, bins=[None])]
        for field, value in [('x', float('inf')), ('y', '2'), ('width', False),
                             ('height', 0), ('id', []), ('instance', True), ('angle', None)]:
            bad = copy.deepcopy(result); bad['bins'][0]['items'][0][field] = value; variants.append(bad)
        bad = copy.deepcopy(result); del bad['bins'][0]['items'][0]['z']; variants.append(bad)
        bad = copy.deepcopy(result); bad['bins'][0]['items'].append(copy.deepcopy(bad['bins'][0]['items'][0])); variants.append(bad)
        for bad in variants:
            with self.subTest(result=bad): self.assert_invalid(request, bad)

    def test_identity_stock_and_statistics(self):
        request, result = fixture([pose()])
        for mutate in [lambda r: r['bins'][0].update(type_id='unknown'),
                       lambda r: r['bins'][0]['items'][0].update(id='unknown'),
                       lambda r: r['stats'].update(total_cost=2),
                       lambda r: r['stats'].update(utilization=.1),
                       lambda r: r['stats'].update(box_count=True),
                       lambda r: r['bins'][0].update(cost=2),
                       lambda r: r['bins'][0].update(max_weight=0),
                       lambda r: r['bins'][0].update(weight=float('nan'))]:
            bad = copy.deepcopy(result); mutate(bad); self.assert_invalid(request, bad)
        request['boxes'][0]['quantity'] = 0
        self.assert_invalid(request, result, 'stock exceeded')

    def test_unavailable_upstream_search_diagnostics(self):
        request, result = fixture([pose()])
        result['stats'].update(candidates=None, restarts=None)
        self.assertEqual(validate(request, result), [])

    def test_extreme_finite_angle_does_not_raise(self):
        request, result = fixture([pose(angle=1e308)])
        # A square at a non-quarter turn is valid away from all walls.
        self.assertEqual(validate(request, result), [])

    def test_pair_uses_smaller_epsilon_and_z_separation(self):
        request, result = fixture([pose(), pose(x=2.50004999999, width=.0001)])
        self.assert_invalid(request, result, 'overlapping products')
        result['bins'][0]['items'][1].update(x=2, z=1)
        self.assertEqual(validate(request, result), [])
        result['bins'][0]['items'][1]['z'] = 1 - 1e-10
        self.assert_invalid(request, result, 'overlapping products')

    def test_cost_and_weight_roundoff_is_relative(self):
        request, result = fixture([pose(weight=1e-12)], capacity=1e-12)
        self.assertEqual(validate(request, result), [])
        result['bins'][0]['items'][0]['weight'] = 2e-12
        self.assert_invalid(request, result, 'item weight changed')
        request, result = fixture([pose()])
        request['boxes'][0]['cost'] = result['bins'][0]['cost'] = 1e-12
        result['stats']['total_cost'] = 2e-12
        self.assert_invalid(request, result, 'cost mismatch')

    def test_reported_dimensions_cannot_shrink_a_long_thin_item(self):
        request, result = fixture([pose(x=500000-5e-10, width=1e6,
                                        length=.0001, height=.0001)])
        self.assert_invalid(request, result, 'outside XY walls')
        result['bins'][0]['items'][0]['width'] -= 1e-9
        self.assert_invalid(request, result, 'forbidden face orientation')

    def test_copied_scalars_allow_cjson_one_ulp_rounding(self):
        request, result = fixture([pose(weight=1)])
        for field in ('width', 'length', 'height', 'max_weight', 'cost'):
            bad = copy.deepcopy(result)
            bad['bins'][0][field] = math.nextafter(bad['bins'][0][field], 0)
            self.assertEqual(validate(request, bad), [])
        for field in ('width', 'length', 'height', 'weight'):
            bad = copy.deepcopy(result)
            bad['bins'][0]['items'][0][field] = math.nextafter(
                bad['bins'][0]['items'][0][field], 0)
            self.assertEqual(validate(request, bad), [])

    def test_cjson_rounded_source_width_and_weight_are_supported(self):
        value = math.nextafter(1., math.inf)
        request, result = fixture([pose(width=value, weight=value)])
        result['bins'][0]['items'][0].update(width=1, weight=1)
        result['bins'][0]['weight'] = 1
        self.assertEqual(validate(request, result), [])

    def test_serialized_dimension_allowance_cannot_hide_wall_violation(self):
        request, result = fixture([pose(x=500000-1.05e-9, width=1e6,
                                        length=1, height=1)])
        # One ULP is inside cJSON's relative bound and the physical epsilon.
        # Using the rounded width for geometry would hide the real overflow.
        result['bins'][0]['items'][0]['width'] = math.nextafter(1e6, 0)
        self.assert_invalid(request, result, 'outside XY walls')

    def test_serialized_dimension_allowance_cannot_hide_pair_overlap(self):
        request, result = fixture([pose(x=499999.5, width=999998),
                                   pose(x=999999-1.1e-9)])
        result['bins'][0]['items'][0]['width'] = math.nextafter(999998, 0)
        self.assert_invalid(request, result, 'overlapping products')

    def test_ambiguous_serialized_face_on_floor_is_valid(self):
        request, result = fixture([pose(width=math.nextafter(1., math.inf))])
        result['bins'][0]['items'][0]['width'] = 1
        self.assertEqual(validate(request, result), [])

    def test_ambiguous_serialized_support_reports_inability(self):
        request, result = fixture([pose(width=math.nextafter(1., math.inf)), pose(z=1)])
        result['bins'][0]['items'][0]['width'] = 1
        self.assert_invalid(request, result, 'cannot verify ambiguous serialized dimensions')


if __name__ == '__main__':
    unittest.main()
