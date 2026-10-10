"""Independent request/schema-2 verifier. Never imports or invokes an engine.

A Decimal (60-digit) vertex/face oracle supplies only geometric predicates.
This module checks JSON, identities, constraints, permissions and bookkeeping.
"""
import argparse
from collections import Counter
from contextvars import ContextVar
from decimal import Decimal, localcontext
from . import geometry3d_oracle as ORACLE
import json
import math
from pathlib import Path

DIMENSIONS = ('width', 'length', 'height')
ORIENTATION_ERROR = Decimal(2) ** -49  # eight binary64 epsilons, dimensionless
DEFAULT_OPTIONS = dict(angle_step=15, restarts=8, max_candidates=200000,
                       time_limit_ms=1000, seed=42, gap=0,
                       support_mode='full_base', clearance=0)
_SCOPE = ContextVar('validation_location', default=None)


def _locate(path):
    if _SCOPE.get() is not None:
        _SCOPE.set(path)


def require(condition, message):
    if not condition:
        location = _SCOPE.get()
        raise ValueError(f'{location}: {message}' if location is not None else message)


def finite_tree(value, depth=0):
    require(depth <= 64, 'JSON nesting exceeds 64')
    if value is None or type(value) is bool:
        return
    if type(value) in (int, float):
        try:
            require(math.isfinite(float(value)), 'non-finite JSON number')
        except OverflowError as exc:
            raise ValueError('number outside binary64') from exc
    elif isinstance(value, str):
        require('\0' not in value, 'embedded NUL')
        try:
            value.encode('utf-8')
        except UnicodeError as exc:
            raise ValueError('invalid UTF-8 string') from exc
    elif type(value) is list:
        for child in value:
            finite_tree(child, depth+1)
    elif type(value) is dict:
        for key, child in value.items():
            require(type(key) is str, 'JSON object key must be string')
            finite_tree(key, depth+1); finite_tree(child, depth+1)
    else:
        raise ValueError('not a JSON value')


def loads(text):
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, 'duplicate JSON member')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('non-finite JSON literal: '+value)
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        finite_tree(value)
        return value
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('invalid JSON depth/encoding') from exc


def load_request(text):
    require(type(text) is str and len(text.encode('utf-8')) <= 1048576,
            'raw request exceeds 1 MiB')
    value = loads(text)
    validate_request(value)
    return value


def numeric(value, low=-math.inf, high=math.inf, integer=False):
    require(type(value) in (int, float), 'expected JSON number')
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError('number outside binary64') from exc
    require(math.isfinite(value) and low <= value <= high, 'numeric range/finite error')
    require(not integer or value.is_integer(), 'expected integral number')
    return int(value) if integer else value


def identity(value):
    require(type(value) is str and 1 <= len(value.encode('utf-8')) <= 63 and '\0' not in value,
            'id must have 1..63 UTF-8 bytes')
    return value


def fields(value, allowed, required=()):
    require(type(value) is dict, 'expected object')
    require(set(value) <= set(allowed), 'unknown request field')
    require(set(required) <= set(value), 'missing required field')


