"""Compile private cache checks while preserving the public library ABI."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SearchCacheTests(unittest.TestCase):
    def test_completed_cache_keys_and_global_limits(self):
        zig = ROOT / '.tools/zig-x86_64-windows-0.15.2/zig.exe'
        zig = zig if zig.exists() else Path(shutil.which('zig') or zig)
        if sys.platform == 'win32' and zig.exists():
            compiler = [str(zig), 'cc']
        else:
            cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
            if not cc:
                self.skipTest('No C compiler available for private cache checks')
            compiler = [cc]
        with tempfile.TemporaryDirectory(prefix='ordinary-cache-') as directory:
            binary = Path(directory) / ('cache.exe' if sys.platform == 'win32' else 'cache')
            command = compiler + ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                  '-I' + str(ROOT / 'include'), str(ROOT / 'tests/search_cache.c'),
                                  '-o', str(binary)]
            if sys.platform != 'win32':
                command.append('-lm')
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
