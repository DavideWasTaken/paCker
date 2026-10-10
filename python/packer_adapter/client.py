"""Synchronous Python facade for the paCker JSON executable, like the PHP Packer.

    from packer_adapter import Packer
    packer = Packer()
    packer.add_box(id='carton', width=180, length=180, height=30)
    packer.add_item(id='bar', width=220, length=30, height=20, quantity=3)
    result = packer.pack()

Standard library only. The native CLI validates every field; this class adds no
packing logic. The executable is, in order: binary=, PACKER_BINARY, the one
bundled in the packer3d wheel, or build/ of a source checkout.
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

__all__ = ['Packer', 'PackerError']
MAX_INPUT_BYTES = 1048576
MAX_OUTPUT_BYTES = 16777216


class PackerError(RuntimeError):
    """Invalid request, missing binary, process failure or malformed output."""


def default_binary():
    configured = os.environ.get('PACKER_BINARY')
    if configured:
        return Path(configured)
    name = 'packer.exe' if sys.platform == 'win32' else 'packer'
    bundled = Path(__file__).resolve().parents[1] / 'packer3d' / 'bin' / name
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parents[2] / 'build' / name


class Packer:
    def __init__(self, binary=None, timeout=None):
        if timeout is not None and not (isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0):
            raise ValueError('timeout must be positive and finite')
        self.binary = Path(binary) if binary is not None else default_binary()
        self.timeout = timeout
        self.boxes, self.items, self.options = [], [], {}

    def add_box(self, box=None, **fields):
        self.boxes.append(dict(box or {}, **fields))
        return self

    def add_item(self, item=None, quantity=None, **fields):
        value = dict(item or {}, **fields)
        if quantity is not None:
            value['quantity'] = quantity
        self.items.append(value)
        return self

    def set_options(self, options=None, **fields):
        """Successive calls merge options, e.g. support_mode='full_base', improve=True."""
        self.options.update(dict(options or {}, **fields))
        return self

    def request(self):
        return dict(boxes=list(self.boxes), items=list(self.items), options=dict(self.options))

    def pack(self):
        binary = self.binary.resolve()
        if not binary.is_file():
            raise PackerError(f'Packing binary is missing: {self.binary}')
        if os.name == 'posix' and not os.access(binary, os.X_OK):
            try:
                binary.chmod(binary.stat().st_mode | 0o755)
            except OSError as exc:
                raise PackerError(f'Packing binary is not executable: {binary}') from exc
        try:
            data = json.dumps(self.request(), allow_nan=False, ensure_ascii=False).encode('utf-8')
        except (TypeError, ValueError) as exc:
            raise PackerError(f'Request is not finite JSON: {exc}') from exc
        if len(data) > MAX_INPUT_BYTES:
            raise PackerError('Request exceeds 1 MiB')
        timeout = self.timeout or self.options.get('time_limit_ms', 1000)/1000 + 5
        try:
            process = subprocess.run([str(binary)], input=data, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise PackerError(f'Packing binary exceeded {timeout:g} seconds') from exc
        if len(process.stdout) > MAX_OUTPUT_BYTES:
            raise PackerError('Output exceeds 16 MiB')
        try:
            result = json.loads(process.stdout)
        except ValueError as exc:
            raise PackerError('Packing binary returned invalid JSON') from exc
        if process.returncode or not isinstance(result, dict) or 'error' in result:
            message = result.get('error') if isinstance(result, dict) else None
            raise PackerError(message or f'Packing binary exited {process.returncode}')
        if result.get('status') not in ('complete', 'partial') or not isinstance(result.get('bins'), list):
            raise PackerError('Packing binary returned an unexpected result')
        return result