def validate_request(request):
    finite_tree(request)
    require(len(json.dumps(request, ensure_ascii=False).encode('utf-8')) <= 1048576,
            'request exceeds 1 MiB')
    fields(request, ('boxes', 'items', 'options'), ('boxes', 'items'))
    require(type(request['boxes']) is list and len(request['boxes']) <= 64, 'box type limit')
    require(type(request['items']) is list and len(request['items']) <= 256, 'item type limit')
    result = dict(boxes=[], items=[])
    options = request.get('options', {})
    fields(options, DEFAULT_OPTIONS)
    opts = dict(DEFAULT_OPTIONS)
    opts.update(options)
    require(opts['support_mode'] in ('full_base', 'geometric'), 'invalid support mode')
    for key, low, high, integer in [('angle_step', 1, 90, True), ('restarts', 1, 64, True),
            ('max_candidates', 1, 100000000, True), ('time_limit_ms', 1, 60000, False),
            ('seed', 0, 4294967295, True), ('gap', 0, 1000000, False),
            ('clearance', 0, 1000000, False)]:
        opts[key] = numeric(opts[key], low, high, integer)
    require(opts['support_mode'] != 'full_base' or 'clearance' not in options,
            'clearance is geometric-only, including zero')
    require(opts['support_mode'] != 'geometric' or opts['gap'] == 0,
            'geometric mode requires gap zero')
    for category in ('boxes', 'items'):
        ids = set()
        for source in request[category]:
            extra = ('max_weight', 'cost') if category == 'boxes' else ('weight', 'rotation', 'diagonal')
            fields(source, ('id', *DIMENSIONS, 'quantity', *extra), ('id', *DIMENSIONS))
            item = dict(id=identity(source['id']))
            require(item['id'] not in ids, 'duplicate type id'); ids.add(item['id'])
            item.update({k: numeric(source[k], 1e-4, 1e6) for k in DIMENSIONS})
            if category == 'boxes':
                item.update(max_weight=numeric(source.get('max_weight', 1e12), 0, 1e12),
                            cost=numeric(source.get('cost', 1), 0, 1e12),
                            quantity=numeric(source.get('quantity', -1), -1, 256, True))
            else:
                item.update(weight=numeric(source.get('weight', 0), 0, 1e12),
                            quantity=numeric(source.get('quantity', 1), 1, 256, True),
                            rotation=source.get('rotation', 'flat'), diagonal=source.get('diagonal', True))
                require(item['rotation'] in ('none', 'flat', 'any', 'free3d'), 'invalid rotation')
                require(type(item['diagonal']) is bool, 'diagonal must be boolean')
                require(item['rotation'] != 'free3d' or
                        (opts['support_mode'] == 'geometric' and item['diagonal']),
                        'free3d requires geometric mode and diagonal true')
            result[category].append(item)
    require(sum(x['quantity'] for x in result['items']) <= 256, 'expanded instance limit')
    result['options'] = opts
    return result


def _same(actual, expected):
    require(numeric(actual) == float(expected), 'copied input metadata differs')


def _decimal(value):
    return Decimal.from_float(float(value))


def _close(actual, expected, terms):
    actual = numeric(actual, 0)
    # Bound for binary64 sums/products/divisions, never a geometric tolerance.
    allowance = Decimal(2)*(terms+2)*Decimal(2)**-52*max(abs(expected), abs(_decimal(actual)))
    require(abs(_decimal(actual)-expected) <= allowance, 'inconsistent aggregate statistic')


def _orientation(placement, source):
    q = placement['orientation']
    require(type(q) is list and len(q) == 4, 'orientation needs four components')
    for component in q: numeric(component)
    norm2 = sum(_decimal(x)**2 for x in q)
    require(abs(norm2-1) <= Decimal('1e-12'), 'quaternion squared norm error')
    first = next((x for x in (q[3], q[0], q[1], q[2]) if x != 0), 0)
    require(first > 0, 'quaternion sign is not canonical')
    # Rotate unit basis vectors using normalized quaternion, in Decimal60.
    norm = norm2.sqrt(); x, y, z, w = [_decimal(a)/norm for a in q]
    columns = ((1-2*(y*y+z*z), 2*(x*y+z*w), 2*(x*z-y*w)),
               (2*(x*y-z*w), 1-2*(x*x+z*z), 2*(y*z+x*w)),
               (2*(x*z+y*w), 2*(y*z-x*w), 1-2*(x*x+y*y)))
    near = lambda a, b: abs(a-b) <= ORIENTATION_ERROR
    vertical = lambda col: near(col[0], 0) and near(col[1], 0) and near(abs(col[2]), 1)
    mode = source['rotation']
    if mode == 'none':
        require(all(near(columns[j][k], int(j == k)) for j in range(3) for k in range(3)),
                'none must preserve original axes')
    elif mode == 'flat':
        require(vertical(columns[2]) and columns[2][2] > 0, 'flat requires original positive Z and yaw')
    elif mode == 'any':
        require(any(vertical(col) for col in columns), 'any requires one original face horizontal')
    if not source['diagonal']:
        require(all(sum(near(abs(x), 1) for x in col) == 1 and
                    all(near(x, 0) or near(abs(x), 1) for x in col) for col in columns),
                'diagonal false requires orthogonal axes')


