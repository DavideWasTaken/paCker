"""Local stateless MCP tools; stdout is reserved for stdio protocol messages."""
import argparse
import base64
from contextlib import asynccontextmanager
import importlib.util
import json
import os
from pathlib import Path
from time import perf_counter

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import ConfigDict

from .engine import Engine, Validator
from .models import (AdapterError, Capabilities, Envelope, REQUEST_SCHEMA, RESULT_SCHEMA,
                     check_request, check_result, selected_boxes)
from .render import PackerRenderer, MAX_IMAGES, MAX_INLINE_BYTES


def _response(envelope, images=(), error=False):
    data = envelope.model_dump(mode='python')
    content = [TextContent(type='text', text=json.dumps(data, ensure_ascii=False, allow_nan=False))]
    content.extend(ImageContent(type='image', data=base64.b64encode(image['png']).decode('ascii'),
                                mime_type='image/png') for image in images)
    return CallToolResult(content=content, structured_content=data, is_error=error)


def _failure(code, message):
    return _response(Envelope(error={'code': code, 'message': message}), error=True)


class Adapter:
    def __init__(self, binary, *, engine_timeout=70, validation_timeout=30, render_timeout_ms=15000):
        self.engine = Engine(binary, timeout=engine_timeout)
        self.validator = Validator(timeout=validation_timeout)
        # The callback resolves the current validator, also allowing controlled test failures.
        async def bounded_validation(request, result):
            return await self.validator.validate(request, result)
        self.renderer = PackerRenderer(timeout_ms=render_timeout_ms, validator=bounded_validation)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.renderer.close()

    async def capabilities(self):
        installed = importlib.util.find_spec('playwright') is not None
        executable = None
        if installed:
            from playwright.async_api import async_playwright
            async with async_playwright() as playwright:
                executable = playwright.chromium.executable_path
        return Capabilities(engine=await self.engine.capabilities(),
            renderer={'available': bool(executable and Path(executable).is_file()),
                      'playwright_installed': installed, 'views': ['isometric', 'top'],
                      'width': 1024, 'height': 768, 'max_images': MAX_IMAGES,
                      'max_png_bytes': MAX_INLINE_BYTES,
                      'availability_note': 'Installed Chromium detected; a render call verifies launch.'},
            adapter={'version': '0.1.0', 'transport': 'stdio', 'stateless': True,
                     'result_bytes': 4*1024*1024, 'engine_timeout_seconds': self.engine.timeout,
                     'validation_timeout_seconds': self.validator.timeout,
                     'geometric_conventions': {'axes': 'right-handed X=width,Y=length,Z=height',
                         'position': 'center', 'quaternion': 'active local-to-container [x,y,z,w]',
                         'support': 'padding supplied by user; no gravity or insertion path'}})

    async def call(self, name, arguments):
        start = perf_counter()
        envelope = Envelope(validation={'status': 'not_run', 'valid': False, 'violations': []},
                            rendering={'status': 'not_requested', 'images': [], 'omitted': []},
                            timings={'solver_ms': 0.0, 'validation_ms': 0.0, 'render_ms': 0.0, 'total_ms': 0.0})
        images = []
        phase = None
        phase_start = start
        try:
            if name == 'get_capabilities':
                caps = await self.capabilities()
                data = caps.model_dump(mode='python')
                return CallToolResult(content=[TextContent(type='text', text=json.dumps(data))], structured_content=data)
            request = check_request(arguments['request'])
            include_image = arguments.get('include_image', False)
            view = arguments.get('view', 'isometric')
            if type(include_image) is not bool or view not in ('isometric', 'top'):
                raise AdapterError('invalid_input', 'include_image must be boolean; view must be isometric or top.')
            if name == 'pack_order':
                phase, phase_start = 'solver_ms', perf_counter()
                envelope.packing = await self.engine.pack(request)
                envelope.timings[phase] = (perf_counter()-phase_start)*1000
                phase = None
            elif name in ('validate_packing', 'render_packing'):
                envelope.packing = check_result(arguments['result'])
            else:
                raise AdapterError('invalid_input', 'Unknown tool.')
            indexes = selected_boxes(envelope.packing, arguments.get('box_indexes'), arguments.get('box_ids'))
            phase, phase_start = 'validation_ms', perf_counter()
            violations = await self.validator.validate(request, envelope.packing)
            envelope.timings[phase] = (perf_counter()-phase_start)*1000
            phase = None
            envelope.validation = {'status': 'invalid' if violations else 'valid', 'valid': not violations,
                                   'violations': violations}
            if violations:
                raise AdapterError('invalid_result', 'Independent validation rejected the result.')
            if name == 'render_packing' or include_image:
                phase, phase_start = 'render_ms', perf_counter()
                rendered = await self.renderer.render(request, envelope.packing, box_indexes=indexes, view=view)
                # Renderer validation also uses the interruptible worker; account for both checks.
                envelope.timings['validation_ms'] += rendered['validation_ms']
                envelope.timings['render_ms'] = rendered['render_ms']
                phase = None
                if not rendered['valid']:
                    envelope.validation = {'status': 'invalid', 'valid': False, 'violations': rendered['errors']}
                    raise AdapterError('invalid_result', 'Renderer validation rejected the result.')
                images = rendered['images']
                envelope.rendering = {'status': 'error' if rendered['render_error'] else
                                      ('partial' if rendered['omitted'] else 'complete'),
                    'view': view, 'selected_boxes': [{'box_index': i, 'box_id': envelope.packing['bins'][i]['id']} for i in indexes],
                    'images': [{key: value for key, value in image.items() if key != 'png'} for image in images],
                    'omitted': rendered['omitted'], 'renderer_cold': rendered['renderer_cold'],
                    'png_bytes': sum(len(image['png']) for image in images)}
                if rendered['render_error']:
                    raise AdapterError('render_error', rendered['render_error'])
        except AdapterError as exc:
            if phase:
                envelope.timings[phase] += (perf_counter()-phase_start)*1000
            if exc.code.startswith('validation_'):
                envelope.validation = {'status': 'error', 'valid': False, 'violations': [str(exc)]}
            envelope.error = {'code': exc.code, 'message': str(exc)}
        envelope.timings['total_ms'] = (perf_counter()-start)*1000
        return _response(envelope, images, error=envelope.error is not None)


