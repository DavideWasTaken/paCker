"""Faithful final-box PNGs using a reusable, isolated Chromium renderer."""
import asyncio
from contextlib import nullcontext
from pathlib import Path
from time import perf_counter

from .validation import validate

WIDTH, HEIGHT = 1024, 768
MAX_IMAGES = 4
MAX_INLINE_BYTES = 4 * 1024 * 1024
_ASSETS = ('render.html', 'pose.js', 'packing-scene.js', 'camera.js',
           'vendor/three.module.js', 'vendor/three.core.js', 'vendor/LICENSE-three.txt')


def _asset_root():
    bundled = Path(__file__).resolve().parent / 'assets'
    return bundled if bundled.is_dir() else Path(__file__).resolve().parents[2] / 'viewer'


async def _cleanup(awaitable):
    """Await resource cleanup despite asyncio or the SDK's level cancellation.

    AnyIO is optional for standalone images; use its scope only when installed.
    A separate asyncio task also protects cleanup from direct task cancellation.
    """
    try:
        from anyio import CancelScope
    except ImportError:
        scope = nullcontext()
    else:
        scope = CancelScope(shield=True)
    with scope:
        task = asyncio.ensure_future(awaitable)
        cancelled = False
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                # Nested gather/wait_for cleanup can cancel an image task again.
                # Finish the resource operation before propagating cancellation.
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError


class PackerRenderer:
    """Bind Playwright to one event loop; reuse Chromium, isolate each image."""

    def __init__(self, concurrency=2, timeout_ms=15000, validator=None):
        self.browser = None
        self._playwright = None
        self._start_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(1, min(int(concurrency), MAX_IMAGES)))
        self.timeout_ms = timeout_ms
        self._validator = validator

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def start(self):
        async with self._start_lock:
            if self.browser:
                return
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            try:
                self.browser = await self._playwright.chromium.launch(
                    args=['--use-gl=angle', '--use-angle=swiftshader'])
            except BaseException:
                await _cleanup(self._playwright.stop())
                self._playwright = None
                raise

    async def close(self):
        async def close_resources():
            try:
                if self.browser:
                    await self.browser.close()
            finally:
                self.browser = None
                if self._playwright:
                    try:
                        await self._playwright.stop()
                    finally:
                        self._playwright = None
        await _cleanup(close_resources())

    async def _image(self, result, index, view):
        async with self._semaphore:
            context = await self.browser.new_context(viewport={'width': WIDTH, 'height': HEIGHT},
                                                     device_scale_factor=1, service_workers='block')
            try:
                root = _asset_root()

                async def asset_route(route):
                    name = route.request.url.removeprefix('https://packer-render.invalid/')
                    if name not in _ASSETS:
                        await route.abort()
                        return
                    content_type = ('text/html' if name.endswith('.html') else
                                    'text/javascript' if name.endswith('.js') else 'text/plain')
                    await route.fulfill(status=200, content_type=content_type,
                                        body=(root / name).read_bytes())

                await context.route('https://packer-render.invalid/**', asset_route)
                page = await context.new_page()
                page.set_default_timeout(self.timeout_ms)
                await page.goto('https://packer-render.invalid/render.html', wait_until='load', timeout=self.timeout_ms)
                await page.wait_for_function('window.renderPageReady === true', timeout=self.timeout_ms)
                scene = await page.evaluate('args => window.renderScene(args)',
                                            {'result': result, 'boxIndex': index, 'view': view})
                await page.wait_for_function('window.sceneReady === true', timeout=self.timeout_ms)
                png = await page.screenshot(type='png', timeout=self.timeout_ms)
                return {'box_index': index, 'box_id': result['bins'][index]['id'],
                        'box_type_id': result['bins'][index]['type_id'], 'view': view,
                        'width': WIDTH, 'height': HEIGHT, 'scene': scene, 'png': png}
            finally:
                await _cleanup(context.close())

    async def render(self, request, result, box_indexes=None, view='isometric',
                     max_images=MAX_IMAGES, max_total_bytes=MAX_INLINE_BYTES):
        """Validate first. Return images and omissions; retain valid result on render failure."""
        validation_start = perf_counter()
        errors = (await self._validator(request, result) if self._validator is not None
                  else validate(request, result))
        output = {'valid': not errors, 'errors': errors, 'images': [], 'omitted': [],
                  'render_error': None, 'validation_ms': (perf_counter()-validation_start)*1000,
                  'render_ms': 0.0, 'renderer_cold': None}
        if errors:
            return output
        if view not in ('isometric', 'top'):
            output['render_error'] = 'View must be isometric or top.'
            return output
        if box_indexes is None:
            box_indexes = list(range(len(result['bins'])))
        if (not isinstance(box_indexes, (list, tuple)) or
                any(type(i) is not int or i < 0 or i >= len(result['bins']) for i in box_indexes) or
                len(set(box_indexes)) != len(box_indexes)):
            output['render_error'] = 'Selected box indexes are invalid.'
            return output
        if not isinstance(max_images, int) or max_images < 0 or not isinstance(max_total_bytes, int) or max_total_bytes < 0:
            output['render_error'] = 'Image limits are invalid.'
            return output
        chosen = box_indexes[:min(max_images, MAX_IMAGES)]
        output['omitted'] = [{'box_index': i, 'reason': 'maximum of four images'}
                             for i in box_indexes[len(chosen):]]
        if not chosen:
            return output
        render_start = perf_counter()
        output['renderer_cold'] = self.browser is None
        try:
            await self.start()
            # Gather under bounded semaphore; return in requested box order.
            tasks = [asyncio.create_task(self._image(result, i, view)) for i in chosen]
            try:
                images = await asyncio.wait_for(asyncio.gather(*tasks),
                                                timeout=max(1, self.timeout_ms/1000)*len(chosen))
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await _cleanup(asyncio.gather(*tasks, return_exceptions=True))
            total = 0
            for image in images:
                if total + len(image['png']) > min(max_total_bytes, MAX_INLINE_BYTES):
                    output['omitted'].append({'box_index': image['box_index'], 'reason': '4 MiB inline PNG budget'})
                else:
                    output['images'].append(image)
                    total += len(image['png'])
        except Exception as exc:
            output['render_error'] = f'Image renderer unavailable: {type(exc).__name__}: {exc}'
            for i in chosen:
                if i not in [x['box_index'] for x in output['images']]:
                    output['omitted'].append({'box_index': i, 'reason': 'renderer unavailable'})
        output['render_ms'] = (perf_counter()-render_start)*1000
        return output
