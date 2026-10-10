"""Actual MCP 2.3 stdio sessions and structured/image failure contracts."""
import asyncio
import base64
from copy import deepcopy
import importlib.util
import json
import os
import shutil
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
sys.path.insert(0, str(ROOT / 'tests'))
from test_python_adapter import REQUEST, BINARY
from test_render import png_dimensions


@unittest.skipUnless(all(importlib.util.find_spec(name) is not None for name in ('mcp', 'playwright', 'jsonschema')),
                     'Install packer-adapter[mcp,images] for MCP integration tests')
class MCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('packer_adapter.mcp_server'), 'MCP tools are not implemented')

    async def test_real_stdio_discovery_closed_schemas_packing_and_pngs(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'python'), PACKER_BINARY=str(BINARY))
        params = StdioServerParameters(command=sys.executable, args=['-m', 'packer_adapter.mcp_server'], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                self.assertEqual('paCker', initialized.server_info.name)
                tools = (await session.list_tools()).tools
                self.assertEqual({'get_capabilities', 'pack_order', 'validate_packing', 'render_packing'}, {t.name for t in tools})

                def closed(node):
                    if isinstance(node, dict):
                        if node.get('type') == 'object':
                            self.assertIs(node.get('additionalProperties'), False)
                        for value in node.values(): closed(value)
                    elif isinstance(node, list):
                        for value in node: closed(value)
                for tool in tools:
                    closed(tool.input_schema)
                    self.assertIsNotNone(tool.output_schema)
                caps = await session.call_tool('get_capabilities', {})
                self.assertFalse(caps.is_error)
                self.assertEqual([1, 2], caps.structured_content['engine']['schemas'])
                ordinary = await session.call_tool('pack_order', {'request': REQUEST})
                self.assertFalse(ordinary.is_error, ordinary.content)
                data = ordinary.structured_content
                self.assertEqual('complete', data['packing']['status'])
                self.assertTrue(data['validation']['valid'])
                self.assertEqual('not_requested', data['rendering']['status'])
                self.assertFalse(any(block.type == 'image' for block in ordinary.content))
                self.assertEqual({'solver_ms', 'validation_ms', 'render_ms', 'total_ms'}, set(data['timings']))
                invalid = deepcopy(data['packing'])
                invalid['bins'][0]['items'][0]['x'] = 100
                checked = await session.call_tool('validate_packing', {'request': REQUEST, 'result': invalid})
                self.assertTrue(checked.is_error)
                self.assertEqual('invalid_result', checked.structured_content['error']['code'])
                self.assertIn('/bins/0/items/0', str(checked.structured_content['validation']['violations']))
                rendered = await session.call_tool('render_packing', {'request': REQUEST, 'result': data['packing'],
                                                                      'box_ids': ['bin-1'], 'view': 'top'})
                self.assertFalse(rendered.is_error, rendered.content)
                images = [block for block in rendered.content if block.type == 'image']
                self.assertEqual(1, len(images))
                png = base64.b64decode(images[0].data, validate=True)
                self.assertEqual((1024, 768), png_dimensions(png))
                self.assertEqual('top', rendered.structured_content['rendering']['images'][0]['view'])
                self.assertEqual('bin-1', rendered.structured_content['rendering']['images'][0]['box_id'])
                artifacts = Path(os.environ.get('PACKER_MCP_ARTIFACTS', ROOT / 'build' / 'mcp-tests'))
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / 'ordinary-top.png').write_bytes(png)
                (artifacts / 'ordinary.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
                geometric_request = deepcopy(REQUEST)
                geometric_request['options']['support_mode'] = 'geometric'
                geometric_request['items'][0]['rotation'] = 'free3d'
                geometric = await session.call_tool('pack_order', {'request': geometric_request, 'include_image': True})
                self.assertFalse(geometric.is_error, geometric.content)
                self.assertEqual(2, geometric.structured_content['packing']['schema_version'])
                self.assertEqual(1, len([block for block in geometric.content if block.type == 'image']))
                (artifacts / 'geometric.json').write_text(json.dumps(geometric.structured_content, indent=2), encoding='utf-8')
                partial_request = deepcopy(REQUEST)
                partial_request['boxes'] = []
                partial = await session.call_tool('pack_order', {'request': partial_request})
                self.assertFalse(partial.is_error)
                self.assertEqual('partial', partial.structured_content['packing']['status'])
                for args in ({'request': REQUEST, 'unknown': 1}, {'request': {'items': []}},
                             {'request': REQUEST, 'include_image': 'true'},
                             {'request': REQUEST, 'box_ids': ['unknown']}):
                    bad = await session.call_tool('pack_order', args)
                    self.assertTrue(bad.is_error, args)
                    self.assertEqual('invalid_input', bad.structured_content['error']['code'])

    async def test_render_failure_keeps_original_numeric_packing(self):
        from packer_adapter.mcp_server import Adapter
        from packer_adapter.render import PackerRenderer
        async def absent(_):
            raise ModuleNotFoundError('Chromium absent')
        async with Adapter(BINARY) as adapter:
            plain = await adapter.call('pack_order', {'request': REQUEST})
            packing = plain.structured_content['packing']
            with patch.object(PackerRenderer, 'start', absent):
                response = await adapter.call('render_packing', {'request': REQUEST, 'result': packing})
            self.assertEqual(packing, response.structured_content['packing'])
            self.assertEqual('render_error', response.structured_content['error']['code'])
            self.assertTrue(response.structured_content['validation']['valid'])
            self.assertFalse(any(block.type == 'image' for block in response.content))

    async def test_validation_boundary_errors_fail_packing_and_renderer(self):
        from packer_adapter.mcp_server import Adapter
        from packer_adapter.models import AdapterError
        async with Adapter(BINARY) as adapter:
            packing = (await adapter.call('pack_order', {'request': REQUEST})).structured_content['packing']
            async def failed(*_):
                raise AdapterError('validation_timeout', 'Validation timed out')
            adapter.validator.validate = failed
            for name, args in [('pack_order', {'request': REQUEST, 'include_image': True}),
                               ('render_packing', {'request': REQUEST, 'result': packing})]:
                response = await adapter.call(name, args)
                self.assertTrue(response.is_error)
                self.assertEqual('validation_timeout', response.structured_content['error']['code'])
                self.assertEqual('error', response.structured_content['validation']['status'])
                self.assertIsNone(adapter.renderer.browser)

    async def test_renderer_revalidation_uses_worker_and_lifespan_closes_browser(self):
        from packer_adapter.mcp_server import Adapter
        adapter = Adapter(BINARY)
        with patch('packer_adapter.render.validate', side_effect=AssertionError('sync validation bypass')):
            async with adapter:
                result = await adapter.call('pack_order', {'request': REQUEST, 'include_image': True})
                self.assertFalse(result.is_error, result.content)
                self.assertIsNotNone(adapter.renderer.browser)
        self.assertIsNone(adapter.renderer.browser)
        self.assertIsNone(adapter.renderer._playwright)

    async def test_anyio_render_cancellation_closes_context_and_lifespan(self):
        import anyio
        from playwright.async_api import Page
        from packer_adapter.engine import Engine
        from packer_adapter.render import PackerRenderer
        packing = await Engine(BINARY).pack(REQUEST)
        entered = asyncio.Event()

        async def held_goto(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async with PackerRenderer() as renderer:
            await renderer.start()
            browser = renderer.browser
            with patch.object(Page, 'goto', held_goto):
                # Cancel after the context reaches navigation, also on slower hosts.
                with anyio.move_on_after(5) as scope:
                    async def cancel_at_navigation():
                        await entered.wait()
                        scope.cancel()
                    canceller = asyncio.create_task(cancel_at_navigation())
                    try:
                        await renderer.render(REQUEST, packing)
                    finally:
                        canceller.cancel()
                await asyncio.gather(canceller, return_exceptions=True)
            self.assertTrue(entered.is_set(), 'Cancellation must interrupt an actual scene context')
            self.assertTrue(scope.cancel_called)
            self.assertEqual([], browser.contexts, 'Cancelled MCP render leaked a browser context')
            # Server shutdown can run inside the same already-cancelled AnyIO scope.
            with anyio.CancelScope() as shutdown:
                shutdown.cancel()
                await renderer.close()
            self.assertFalse(browser.is_connected())
            self.assertIsNone(renderer._playwright)

    async def test_actual_stdio_without_chromium_retains_verified_data(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as empty_browsers:
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'python'), PACKER_BINARY=str(BINARY),
                       PLAYWRIGHT_BROWSERS_PATH=empty_browsers)
            params = StdioServerParameters(command=sys.executable, args=['-m', 'packer_adapter.mcp_server'], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    caps = await session.call_tool('get_capabilities', {})
                    self.assertFalse(caps.structured_content['renderer']['available'])
                    result = await session.call_tool('pack_order', {'request': REQUEST, 'include_image': True})
                    self.assertTrue(result.is_error)
                    self.assertEqual('render_error', result.structured_content['error']['code'])
                    self.assertTrue(result.structured_content['validation']['valid'])
                    self.assertEqual('complete', result.structured_content['packing']['status'])

    async def test_php_and_mcp_keep_identical_packing_without_time_stop(self):
        from packer_adapter.mcp_server import Adapter
        php = os.environ.get('PACKER_PHP')
        if not php:
            php = ROOT / '.tools' / 'php' / 'php.exe' if sys.platform == 'win32' else 'php'
        if not shutil.which(str(php)):
            self.skipTest('PHP is optional; set PACKER_PHP to run facade parity checks')
        script = '''<?php
require $argv[1];
$r = json_decode(stream_get_contents(STDIN), true, 32, JSON_THROW_ON_ERROR);
$p = new paCker\\Packer($argv[2]);
foreach ($r['boxes'] as $b) $p->addBox($b);
foreach ($r['items'] as $i) $p->addItem($i, (int)($i['quantity'] ?? 1));
$p->setOptions($r['options']);
echo json_encode($p->pack(), JSON_THROW_ON_ERROR);
'''
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'compare.php'
            file.write_text(script, encoding='utf-8')
            for geometric in (False, True):
                request = deepcopy(REQUEST)
                request['items'][0]['quantity'] = 2
                if geometric:
                    request['options']['support_mode'] = 'geometric'
                    request['items'][0]['rotation'] = 'free3d'
                php_result = json.loads(subprocess.run([str(php), '-n', str(file), str(ROOT / 'php/src/Packer.php'), str(BINARY)],
                    input=json.dumps(request), text=True, capture_output=True, check=True).stdout)
                async with Adapter(BINARY) as adapter:
                    mcp_result = (await adapter.call('pack_order', {'request': request})).structured_content['packing']
                self.assertFalse(mcp_result['stats']['timed_out'])
                for result in (php_result, mcp_result):
                    result['stats'].pop('elapsed_ms', None)
                    result['stats'].pop('xy_elapsed_ms', None)
                self.assertEqual(php_result, mcp_result)


if __name__ == '__main__':
    unittest.main()
