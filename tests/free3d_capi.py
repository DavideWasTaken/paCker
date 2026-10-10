"""ctypes binding of the geometric C API (op3_pack) used by the tests.

Pass an already-built library to Adapter. Python JSON preserves binary64 round
trips. Verification is deliberately outside pack().
"""
import ctypes as C
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from packer_adapter import validation_3d as verify  # noqa: E402


class Pose(C.Structure):
    _fields_ = [(s, C.c_double) for s in ('width', 'length', 'height')] + [('center', C.c_double * 3), ('orientation', C.c_double * 4)]


class Item(C.Structure):
    _fields_ = [('id', C.c_char * 64)] + [(s, C.c_double) for s in ('width', 'length', 'height', 'weight')] + [(s, C.c_int) for s in ('instance', 'rotation', 'diagonal')]


class Box(C.Structure):
    _fields_ = [('id', C.c_char * 64)] + [(s, C.c_double) for s in ('width', 'length', 'height', 'max_weight', 'cost')] + [('quantity', C.c_int)]


class Options(C.Structure):
    _fields_ = [(s, C.c_double) for s in ('angle_step', 'time_limit_ms', 'clearance')] + [('max_candidates', C.c_uint64), ('seed', C.c_uint), ('restarts', C.c_int)]


class Request(C.Structure):
    _fields_ = [('items', Item * 256), ('boxes', Box * 64), ('item_count', C.c_int), ('box_count', C.c_int), ('options', Options)]


class Placement(C.Structure):
    _fields_ = [('item_index', C.c_int), ('bin_index', C.c_int), ('pose', Pose)]


class Bin(C.Structure):
    _fields_ = [('box_index', C.c_int), ('weight', C.c_double)]


class Result(C.Structure):
    _fields_ = [('placements', Placement * 256), ('bins', Bin * 256), ('unpacked', C.c_int * 256)] + [(s, C.c_int) for s in ('placement_count', 'bin_count', 'unpacked_count')] + [(s, C.c_double) for s in ('total_cost', 'utilization', 'elapsed_ms')] + [('candidates', C.c_uint64)] + [(s, C.c_int) for s in ('restarts', 'timed_out', 'budget_exhausted', 'stop_reason')] + [('xy_candidates', C.c_uint64), ('xy_elapsed_ms', C.c_double)]


ROTATIONS = dict(none=0, flat=1, any=2, free3d=3)
REASONS = ['search_exhausted', 'completed', 'time_limit', 'candidate_limit']


def request_to_c(request):
    normalized = verify.validate_request(request)
    out = Request()
    options = normalized['options']
    if options['support_mode'] != 'geometric':
        raise ValueError('C API adapter supports geometric mode only')
    out.options = Options(*(options[k] for k in ('angle_step', 'time_limit_ms', 'clearance', 'max_candidates', 'seed', 'restarts')))
    for product in normalized['items']:
        for instance in range(product['quantity']):
            out.items[out.item_count] = Item(product['id'].encode(), *(product[k] for k in ('width', 'length', 'height', 'weight')), instance, ROTATIONS[product['rotation']], product['diagonal'])
            out.item_count += 1
    for i, box in enumerate(normalized['boxes']):
        out.boxes[i] = Box(box['id'].encode(), *(box[k] for k in ('width', 'length', 'height', 'max_weight', 'cost', 'quantity')))
    out.box_count = len(normalized['boxes'])
    return normalized, out