def validate_result(request, result, diagnostics=False):
    """Raise ValueError on invalid output; return the complete lexicographic score."""
    token = _SCOPE.set('/' if diagnostics else None)
    try:
        with localcontext() as ctx:
            ctx.prec = 60
            return _validate_result(validate_request(request), result)
    finally:
        _SCOPE.reset(token)


def _validate_result(request, result):
    finite_tree(result)
    require(request['options']['support_mode'] == 'geometric', 'schema 2 is geometric-only')
    require(type(result) is dict, 'result must be object')
    required = {'version', 'schema_version', 'support_mode', 'clearance', 'status', 'bins', 'unpacked', 'stats'}
    require(required <= set(result), 'missing result fields')
    require(type(result['version']) is str and bool(result['version']), 'missing version/provenance')
    if 'provenance' in result:
        require(result['provenance'] == 'witness', 'unknown preparation provenance')
    require(numeric(result['schema_version'], 2, 2, True) == 2 and result['support_mode'] == 'geometric',
            'not geometric schema 2')
    _same(result['clearance'], request['options']['clearance'])
    require(type(result['bins']) is list and len(result['bins']) <= 256, 'invalid bins')
    require(type(result['unpacked']) is list, 'invalid unpacked')
    expected = {(i['id'], n): i for i in request['items'] for n in range(i['quantity'])}
    seen, bin_ids, stock = set(), set(), Counter()
    boxes = {b['id']: b for b in request['boxes']}
    total_cost, box_volume, item_volume = Decimal(0), Decimal(0), Decimal(0)

    def consume(item):
        require(type(item) is dict and {'id', 'instance'} <= set(item), 'invalid item identity')
        key = (identity(item['id']), numeric(item['instance'], 0, 255, True))
        require(key in expected and key not in seen, 'unknown/duplicate instance')
        seen.add(key)
        return expected[key]

    for box_index, bin_value in enumerate(result['bins']):
        _locate(f'/bins/{box_index}')
        require(type(bin_value) is dict and {'id', 'type_id', *DIMENSIONS, 'max_weight', 'cost', 'weight', 'items'} <= set(bin_value),
                'missing bin fields')
        bid = identity(bin_value['id']); require(bid not in bin_ids, 'duplicate bin id'); bin_ids.add(bid)
        require(type(bin_value['type_id']) is str and bin_value['type_id'] in boxes, 'unknown box type')
        box = boxes[bin_value['type_id']]
        stock[box['id']] += 1
        require(box['quantity'] == -1 or stock[box['id']] <= box['quantity'], 'stock exceeded')
        for k in (*DIMENSIONS, 'max_weight', 'cost'): _same(bin_value[k], box[k])
        items = bin_value['items']; require(type(items) is list and 0 < len(items) <= 256, 'empty/invalid bin')
        weight = Decimal(0)
        for item_index, placement in enumerate(items):
            _locate(f'/bins/{box_index}/items/{item_index}')
            source = consume(placement)
            require({*DIMENSIONS, 'weight', 'center', 'orientation'} <= set(placement), 'missing placement fields')
            require(not {'x', 'y', 'z', 'angle'} & set(placement), 'ambiguous old pose fields')
            for k in (*DIMENSIONS, 'weight'): _same(placement[k], source[k])
            require(type(placement['center']) is list and len(placement['center']) == 3, 'center needs three components')
            for x in placement['center']: numeric(x)
            _orientation(placement, source)
            require(ORACLE.inside(placement, [box[k] for k in DIMENSIONS], request['options']['clearance']),
                    'wall containment/clearance violated')
            weight += _decimal(source['weight'])
            item_volume += math.prod(_decimal(source[k]) for k in DIMENSIONS)
        _locate(f'/bins/{box_index}')
        allowance = Decimal(2)*(len(items)+2)*Decimal(2)**-52*max(weight, _decimal(box['max_weight']))
        require(weight <= _decimal(box['max_weight']) or
                (box['max_weight'] > 0 and weight-_decimal(box['max_weight']) <= allowance),
                'weight capacity exceeded')
        _close(bin_value['weight'], weight, len(items))
        for i, a in enumerate(items):
            for j, b in enumerate(items[i+1:], i+1):
                _locate(f'/bins/{box_index}/items/{i} (with /bins/{box_index}/items/{j})')
                require(not ORACLE.intersects(a, b, request['options']['clearance']), 'item intersection/clearance violated')
        total_cost += _decimal(box['cost'])
        box_volume += math.prod(_decimal(box[k]) for k in DIMENSIONS)
    for unpacked_index, item in enumerate(result['unpacked']):
        _locate(f'/unpacked/{unpacked_index}')
        consume(item)
    _locate('/')
    require(seen == set(expected), 'missing instances')
    require(result['status'] == ('partial' if result['unpacked'] else 'complete'), 'status inconsistent')
    stats = result['stats']
    _locate('/stats')
    require(type(stats) is dict and {'elapsed_ms', 'candidates', 'restarts', 'box_count', 'total_cost', 'utilization',
            'timed_out', 'budget_exhausted'} <= set(stats), 'missing statistics')
    elapsed = numeric(stats['elapsed_ms'], 0)
    candidates = numeric(stats['candidates'], 0, request['options']['max_candidates'], True)
    numeric(stats['restarts'], 0, request['options']['restarts'], True)
    require(numeric(stats['box_count'], 0, 256, True) == len(result['bins']), 'box count mismatch')
    for flag in ('timed_out', 'budget_exhausted'): require(type(stats[flag]) is bool, 'stop flag must be boolean')
    require(not stats['timed_out'] or elapsed >= request['options']['time_limit_ms'], 'time stop before budget')
    require(not stats['budget_exhausted'] or candidates == request['options']['max_candidates'],
            'candidate stop before budget')
    _close(stats['total_cost'], total_cost, len(result['bins']))
    _close(stats['utilization'], item_volume/box_volume if box_volume else Decimal(0), 3*len(seen)+len(result['bins']))
    if 'seed' in stats: require(numeric(stats['seed'], 0, 4294967295, True) == request['options']['seed'], 'seed mismatch')
    if 'options' in stats:
        require(type(stats['options']) is dict, 'effective options must be object')
        for key, value in request['options'].items():
            require(key in stats['options'], 'missing effective option')
            if type(value) in (int, float): _same(stats['options'][key], value)
            else: require(type(stats['options'][key]) is type(value) and stats['options'][key] == value,
                          'effective options mismatch')
    if 'stop_reason' in stats:
        require(type(stats['stop_reason']) is str and bool(stats['stop_reason']), 'invalid stop reason')
        if stats['stop_reason'] in ('time_limit', 'candidate_limit', 'completed', 'search_exhausted', 'witness'):
            require(stats['timed_out'] == (stats['stop_reason'] == 'time_limit') and
                    stats['budget_exhausted'] == (stats['stop_reason'] == 'candidate_limit'), 'stop reason mismatch')
    return (len(result['unpacked']), float(total_cost), len(result['bins']), float(box_volume))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    try:
        score = validate_result(load_request(args.request.read_bytes().decode('utf-8')),
                                loads(args.result.read_text(encoding='utf-8')))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(dict(valid=True, score=score)))


if __name__ == '__main__':
    main()

