"""Bounded asynchronous boundaries around fixed local executables."""
import asyncio
import json
from pathlib import Path
import sys
import anyio

from .models import (AdapterError, REQUEST_BYTES, RESULT_BYTES, STDERR_BYTES,
                     check_request, check_result, json_bytes)


async def run_process(command, data, *, timeout=70, stdout_limit=RESULT_BYTES,
                      stderr_limit=STDERR_BYTES, input_limit=REQUEST_BYTES):
    if len(data) > input_limit:
        raise AdapterError('input_limit', 'Subprocess input exceeds its byte limit.')
    process = None
    tasks = []
    try:
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(*map(str, command), stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=65536))
        try:
            process = await asyncio.shield(spawning)
        except BaseException:
            # Windows may already have created the process before its pipe setup awaits.
            with anyio.CancelScope(shield=True):
                process = await asyncio.shield(spawning)
            raise

        async def read(stream, limit, code):
            chunks, size = [], 0
            while True:
                chunk = await stream.read(min(65536, limit-size+1))
                if not chunk:
                    return b''.join(chunks)
                size += len(chunk)
                if size > limit:
                    raise AdapterError(code, f'Subprocess {code} exceeds {limit} bytes.')
                chunks.append(chunk)

        async def write():
            try:
                process.stdin.write(data)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        tasks = [asyncio.create_task(write()),
                 asyncio.create_task(read(process.stdout, stdout_limit, 'output_limit')),
                 asyncio.create_task(read(process.stderr, stderr_limit, 'stderr_limit')),
                 asyncio.create_task(process.wait())]
        try:
            _, stdout, stderr, returncode = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        except TimeoutError as exc:
            raise AdapterError('process_timeout', f'Subprocess exceeded {timeout:g} seconds.') from exc
        if returncode:
            detail = (stdout or stderr)[:2048].decode('utf-8', errors='replace')
            raise AdapterError('process_exit', f'Subprocess exited {returncode}: {detail}')
        return stdout
    except OSError as exc:
        raise AdapterError('process_start', f'Cannot start configured executable: {exc}') from exc
    finally:
        if process is not None:
            # Shield cleanup against both asyncio cancellation and the SDK's AnyIO cancel scopes.
            async def cleanup():
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await process.wait()
            with anyio.CancelScope(shield=True):
                cleanup_task = asyncio.create_task(cleanup())
                await asyncio.shield(cleanup_task)


def decode_object(data):
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError('Duplicate JSON member')
            result[key] = value
        return result
    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if type(result) is not dict:
            raise ValueError('Expected JSON object')
        json_bytes(result, RESULT_BYTES, 32, 'invalid_response')
        return result
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AdapterError('invalid_response', 'Executable returned invalid JSON object.') from exc


class Engine:
    def __init__(self, binary, timeout=70):
        self.binary = Path(binary).expanduser().resolve()
        self.timeout = timeout
        self._capabilities = None

    async def capabilities(self):
        if self._capabilities is None:
            try:
                caps = decode_object(await run_process([self.binary, '--capabilities'], b'', timeout=5,
                                                       stdout_limit=65536))
                if (caps.get('protocol') != 1 or caps.get('schemas') != [1, 2] or
                        caps.get('support_modes') != ['contact', 'full_base', 'geometric'] or
                        caps.get('limits') != {'request_bytes': REQUEST_BYTES, 'json_depth': 16,
                            'expanded_items': 256, 'box_types': 64, 'id_utf8_bytes': 63} or
                        not isinstance(caps.get('ordinary_version'), str) or
                        caps.get('geometric_version') != '0.4.1-free3d-dev'):
                    raise AdapterError('incompatible_engine', 'Capability handshake does not match supported CLI contract.')
            except AdapterError as exc:
                raise AdapterError('incompatible_engine', f'Configured binary lacks compatible --capabilities: {exc}') from exc
            self._capabilities = caps
        return deepcopy_json(self._capabilities)

    async def pack(self, request):
        check_request(request)
        await self.capabilities()
        try:
            raw = await run_process([self.binary], json_bytes(request, REQUEST_BYTES, 16), timeout=self.timeout)
            result = decode_object(raw)
            if 'error' in result:
                raise AdapterError('engine_error', str(result['error'])[:2048])
            return check_result(result)
        except AdapterError as exc:
            if exc.code in ('invalid_result', 'invalid_response'):
                raise AdapterError('invalid_result', str(exc)) from exc
            raise AdapterError('engine_error', f'{exc.code}: {exc}') from exc


def deepcopy_json(value):
    from copy import deepcopy
    return deepcopy(value)


class Validator:
    def __init__(self, timeout=30, worker_command=None):
        self.timeout = timeout
        self.command = tuple(worker_command or (sys.executable, '-c',
            "import runpy,sys; sys.path.insert(0,sys.argv[1]); runpy.run_module('packer_adapter.validation_worker',run_name='__main__')",
            str(Path(__file__).resolve().parents[1])))

    async def validate(self, request, result):
        data = json_bytes({'request': request, 'result': result}, REQUEST_BYTES+RESULT_BYTES, 33)
        try:
            output = decode_object(await run_process(self.command, data, timeout=self.timeout,
                    input_limit=REQUEST_BYTES+RESULT_BYTES, stdout_limit=1024*1024))
            if set(output) != {'errors'} or type(output['errors']) is not list or any(type(e) is not str for e in output['errors']):
                raise AdapterError('invalid_response', 'Validator worker returned an invalid response.')
            return output['errors']
        except AdapterError as exc:
            code = 'validation_timeout' if exc.code == 'process_timeout' else 'validation_error'
            raise AdapterError(code, f'{exc.code}: {exc}') from exc
