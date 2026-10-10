"""Thin adapter bounds, request fidelity, and process cleanup."""
import asyncio
from copy import deepcopy
import json
import os
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
PYTHON = sys.executable
BINARY = Path(os.environ.get('OP_BINARY',str(ROOT / 'build' / ('packer.exe' if sys.platform == 'win32' else 'packer'))))
REQUEST = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
           'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}],
           'options': {'max_candidates': 100, 'seed': 42}}
HAS_ADAPTER = all(importlib.util.find_spec(name) is not None for name in ('jsonschema', 'pydantic', 'anyio'))


@unittest.skipUnless(HAS_ADAPTER, 'Install packer-adapter[mcp] for adapter tests')
class RequestTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('packer_adapter.models'), 'request boundary is not implemented')

    def test_request_is_preserved_and_cli_capabilities_are_explicit(self):
        from packer_adapter.models import check_request
        self.assertEqual(REQUEST, check_request(deepcopy(REQUEST)))
        result = subprocess.run([str(BINARY), '--capabilities'], capture_output=True, check=True)
        caps = json.loads(result.stdout)
        self.assertEqual([1, 2], caps['schemas'])
        self.assertEqual(['contact', 'full_base', 'geometric'], caps['support_modes'])
        self.assertEqual(256, caps['limits']['expanded_items'])

    def test_rejects_missing_unknown_nonfinite_and_cross_field_values(self):
        from packer_adapter.models import check_request, AdapterError
        changes = [lambda r: r['items'][0].pop('width'),
                   lambda r: r['items'][0].update(width=True),
                   lambda r: r['items'][0].update(width=float('nan')),
                   lambda r: r['items'][0].update(id='é'*32),
                   lambda r: r['items'][0].update(quantity=257),
                   lambda r: r['items'].extend([dict(r['items'][0])]),
                   lambda r: r['items'][0].update(rotation='free3d'),
                   lambda r: r['options'].update(clearance=1),
                   lambda r: r.update(command='echo hello'),
                   lambda r: r['options'].update(support_mode='geometric', gap=1),
                   lambda r: (r['options'].update(support_mode='geometric'),
                              r['items'][0].update(rotation='free3d', diagonal=False))]
        for change in changes:
            request = deepcopy(REQUEST)
            change(request)
            with self.subTest(request=request), self.assertRaises(AdapterError) as error:
                check_request(request)
            self.assertEqual('invalid_input', error.exception.code)
        request = deepcopy(REQUEST)
        request['items'] = [dict(request['items'][0], id='A', quantity=200),
                            dict(request['items'][0], id='C', quantity=100)]
        with self.assertRaises(AdapterError):
            check_request(request)

    def test_integral_cli_numbers_are_accepted_without_coercing_request(self):
        from packer_adapter.models import check_request
        request = deepcopy(REQUEST)
        request['items'][0]['quantity'] = 1.0
        self.assertEqual(request, check_request(request))

    def test_depth_byte_numeric_utf8_limits_and_box_selection(self):
        from packer_adapter.models import json_bytes, check_request, selected_boxes, AdapterError
        nested = []
        for _ in range(18):
            nested = [nested]
        for value in (nested, {'s': 'x'*1048577}, {'s': '\ud800'}, {'n': 10**1000}, {'s': '\0'}):
            with self.assertRaises(AdapterError):
                json_bytes(value, 1048576, 16)
        result = {'bins': [{'id': 'bin-1'}, {'id': 'bin-2'}]}
        self.assertEqual([1], selected_boxes(result, box_ids=['bin-2']))
        for indexes, ids in (([True], None), ([2], None), ([0, 0], None), ([0], ['bin-1']), (None, ['missing'])):
            with self.assertRaises(AdapterError):
                selected_boxes(result, indexes, ids)

    def test_detailed_geometric_violation_has_item_location(self):
        from packer_adapter.validation import validate
        request = deepcopy(REQUEST)
        request['options']['support_mode'] = 'geometric'
        result = json.loads(subprocess.run([str(BINARY)], input=json.dumps(request), text=True,
                                          capture_output=True, check=True).stdout)
        result['bins'][0]['items'][0]['center'][0] = 100
        self.assertIn('/bins/0/items/0', validate(request, result, diagnostics=True)[0])


