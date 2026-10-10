"""Assemble the GitHub Pages demo in build/site: page files, the engine compiled to
WebAssembly with Zig, Three.js and the logo. Usage: python tools/build_site.py [out]"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_wheels import ROOT, SOURCES, ZIG  # noqa: E402


def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'build/site'
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(ROOT / 'site', out, ignore=shutil.ignore_patterns('worker', '*.md'))
    zig = str(ZIG) if ZIG.exists() else (shutil.which('zig') or 'zig')
    subprocess.run([zig, 'cc', '-target', 'wasm32-wasi', '-std=c11', '-O2', '-s', '-Iinclude', '-Ithird_party',
                    *SOURCES, '-o', str(out / 'packer.wasm')], cwd=ROOT, check=True)
    (out / 'vendor').mkdir()
    for name in ('three.module.js', 'three.core.js', 'LICENSE-three.txt'):
        shutil.copy2(ROOT / 'viewer/vendor' / name, out / 'vendor' / name)
    for name in ('logo.svg', 'social-preview.png'):
        shutil.copy2(ROOT / 'docs/images' / name, out / name)
    (out / '.nojekyll').write_text('')
    print(f'Site assembled in {out}')


if __name__ == '__main__':
    main()
