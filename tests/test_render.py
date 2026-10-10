"""Independent validation and final-scene image contracts."""
import json
import asyncio
import builtins
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zlib

try:
    import playwright  # noqa: F401
except ImportError:
    raise unittest.SkipTest('install packer3d[images] and Chromium to run renderer tests')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
ARTIFACTS = Path(os.environ.get('PACKER_TEST_ARTIFACTS', ROOT / 'build' / 'render-tests'))
BINARY = Path(os.environ.get('OP_BINARY',str(ROOT / 'build' / ('packer.exe' if sys.platform == 'win32' else 'packer'))))


def solved(request):
    return json.loads(subprocess.run([str(BINARY)],
                                     input=json.dumps(request), text=True, capture_output=True, check=True).stdout)


def png_dimensions(png):
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        raise AssertionError('not a PNG')
    offset, image_data = 8, bytearray()
    while offset < len(png):
        length = int.from_bytes(png[offset:offset+4], 'big')
        kind = png[offset+4:offset+8]
        payload = png[offset+8:offset+8+length]
        crc = int.from_bytes(png[offset+8+length:offset+12+length], 'big')
        if zlib.crc32(kind+payload) & 0xffffffff != crc:
            raise AssertionError('invalid PNG CRC')
        if kind == b'IHDR':
            dimensions = (int.from_bytes(payload[:4], 'big'), int.from_bytes(payload[4:8], 'big'))
        if kind == b'IDAT':
            image_data.extend(payload)
        offset += length+12
        if kind == b'IEND':
            break
    if not zlib.decompress(image_data):
        raise AssertionError('empty image pixels')
    return dimensions


class ValidationDispatchTests(unittest.TestCase):
    def test_ordinary_dispatch_matches_existing_verifier(self):
        from packer_adapter.validation import validate
        sys.path.insert(0, str(ROOT / 'tests'))
        from validate_result import validate as existing
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}]}
        result = json.loads(subprocess.run([str(BINARY)],
                                           input=json.dumps(request), text=True, capture_output=True, check=True).stdout)
        self.assertEqual(validate(request, result), existing(request, result))
        result['bins'][0]['items'][0]['x'] = 100
        self.assertEqual(validate(request, result), existing(request, result))
        self.assertTrue(validate(request, result))

    def test_geometric_dispatch_matches_existing_verifier(self):
        from packer_adapter.validation import validate
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2, 'rotation': 'free3d'}],
                   'options': {'support_mode': 'geometric', 'clearance': 0, 'gap': 0}}
        result = json.loads(subprocess.run([str(BINARY)],
                                           input=json.dumps(request), text=True, capture_output=True, check=True).stdout)
        self.assertEqual(validate(request, result), [])
        result['bins'][0]['items'][0]['center'][0] = 100
        self.assertTrue(validate(request, result))