@unittest.skipUnless(HAS_ADAPTER, 'Install packer-adapter[mcp] for adapter tests')
class ProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('packer_adapter.engine'), 'process boundary is not implemented')

    async def test_real_engine_and_independent_worker_preserve_packing(self):
        from packer_adapter.engine import Engine, Validator
        engine = Engine(BINARY)
        self.assertEqual([1, 2], (await engine.capabilities())['schemas'])
        result = await engine.pack(REQUEST)
        self.assertEqual('complete', result['status'])
        self.assertEqual([], await Validator().validate(REQUEST, result))
        result['bins'][0]['items'][0]['x'] = 100
        self.assertTrue(await Validator().validate(REQUEST, result))

    async def test_timeout_output_stderr_exit_and_invalid_json(self):
        from packer_adapter.engine import run_process, decode_object
        from packer_adapter.models import AdapterError
        for script, kwargs, code in [
            ('import time; time.sleep(30)', {'timeout': .1}, 'process_timeout'),
            ('import sys; sys.stdout.write("x"*100000)', {'stdout_limit': 32}, 'output_limit'),
            ('import sys; sys.stderr.write("x"*100000)', {'stderr_limit': 32}, 'stderr_limit'),
            ('import sys; sys.exit(7)', {}, 'process_exit')]:
            with self.subTest(code=code), self.assertRaises(AdapterError) as error:
                await run_process([PYTHON, '-c', script], b'', **kwargs)
            self.assertEqual(code, error.exception.code)
        for data in (b'[]', b'{"a":1,"a":2}', b'{"x":NaN}', b'not-json'):
            with self.assertRaises(AdapterError):
                decode_object(data)

    async def test_cancelled_process_is_reaped_and_loop_stays_responsive(self):
        from packer_adapter.engine import run_process
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'alive'
            script = 'import pathlib,time; time.sleep(.5); pathlib.Path(__import__("sys").argv[1]).write_text("alive")'
            task = asyncio.create_task(run_process([PYTHON, '-c', script, str(marker)], b''))
            await asyncio.sleep(.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(.6)
            self.assertFalse(marker.exists())

    async def test_validation_timeout_is_interruptible(self):
        from packer_adapter.engine import Validator
        from packer_adapter.models import AdapterError
        validator = Validator(timeout=.1, worker_command=(PYTHON, '-c', 'import time; time.sleep(30)'))
        with self.assertRaises(AdapterError) as error:
            await validator.validate(REQUEST, {})
        self.assertEqual('validation_timeout', error.exception.code)

    async def test_validation_worker_crash_and_bad_response_are_errors(self):
        from packer_adapter.engine import Validator
        from packer_adapter.models import AdapterError
        for script in ('raise RuntimeError("worker failed")', 'print("{}")', 'print("x"*1100000)'):
            with self.assertRaises(AdapterError) as error:
                await Validator(worker_command=(PYTHON, '-c', script)).validate(REQUEST, {})
            self.assertEqual('validation_error', error.exception.code)

    async def test_anyio_cancellation_reaps_validation_subprocess(self):
        import anyio
        from packer_adapter.engine import run_process
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'alive'
            script = 'import pathlib,time,sys; time.sleep(.5); pathlib.Path(sys.argv[1]).write_text("alive")'
            with anyio.move_on_after(.05) as scope:
                await run_process([PYTHON, '-c', script, str(marker)], b'')
            self.assertTrue(scope.cancel_called)
            await asyncio.sleep(.6)
            self.assertFalse(marker.exists())

    async def test_old_incompatible_binary_and_engine_bad_response_fail_closed(self):
        from packer_adapter.engine import Engine
        from packer_adapter.models import AdapterError
        with self.assertRaises(AdapterError) as error:
            await Engine(PYTHON).capabilities()
        self.assertEqual('incompatible_engine', error.exception.code)
        engine = Engine(BINARY)
        await engine.capabilities()
        for raw, code in ((b'not JSON', 'invalid_result'), (b'{"error":"failed"}', 'engine_error'),
                          (b'{"status":"complete"}', 'invalid_result')):
            async def response(*args, **kwargs):
                return raw
            with patch('packer_adapter.engine.run_process', response), self.assertRaises(AdapterError) as error:
                await engine.pack(REQUEST)
            self.assertEqual(code, error.exception.code)


if __name__ == '__main__':
    unittest.main()
