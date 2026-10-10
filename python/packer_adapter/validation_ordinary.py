"""Independent ordinary result checks, with schema validation before geometry."""
import math
from collections import Counter
from decimal import localcontext
from itertools import permutations

from .ordinary_geometry import (PRECISION, clip_polygon, decimal, epsilon, full_support, vertices,
                               pair_error, rests, stable, walls)

DIMENSIONS = ('width', 'length', 'height')
MACHINE_EPSILON = 2**-52


def polygon(p):
    with localcontext() as context:
        context.prec = PRECISION
        return [(float(x), float(y)) for x, y in vertices(p)]


def cross(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])


def contains(poly, p):
    return all(cross(a, b, p) >= 0 for a, b in zip(poly, poly[1:]+poly[:1]))


def intersection_area(subject, clip):
    result = clip_polygon(subject, clip)
    if not result:
        return 0
    # Translating before shoelace avoids cancellation far from origin.
    x, y = result[0]
    local = [(u-x, v-y) for u, v in result]
    return abs(math.fsum(a[0]*b[1]-a[1]*b[0]
                        for a, b in zip(local, local[1:]+local[:1])))/2


def _number(value, low=-math.inf, high=math.inf, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return (math.isfinite(value) and low <= value <= high and
                (not integer or value == int(value)))
    except (OverflowError, ValueError):
        return False


def _identity(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        return False
    try:
        return len(value.encode('utf-8')) <= 63
    except UnicodeEncodeError:
        return False


def _close(actual, expected, terms=1):
    """Relative allowance for sums/derived statistics; zero remains strict."""
    return abs(actual-expected) <= 2*MACHINE_EPSILON*(terms+2)*max(abs(actual), abs(expected))


def _copied_scalar(actual, expected, physical_limit=math.inf):
    """cJSON may round copied doubles within DBL_EPSILON, but never beyond
    the source shape's physical epsilon when comparing dimensions.
    """
    return abs(actual-expected) <= min(physical_limit,
                                      MACHINE_EPSILON*max(abs(actual), abs(expected)))


def _source_support(p, groups, own, mode='full_base'):
    """Certify coverage from uniquely identified source faces only.

    Ambiguous serialized face assignments are harmless if the unique faces
    already prove coverage. Otherwise report inability, not definite invalidity.
    No global orientation combinations are searched and no output is repaired.
    """
    supports, ambiguous = [], False
    for index, variants in enumerate(groups):
        if index == own:
            continue
        if len(variants) == 1:
            supports.append(variants[0])
        elif any(abs(decimal(q['z'])+decimal(q['height'])-decimal(p['z'])) <= epsilon(p)
                 for q in variants):
            ambiguous = True
    check = {'full_base': full_support, 'contact': rests, 'stable': stable}[mode]
    if check(p, supports):
        return None
    if ambiguous:
        return 'cannot verify ambiguous serialized dimensions'
    if mode == 'full_base':
        return 'unsupported footprint'
    return 'product would tip' if mode == 'stable' and rests(p, supports) else 'product rests on nothing'


def _request_errors(request):
    errors = []

    def fields(obj, allowed, label):
        if not isinstance(obj, dict):
            errors.append(f'{label} must be an object')
            return False
        if set(obj)-set(allowed):
            errors.append(f'{label} has unknown fields')
        return True

    if not fields(request, ('boxes', 'items', 'options'), 'request'):
        return errors
    expanded = 0
    for kind, limit in (('boxes', 64), ('items', 256)):
        rows = request.get(kind)
        if not isinstance(rows, list) or len(rows) > limit:
            errors.append(f'invalid {kind} array')
            continue
        ids = set()
        for row in rows:
            extra = ('max_weight', 'cost') if kind == 'boxes' else ('weight', 'rotation', 'diagonal')
            if not fields(row, ('id', *DIMENSIONS, 'quantity', *extra), kind):
                continue
            identity = row.get('id')
            if not _identity(identity):
                errors.append(f'invalid {kind} id')
            elif identity in ids:
                errors.append(f'duplicate {kind} id')
            else:
                ids.add(identity)
            for key in DIMENSIONS:
                if not _number(row.get(key), .0001, 1e6):
                    errors.append(f'invalid {kind} {key}')
            is_box = kind == 'boxes'
            quantity = row.get('quantity', -1 if is_box else 1)
            if not _number(quantity, -1 if is_box else 1, 256, integer=True):
                errors.append(f'invalid {kind} quantity')
            elif not is_box:
                expanded += int(quantity)
            defaults = {'max_weight': 1e12, 'cost': 1} if is_box else {'weight': 0}
            for key, fallback in defaults.items():
                if not _number(row.get(key, fallback), 0, 1e12):
                    errors.append(f'invalid {kind} {key}')
            if not is_box:
                if row.get('rotation', 'flat') not in ('none', 'flat', 'any'):
                    errors.append('invalid item rotation')
                if not isinstance(row.get('diagonal', True), bool):
                    errors.append('invalid item diagonal')
    if expanded > 256:
        errors.append('expanded item limit exceeded')
    options = request.get('options', {})
    ranges = {'gap': (0, 1e6, False), 'angle_step': (1, 90, True),
              'time_limit_ms': (1, 60000, False), 'restarts': (1, 64, True),
              'seed': (0, 4294967295, True), 'max_candidates': (1, 100000000, True)}
    if fields(options, (*ranges, 'support_mode', 'improve'), 'options'):
        if options.get('support_mode', 'stable') not in ('stable', 'contact', 'full_base'):
            errors.append('invalid support mode')
        if not isinstance(options.get('improve', False), bool):
            errors.append('invalid option improve')
        for key, value in options.items():
            if key in ranges and not _number(value, *ranges[key]):
                errors.append(f'invalid option {key}')
    return errors


def _result_errors(result):
    errors = []
    if not isinstance(result, dict):
        return ['result must be an object']

    def numeric(obj, key, low=0, high=math.inf, integer=False):
        if not _number(obj.get(key), low, high, integer):
            errors.append(f'invalid result {key}')

    def identity(obj, key):
        if not _identity(obj.get(key)):
            errors.append(f'invalid result {key}')

    for name in ('bins', 'unpacked'):
        if not isinstance(result.get(name), list):
            errors.append(f'result {name} must be an array')
    if result.get('status') not in ('complete', 'partial'):
        errors.append('invalid result status')
    stats = result.get('stats')
    if not isinstance(stats, dict):
        errors.append('result stats must be an object')
    else:
        numeric(stats, 'box_count', integer=True)
        numeric(stats, 'total_cost')
        numeric(stats, 'utilization', high=1)
        for key in ('elapsed_ms', 'candidates', 'restarts'):
            # Upstream adapters report unavailable search counts as null.
            if key in stats and not (key != 'elapsed_ms' and stats[key] is None):
                numeric(stats, key, integer=key != 'elapsed_ms')
        for key in ('timed_out', 'budget_exhausted'):
            if key in stats and not isinstance(stats[key], bool):
                errors.append(f'invalid result {key}')
    for b in result.get('bins', []) if isinstance(result.get('bins'), list) else []:
        if not isinstance(b, dict):
            errors.append('result bin must be an object')
            continue
        identity(b, 'id'); identity(b, 'type_id')
        for key in DIMENSIONS:
            numeric(b, key, .0001, 1e6)
        numeric(b, 'weight')
        for key in ('max_weight', 'cost'):
            if key in b:
                numeric(b, key, high=1e12)
        if not isinstance(b.get('items'), list):
            errors.append('result bin items must be an array')
            continue
        for p in b['items']:
            if not isinstance(p, dict):
                errors.append('result placement must be an object')
                continue
            identity(p, 'id'); numeric(p, 'instance', 0, 255, True)
            for key in DIMENSIONS:
                numeric(p, key, .0001, 1e6)
            for key in ('x', 'y', 'z', 'angle'):
                numeric(p, key, -math.inf)
            numeric(p, 'weight', high=1e12)
    for u in result.get('unpacked', []) if isinstance(result.get('unpacked'), list) else []:
        if not isinstance(u, dict):
            errors.append('unpacked instance must be an object')
        else:
            identity(u, 'id'); numeric(u, 'instance', 0, 255, True)
    return errors


def validate(request, result, require_support=None, diagnostics=False):
    """require_support None follows the request support_mode (default stable);
    True demands full-base support and False checks no support at all."""
    errors = _request_errors(request) + _result_errors(result)
    if errors:
        return errors
    if require_support is None:
        mode = request.get('options', {}).get('support_mode', 'stable')
    else:
        mode = 'full_base' if require_support else None

    scope = '/'

    def report(message):
        errors.append(f'{scope}: {message}' if diagnostics else message)

    def check(ok, message):
        if not ok:
            report(message)

    boxes = {b['id']: b for b in request['boxes']}
    items = {i['id']: i for i in request['items']}
    expected = Counter((i['id'], k) for i in request['items']
                       for k in range(int(i.get('quantity', 1))))
    observed, stocks, bin_ids = Counter(), Counter(), set()
    volumes, costs, packed_volumes = [], [], []
    gap = request.get('options', {}).get('gap', 0)
    for box_index, b in enumerate(result['bins']):
        scope = f'/bins/{box_index}'
        check(b['id'] not in bin_ids, 'duplicate bin id'); bin_ids.add(b['id'])
        ps = b['items']
        for p in ps:
            observed[(p['id'], int(p['instance']))] += 1
        if b['type_id'] not in boxes:
            report('unknown box')
            continue
        source = boxes[b['type_id']]
        stocks[source['id']] += 1
        source_epsilon = float(epsilon(source))
        check(all(_copied_scalar(b[k], source[k], source_epsilon) for k in DIMENSIONS),
              'box dimensions changed')
        for key, default in (('cost', 1), ('max_weight', 1e12)):
            if key in b:
                check(_copied_scalar(b[key], source.get(key, default)), f'box {key} changed')
        volumes.append(math.prod(source[k] for k in DIMENSIONS))
        costs.append(source.get('cost', 1))
        weights, geometry = [], []
        for item_index, p in enumerate(ps):
            scope = f'/bins/{box_index}/items/{item_index}'
            if p['id'] not in items:
                report('unknown item')
                geometry.append([p])
                continue
            original = items[p['id']]
            dimensions = tuple(p[k] for k in DIMENSIONS)
            original_dimensions = tuple(original[k] for k in DIMENSIONS)
            rotation = original.get('rotation', 'flat')
            choices = list(permutations(original_dimensions)) if rotation == 'any' else [
                original_dimensions, (original_dimensions[1], original_dimensions[0], original_dimensions[2])]
            if rotation == 'none':
                choices = [original_dimensions]
            # Geometry uses authoritative source sides in each compatible face
            # assignment, retaining reported coordinates and angle unchanged.
            # This prevents harmless scalar serialization allowances from
            # allowing a rounded smaller side to conceal a physical violation.
            matches = list(dict.fromkeys(choice for choice in choices if all(
                _copied_scalar(a, d, float(epsilon(original)))
                for a, d in zip(dimensions, choice))))
            check(bool(matches), 'forbidden face orientation')
            variants = [dict(p, **dict(zip(DIMENSIONS, choice))) for choice in matches] or [p]
            geometry.append(variants)
            if rotation == 'none':
                check(p['angle'] == 0, 'rotation none violated')
            elif not original.get('diagonal', True):
                check(p['angle'] % 90 == 0, 'diagonal forbidden')
            check(_copied_scalar(p['weight'], original.get('weight', 0)), 'item weight changed')
            weights.append(original.get('weight', 0))
            packed_volumes.append(math.prod(original[k] for k in DIMENSIONS))
            bounds = [walls(variant, source, gap) for variant in variants]
            check(all(xy for xy, z in bounds), 'outside XY walls')
            check(all(z for xy, z in bounds), 'outside Z walls')
        scope = f'/bins/{box_index}'
        weight = math.fsum(weights)
        capacity = source.get('max_weight', 1e12)
        check(weight <= capacity or (capacity > 0 and _close(weight, capacity, len(weights))),
              'weight capacity exceeded')
        check(_close(weight, b['weight'], len(weights)), 'bin weight mismatch')
        valid_solids = True
        for i, variants in enumerate(geometry):
            for j, other in enumerate(geometry[:i]):
                scope = f'/bins/{box_index}/items/{i} (with /bins/{box_index}/items/{j})'
                pair_errors = list(dict.fromkeys(error for p in variants for q in other
                                                  if (error := pair_error(p, q, gap))))
                if pair_errors:
                    for error in pair_errors:
                        report(error)
                    valid_solids = False
        # The coverage sweep requires mutually disjoint solids.
        if mode and valid_solids:
            for i, variants in enumerate(geometry):
                scope = f'/bins/{box_index}/items/{i}'
                for p in variants:
                    error = _source_support(p, geometry, i, mode)
                    if error:
                        report(error)
    for unpacked_index, u in enumerate(result['unpacked']):
        scope = f'/unpacked/{unpacked_index}'
        if u['id'] not in items:
            report('unknown item')
        observed[(u['id'], int(u['instance']))] += 1
    scope = '/'
    check(observed == expected, 'missing/duplicated instance')
    for identity, count in stocks.items():
        stock = boxes[identity].get('quantity', -1)
        check(stock < 0 or count <= stock, 'stock exceeded')
    check(result['status'] == ('partial' if result['unpacked'] else 'complete'), 'status mismatch')
    stats = result['stats']
    scope = '/stats'
    check(stats['box_count'] == len(result['bins']), 'box_count mismatch')
    check(_close(stats['total_cost'], math.fsum(costs), len(costs)), 'cost mismatch')
    volume = math.fsum(volumes)
    utilization = math.fsum(packed_volumes)/volume if volume else 0
    check(_close(stats['utilization'], utilization, len(packed_volumes)+len(volumes)), 'utilization mismatch')
    return errors