class EmptyArguments(ArgModelBase):
    model_config = ConfigDict(extra='forbid', strict=True)


class PackArguments(EmptyArguments):
    request: dict
    include_image: bool = False
    box_indexes: list[int] | None = None
    box_ids: list[str] | None = None
    view: str = 'isometric'


class ValidateArguments(EmptyArguments):
    request: dict
    result: dict


class RenderArguments(ValidateArguments):
    box_indexes: list[int] | None = None
    box_ids: list[str] | None = None
    view: str = 'isometric'


class ClosedTool(Tool):
    async def run(self, arguments, context, convert_result=False):
        try:
            return await super().run(arguments, context, convert_result=convert_result)
        except ToolError as exc:
            return _failure('invalid_input', str(exc)[:2048])


def create_server(binary):
    adapter = Adapter(binary)

    @asynccontextmanager
    async def lifespan(_server):
        async with adapter:
            yield adapter

    selection = {'box_indexes': {'type': ['array', 'null'], 'maxItems': 256,
                    'uniqueItems': True, 'items': {'type': 'integer', 'minimum': 0, 'maximum': 255}},
                 'box_ids': {'type': ['array', 'null'], 'maxItems': 256, 'uniqueItems': True,
                    'items': {'type': 'string', 'minLength': 1, 'maxLength': 63}},
                 'view': {'enum': ['isometric', 'top'], 'default': 'isometric'}}
    specifications = [
        ('get_capabilities', EmptyArguments, {}, [], Capabilities,
         'Discover the configured local engine contract, limits, and renderer availability.'),
        ('pack_order', PackArguments, {'request': REQUEST_SCHEMA,
            'include_image': {'type': 'boolean', 'default': False}, **selection}, ['request'], Envelope,
         'Pack exactly one CLI request; independently validate it and optionally return final-box PNGs.'),
        ('validate_packing', ValidateArguments, {'request': REQUEST_SCHEMA, 'result': RESULT_SCHEMA},
         ['request', 'result'], Envelope, 'Validate an original request/result pair without changing its layout.'),
        ('render_packing', RenderArguments, {'request': REQUEST_SCHEMA, 'result': RESULT_SCHEMA, **selection},
         ['request', 'result'], Envelope, 'Return PNGs of verified original poses, without rerunning packing.')]
    tools = []
    for name, argument_model, properties, required, output_model, description in specifications:
        def handler_for(tool_name):
            async def handler(**arguments):
                return await adapter.call(tool_name, arguments)
            return handler
        tools.append(ClosedTool(fn=handler_for(name), name=name, description=description,
            parameters={'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False},
            fn_metadata=FuncMetadata(arg_model=argument_model, output_model=output_model), is_async=True,
            annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=False,
                                        open_world_hint=False)))
    return MCPServer('paCker', version='0.1.0', tools=tools, lifespan=lifespan,
                     instructions='Supply actual product and box dimensions. Geometric mode assumes padding supplied by the user.')


def main():
    parser = argparse.ArgumentParser(description='paCker local MCP stdio server')
    parser.add_argument('--binary', default=os.environ.get('PACKER_BINARY'), help='Configured paCker executable')
    options = parser.parse_args()
    if not options.binary:
        from .client import default_binary
        bundled = default_binary()
        if not bundled.is_file():
            parser.error('set PACKER_BINARY or provide --binary with the installed CLI executable')
        options.binary = str(bundled)
    create_server(options.binary).run(transport='stdio')


if __name__ == '__main__':
    main()
