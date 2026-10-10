"""Closed wire schemas and lossless JSON boundaries for the CLI adapter."""
from copy import deepcopy
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

REQUEST_BYTES = 1024 * 1024
RESULT_BYTES = 4 * 1024 * 1024
STDERR_BYTES = 64 * 1024


class AdapterError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def json_bytes(value, limit, depth_limit=32, code='invalid_input'):
    """Reject non-JSON/oversized trees before serialization; do not coerce numbers."""
    stack = [(value, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if depth > depth_limit or nodes > limit:
            raise AdapterError(code, 'JSON nesting or node limit exceeded.')
        if node is None or type(node) is bool:
            continue
        if type(node) in (int, float):
            try:
                valid = math.isfinite(node)
            except OverflowError:
                valid = False
            if not valid:
                raise AdapterError(code, 'All numbers must be finite binary64 values.')
        elif type(node) is str:
            try:
                valid = '\0' not in node and len(node.encode('utf-8')) <= limit
            except UnicodeError:
                valid = False
            if not valid:
                raise AdapterError(code, 'Invalid UTF-8, NUL, or oversized string.')
        elif type(node) is list:
            if len(node) > limit:
                raise AdapterError(code, 'JSON array limit exceeded.')
            stack.extend((child, depth+1) for child in node)
        elif type(node) is dict:
            if len(node) > limit or any(type(key) is not str for key in node):
                raise AdapterError(code, 'JSON object keys must be strings within bounds.')
            stack.extend((child, depth+1) for pair in node.items() for child in pair)
        else:
            raise AdapterError(code, 'Expected JSON values without coercion.')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise AdapterError(code, 'Cannot encode bounded JSON.') from exc
    if len(encoded) > limit:
        raise AdapterError(code, f'JSON exceeds {limit} bytes.')
    return encoded


def _canonical(name):
    root = Path(__file__).resolve().parent / 'schemas'
    if not root.is_dir():
        root = Path(__file__).resolve().parents[2] / 'schemas'
    schema = json.loads((root / name).read_text(encoding='utf-8'))
    definitions = schema.pop('$defs')

    def expand(node):
        if isinstance(node, list):
            return [expand(child) for child in node]
        if not isinstance(node, dict):
            return node
        if '$ref' in node:
            return expand(deepcopy(definitions[node['$ref'].split('/')[-1]]))
        return {key: expand(child) for key, child in node.items() if key != '$schema'}
    return expand(schema)


GEOMETRIC_REQUEST = _canonical('request-v2.json')
ORDINARY_REQUEST = deepcopy(GEOMETRIC_REQUEST)
ORDINARY_REQUEST['required'] = ['boxes', 'items']
ORDINARY_REQUEST.pop('title', None)
ORDINARY_REQUEST.pop('description', None)
_ordinary_options = ORDINARY_REQUEST['properties']['options']
_ordinary_options['required'] = []
_ordinary_options['properties']['support_mode'] = {'enum': ['stable', 'contact', 'full_base'], 'default': 'stable'}
_ordinary_options['properties']['improve'] = {'type': 'boolean', 'default': False}
_ordinary_options['properties'].pop('clearance')
_ordinary_options['properties']['gap'] = {'type': 'number', 'minimum': 0, 'maximum': 1000000, 'default': 0}
_ordinary_item = ORDINARY_REQUEST['properties']['items']['items']
_ordinary_item.pop('allOf')
_ordinary_item['properties']['rotation']['enum'].remove('free3d')
REQUEST_SCHEMA = {'oneOf': [ORDINARY_REQUEST, GEOMETRIC_REQUEST]}

GEOMETRIC_RESULT = _canonical('result-v2.json')
ORDINARY_RESULT = deepcopy(GEOMETRIC_RESULT)
ORDINARY_RESULT.pop('title', None)
ORDINARY_RESULT.pop('description', None)
for _key in ('schema_version', 'clearance'):
    ORDINARY_RESULT['properties'].pop(_key)
    ORDINARY_RESULT['required'].remove(_key)
ORDINARY_RESULT['properties']['support_mode'] = {'enum': ['stable', 'contact', 'full_base']}
ORDINARY_RESULT['properties']['version'] = {'type': 'string', 'minLength': 1, 'maxLength': 128}
_placement = ORDINARY_RESULT['properties']['bins']['items']['properties']['items']['items']
for _key in ('center', 'orientation'):
    _placement['properties'].pop(_key)
    _placement['required'].remove(_key)
for _key in ('x', 'y', 'z', 'angle'):
    _placement['properties'][_key] = {'type': 'number'}
    _placement['required'].append(_key)
_stats = ORDINARY_RESULT['properties']['stats']
for _key in ('stop_reason', 'seed', 'xy_candidates', 'xy_elapsed_ms', 'options'):
    _stats['properties'].pop(_key)
    _stats['required'].remove(_key)
_stats['properties']['lower_bound'] = {'type': 'integer', 'minimum': 0, 'maximum': 257}
_stats['properties']['proven_optimal'] = {'type': 'boolean'}
RESULT_SCHEMA = {'oneOf': [ORDINARY_RESULT, GEOMETRIC_RESULT]}
_request_validator = Draft202012Validator(REQUEST_SCHEMA)
_result_validator = Draft202012Validator(RESULT_SCHEMA)


def _check_schema(validator, value, code):
    error = next(validator.iter_errors(value), None)
    if error:
        leaves = error.context or [error]
        detail = '; '.join(f'{"/".join(map(str, e.absolute_path)) or "root"}: {e.message[:180]}'
                           for e in leaves[:4])
        raise AdapterError(code, detail)


def check_request(request):
    json_bytes(request, REQUEST_BYTES, 16)
    _check_schema(_request_validator, request, 'invalid_input')
    for category in ('boxes', 'items'):
        identifiers = [row['id'] for row in request[category]]
        if len(set(identifiers)) != len(identifiers):
            raise AdapterError('invalid_input', f'Duplicate {category} identifiers.')
        if any(len(identity.encode('utf-8')) > 63 for identity in identifiers):
            raise AdapterError('invalid_input', 'Identifiers must contain 1..63 UTF-8 bytes.')
    if sum(row.get('quantity', 1) for row in request['items']) > 256:
        raise AdapterError('invalid_input', 'Limit exceeded: 256 expanded items.')
    return request


def check_result(result):
    json_bytes(result, RESULT_BYTES, 32, 'invalid_result')
    _check_schema(_result_validator, result, 'invalid_result')
    return result


def selected_boxes(result, box_indexes=None, box_ids=None):
    if box_indexes is not None and box_ids is not None:
        raise AdapterError('invalid_input', 'Select box_indexes or box_ids, not both.')
    if box_ids is not None:
        ids = [box['id'] for box in result['bins']]
        if any(identity not in ids for identity in box_ids):
            raise AdapterError('invalid_input', 'Unknown packed box ID.')
        box_indexes = [ids.index(identity) for identity in box_ids]
    indexes = list(range(len(result['bins']))) if box_indexes is None else box_indexes
    if (type(indexes) is not list or any(type(index) is not int or index < 0 or
            index >= len(result['bins']) for index in indexes) or len(set(indexes)) != len(indexes)):
        raise AdapterError('invalid_input', 'Invalid or duplicate packed box selection.')
    return indexes


class Envelope(BaseModel):
    """Numeric solver output is retained as a dictionary without model coercion."""
    model_config = ConfigDict(extra='forbid', strict=True)
    packing: dict | None = None
    validation: dict = Field(default_factory=dict)
    rendering: dict = Field(default_factory=dict)
    timings: dict = Field(default_factory=dict)
    error: dict | None = None


class Capabilities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    engine: dict
    renderer: dict
    adapter: dict