def _validate_result_struct(request, result):
    """Check interchange integrity, without replacing independent geometry QA.

    Validate before any indexing, slicing or boolean coercion: Python negative
    indices and truncated ctypes slices must never conceal a malformed C result.
    No field is repaired or recomputed here.
    """
    def require(condition, message):
        if not condition:
            raise ValueError('invalid C result: ' + message)

    def integer(value, low, high, field):
        require(type(value) is int and low <= value <= high, field + ' outside bounds')

    def finite(value, field, nonnegative=False):
        require(math.isfinite(value) and (not nonnegative or value >= 0), field + ' is nonfinite or negative')

    integer(result.placement_count, 0, request.item_count, 'placement_count')
    integer(result.unpacked_count, 0, request.item_count, 'unpacked_count')
    integer(result.bin_count, 0, result.placement_count, 'bin_count')
    require(result.placement_count + result.unpacked_count == request.item_count, 'inconsistent instance counts')
    integer(result.stop_reason, 0, len(REASONS)-1, 'stop_reason')
    for field in ('timed_out', 'budget_exhausted'):
        integer(getattr(result, field), 0, 1, field)
    require(result.timed_out == (result.stop_reason == 2) and
            result.budget_exhausted == (result.stop_reason == 3), 'stop reason/flag mismatch')
    if result.stop_reason in (0, 1):
        require((result.stop_reason == 1) == (result.unpacked_count == 0), 'completion reason/count mismatch')
    integer(result.candidates, 0, request.options.max_candidates, 'candidates')
    integer(result.xy_candidates, 0, result.candidates, 'xy_candidates')
    integer(result.restarts, 0, request.options.restarts, 'restarts')
    for field in ('total_cost', 'utilization', 'elapsed_ms', 'xy_elapsed_ms'):
        finite(getattr(result, field), field, nonnegative=True)
    require(result.xy_elapsed_ms <= result.elapsed_ms, 'XY time exceeds global time')
    require(not result.timed_out or result.elapsed_ms >= request.options.time_limit_ms, 'time stop before limit')
    require(not result.budget_exhausted or result.candidates == request.options.max_candidates, 'candidate stop before limit')

    for i in range(result.bin_count):
        integer(result.bins[i].box_index, 0, request.box_count-1, 'box_index')
        finite(result.bins[i].weight, 'bin weight', nonnegative=True)
    seen, used_bins = set(), set()
    for i in range(result.placement_count):
        p = result.placements[i]
        integer(p.item_index, 0, request.item_count-1, 'item_index')
        integer(p.bin_index, 0, result.bin_count-1, 'bin_index')
        require(p.item_index not in seen, 'duplicate item index')
        seen.add(p.item_index)
        used_bins.add(p.bin_index)
        original = request.items[p.item_index]
        for field in ('width', 'length', 'height'):
            require(getattr(p.pose, field) == getattr(original, field), 'returned pose ' + field + ' differs from original')
        for field in ('center', 'orientation'):
            for value in getattr(p.pose, field):
                finite(value, field)
    for i in range(result.unpacked_count):
        index = result.unpacked[i]
        integer(index, 0, request.item_count-1, 'unpacked index')
        require(index not in seen, 'duplicate packed/unpacked item index')
        seen.add(index)
    require(len(seen) == request.item_count, 'missing item indices')
    require(len(used_bins) == result.bin_count, 'empty bin')


def result_to_json(normalized, request, result, version='0.3.3-free3d-dev'):
    _validate_result_struct(request, result)
    bins = []
    for i in range(result.bin_count):
        box = normalized['boxes'][result.bins[i].box_index]
        bins.append(dict(id=f'bin-{i}', type_id=box['id'], **{k: box[k] for k in ('width', 'length', 'height', 'max_weight', 'cost')}, weight=result.bins[i].weight, items=[]))
    for p in result.placements[:result.placement_count]:
        item = request.items[p.item_index]
        bins[p.bin_index]['items'].append(dict(id=item.id.decode(), instance=item.instance, **{k: getattr(p.pose, k) for k in ('width', 'length', 'height')}, weight=item.weight, center=list(p.pose.center), orientation=list(p.pose.orientation)))
    unpacked = [dict(id=request.items[i].id.decode(), instance=request.items[i].instance) for i in result.unpacked[:result.unpacked_count]]
    stats = {k: getattr(result, k) for k in ('elapsed_ms', 'candidates', 'restarts', 'total_cost', 'utilization', 'xy_candidates', 'xy_elapsed_ms')}
    stats.update(box_count=result.bin_count, timed_out=bool(result.timed_out), budget_exhausted=bool(result.budget_exhausted), seed=request.options.seed, options=normalized['options'], stop_reason=REASONS[result.stop_reason])
    return dict(version=version, schema_version=2, support_mode='geometric', clearance=request.options.clearance, status='partial' if unpacked else 'complete', bins=bins, unpacked=unpacked, stats=stats)


class Adapter:
    def __init__(self, library):
        self.lib = C.CDLL(str(Path(library).resolve()))
        self.lib.op3_version.argtypes = []
        self.lib.op3_version.restype = C.c_char_p
        self.version = self.lib.op3_version().decode('utf-8')
        self.lib.op3_default_options.argtypes = [C.POINTER(Options)]
        self.lib.op3_pack.argtypes = [C.POINTER(Request), C.POINTER(Result), C.c_char_p, C.c_int]
        self.lib.op3_pack.restype = C.c_int

    def pack(self, request):
        normalized, crequest = request_to_c(request)
        result, error = Result(), C.create_string_buffer(256)
        rc = self.lib.op3_pack(C.byref(crequest), C.byref(result), error, len(error))
        if rc:
            raise ValueError(error.value.decode('utf-8', errors='replace'))
        return result_to_json(normalized, crequest, result, self.version)
