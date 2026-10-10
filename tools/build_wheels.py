"""Build the packer3d wheels with the native CLI bundled, one per platform.

Windows x64 uses build/packer.exe from build.ps1. Linux x64 is cross-compiled
here with the project's Zig as a static musl executable, so one wheel runs on
any x86-64 Linux distribution. Usage: python tools/build_wheels.py [output_dir]
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIG = ROOT / '.tools/zig-x86_64-windows-0.15.2/zig.exe'
SOURCES = ['src/cli.c', 'src/json3d.c', 'src/oblique.c', 'src/geometry3d.c', 'src/packer3d.c',
           'src/search3d.c', 'third_party/cJSON.c']
BIN = ROOT / 'python/packer3d/bin'


def linux_static():
    target = ROOT / 'build/linux-static/packer'
    target.parent.mkdir(parents=True, exist_ok=True)
    zig = str(ZIG) if ZIG.exists() else 'zig'
    subprocess.run([zig, 'cc', '-target', 'x86_64-linux-musl', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Iinclude', '-Ithird_party', '-static', '-s', *SOURCES, '-o', str(target)], cwd=ROOT, check=True)
    return target


def wheel(binary, name, platform, output):
    shutil.rmtree(BIN, ignore_errors=True)
    shutil.rmtree(ROOT / 'python/build', ignore_errors=True)
    BIN.mkdir(parents=True)
    shutil.copy2(binary, BIN / name)
    shutil.copy2(ROOT / 'LICENSE', BIN / 'LICENSE')
    shutil.copy2(ROOT / 'third_party/cJSON.LICENSE', BIN / 'LICENSE-cJSON')
    env = dict(os.environ, PACKER3D_PLATFORM=platform)
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation', '-w', str(output),
                        str(ROOT / 'python')], env=env, check=True)
    finally:
        shutil.rmtree(BIN, ignore_errors=True)
        shutil.rmtree(ROOT / 'python/build', ignore_errors=True)


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'release/0.4.1/python'
    output.mkdir(parents=True, exist_ok=True)
    windows = ROOT / 'build/packer.exe'
    if not windows.exists():
        raise SystemExit('Run ./build.ps1 first: build/packer.exe is missing')
    wheel(windows, 'packer.exe', 'win_amd64', output)
    wheel(linux_static(), 'packer', 'manylinux2014_x86_64.musllinux_1_1_x86_64', output)
    for path in sorted(output.glob('packer3d-*.whl')):
        executable_bit(path)
        print(path.name, path.stat().st_size)


def executable_bit(path):
    """Archives written on Windows lack Unix modes: mark the bundled CLI executable."""
    temporary = path.with_suffix('.tmp')
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename.endswith('/bin/packer'):
                info.external_attr = (0o100755 << 16)
                info.create_system = 3
            target.writestr(info, data)
    temporary.replace(path)


if __name__ == '__main__':
    main()