class RenderTests(unittest.TestCase):
    def test_cleanup_without_anyio_is_awaited_after_direct_cancellation(self):
        from packer_adapter.render import _cleanup
        real_import = builtins.__import__
        finished = []

        def without_anyio(name, *args, **kwargs):
            if name == 'anyio':
                raise ImportError('optional AnyIO is absent')
            return real_import(name, *args, **kwargs)

        async def close_resource():
            await asyncio.sleep(.05)
            finished.append(True)

        async def run():
            with patch('builtins.__import__', without_anyio):
                task = asyncio.create_task(_cleanup(close_resource()))
                await asyncio.sleep(.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual([True], finished)
        asyncio.run(run())

    def test_selected_box_png_is_decodable_and_matches_scene(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10, 'quantity': 2}],
                   'items': [{'id': 'I', 'width': 9, 'length': 9, 'height': 9, 'quantity': 2}]}
        result = solved(request)

        async def run():
            async with PackerRenderer() as renderer:
                first = await renderer.render(request, result, box_indexes=[1], view='top')
                second = await renderer.render(request, result, box_indexes=[0], view='isometric')
                self.assertIsNotNone(renderer.browser)
                return first, second
        top, iso = asyncio.run(run())
        self.assertTrue(top['renderer_cold'])
        self.assertFalse(iso['renderer_cold'])
        self.assertGreater(top['render_ms'], 0)
        self.assertGreater(iso['render_ms'], 0)
        for output, index, view in ((top, 1, 'top'), (iso, 0, 'isometric')):
            self.assertTrue(output['valid'], output.get('errors'))
            self.assertEqual(1, len(output['images']))
            image = output['images'][0]
            self.assertEqual((1024, 768), png_dimensions(image['png']))
            self.assertEqual(index, image['box_index'])
            self.assertEqual(view, image['view'])
            self.assertEqual([(p['id'], p['instance']) for p in result['bins'][index]['items']],
                             [(p['id'], p['instance']) for p in image['scene']['items']])
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            (ARTIFACTS / f'box-{index}-{view}.png').write_bytes(image['png'])
        self.assertNotEqual(top['images'][0]['scene']['camera'], iso['images'][0]['scene']['camera'])

    def test_invalid_geometry_does_not_launch_renderer(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}]}
        result = solved(request)
        result['bins'][0]['items'][0]['x'] = 100

        async def run():
            async with PackerRenderer() as renderer:
                output = await renderer.render(request, result)
                self.assertIsNone(renderer.browser)
                return output
        output = asyncio.run(run())
        self.assertFalse(output['valid'])
        self.assertFalse(output['images'])

    def test_geometric_png_keeps_reported_center_and_orientation(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 100, 'length': 100, 'height': 100}],
                   'items': [{'id': 'Rod', 'width': 150, 'length': 8, 'height': 8,
                              'rotation': 'free3d', 'diagonal': True}],
                   'options': {'support_mode': 'geometric', 'clearance': 0, 'gap': 0}}
        result = solved(request)

        async def run():
            async with PackerRenderer() as renderer:
                return await renderer.render(request, result)
        output = asyncio.run(run())
        self.assertTrue(output['valid'], output['errors'])
        self.assertEqual((1024, 768), png_dimensions(output['images'][0]['png']))
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / 'free3d-rod-isometric.png').write_bytes(output['images'][0]['png'])
        reported = result['bins'][0]['items'][0]
        rendered = output['images'][0]['scene']['items'][0]
        self.assertEqual(reported['center'], rendered['center'])
        self.assertEqual(reported['orientation'], rendered['orientation'])

    def test_ordinary_png_ignores_unverified_3d_pose_aliases(self):
        from packer_adapter.render import PackerRenderer
        from packer_adapter.validation import validate
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}]}
        result = solved(request)
        placement = result['bins'][0]['items'][0]
        expected = [placement['x'], placement['y'], placement['z'] + placement['height']/2]
        placement['center'] = [100, 100, 100]
        placement['orientation'] = [0, 0, 0, 1]
        self.assertEqual([], validate(request, result))

        async def run():
            async with PackerRenderer() as renderer:
                return await renderer.render(request, result)
        output = asyncio.run(run())
        self.assertTrue(output['valid'], output['errors'])
        self.assertEqual((1024, 768), png_dimensions(output['images'][0]['png']))
        item = output['images'][0]['scene']['items'][0]
        self.assertEqual(expected, item['center'])
        self.assertEqual(expected, item['meshCenter'])

    def test_image_limit_reports_omitted_boxes(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10, 'quantity': 5}],
                   'items': [{'id': 'I', 'width': 9, 'length': 9, 'height': 9, 'quantity': 5}]}
        result = solved(request)

        async def run():
            async with PackerRenderer() as renderer:
                return await renderer.render(request, result)
        output = asyncio.run(run())
        self.assertEqual(4, len(output['images']))
        self.assertEqual([4], [entry['box_index'] for entry in output['omitted']])

    def test_parallel_calls_keep_selected_boxes_isolated(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10, 'quantity': 2}],
                   'items': [{'id': 'I', 'width': 9, 'length': 9, 'height': 9, 'quantity': 2}]}
        result = solved(request)

        async def run():
            async with PackerRenderer() as renderer:
                return await asyncio.gather(renderer.render(request, result, box_indexes=[0]),
                                            renderer.render(request, result, box_indexes=[1]))
        outputs = asyncio.run(run())
        self.assertEqual([0, 1], [x['images'][0]['box_index'] for x in outputs])
        self.assertEqual([0, 1], [x['images'][0]['scene']['boxIndex'] for x in outputs])

    def test_missing_browser_preserves_valid_result_and_diagnostic(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}]}
        result = solved(request)

        async def fail_start(_):
            raise ModuleNotFoundError('playwright is not installed')

        async def run():
            async with PackerRenderer() as renderer:
                with patch.object(PackerRenderer, 'start', fail_start):
                    return await renderer.render(request, result)
        output = asyncio.run(run())
        self.assertTrue(output['valid'])
        self.assertFalse(output['images'])
        self.assertIn('playwright is not installed', output['render_error'])
        self.assertEqual([0], [entry['box_index'] for entry in output['omitted']])

    def test_inline_budget_omits_png_without_changing_validation(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}]}
        result = solved(request)

        async def run():
            async with PackerRenderer() as renderer:
                return await renderer.render(request, result, max_total_bytes=1)
        output = asyncio.run(run())
        self.assertTrue(output['valid'])
        self.assertFalse(output['images'])
        self.assertEqual([0], [entry['box_index'] for entry in output['omitted']])

    def test_renderer_timeout_fails_closed_without_losing_validity(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}]}
        result = solved(request)

        async def never_returns(*_):
            await asyncio.sleep(5)

        async def run():
            async with PackerRenderer(timeout_ms=1) as renderer:
                with patch.object(PackerRenderer, '_image', never_returns):
                    return await renderer.render(request, result)
        output = asyncio.run(run())
        self.assertTrue(output['valid'])
        self.assertFalse(output['images'])
        self.assertIn('TimeoutError', output['render_error'])

    def test_failed_image_cancels_and_awaits_sibling(self):
        from packer_adapter.render import PackerRenderer
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10, 'quantity': 2}],
                   'items': [{'id': 'I', 'width': 9, 'length': 9, 'height': 9, 'quantity': 2}]}
        result = solved(request)
        cancelled = asyncio.Event()

        async def failing_image(_, _result, index, _view):
            if index == 0:
                await asyncio.sleep(.05)
                raise RuntimeError('image failed')
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def run():
            async with PackerRenderer() as renderer:
                with patch.object(PackerRenderer, '_image', failing_image):
                    output = await renderer.render(request, result)
                    return output, cancelled.is_set()
        output, sibling_cancelled = asyncio.run(run())
        self.assertTrue(output['valid'])
        self.assertIn('image failed', output['render_error'])
        self.assertTrue(sibling_cancelled)

    def test_browser_close_error_still_stops_playwright(self):
        from packer_adapter.render import PackerRenderer
        stopped = []

        class BrokenBrowser:
            async def close(self):
                raise RuntimeError('close failed')

        class Playwright:
            async def stop(self):
                stopped.append(True)

        async def run():
            renderer = PackerRenderer()
            renderer.browser = BrokenBrowser()
            renderer._playwright = Playwright()
            with self.assertRaisesRegex(RuntimeError, 'close failed'):
                await renderer.close()
        asyncio.run(run())
        self.assertEqual([True], stopped)

    def test_schema_mismatch_fails_closed(self):
        from packer_adapter.validation import validate
        self.assertTrue(validate({'boxes': [], 'items': []}, {'schema_version': 2}))

    def test_explicit_full_base_mode_uses_ordinary_rules(self):
        from packer_adapter.validation import validate
        request = {'boxes': [{'id': 'B', 'width': 10, 'length': 10, 'height': 10}],
                   'items': [{'id': 'I', 'width': 2, 'length': 2, 'height': 2}],
                   'options': {'support_mode': 'full_base', 'gap': 0}}
        result = json.loads(subprocess.run([str(BINARY)],
                                           input=json.dumps(request), text=True, capture_output=True, check=True).stdout)
        self.assertEqual(validate(request, result), [])


if __name__ == '__main__':
    unittest.main()
