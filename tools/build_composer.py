"""Stage the standalone Composer package with bundled Windows and Linux x64 executables.

The output directory is a ready Git repository for Packagist: commit it to a public
GitHub repository and tag the version. Executables come from tools/build_wheels.py:
build/packer.exe when present (else a Zig cross build) and a static Linux build.
Usage: python tools/build_composer.py [dir]
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_wheels import ROOT, linux_static, windows_binary  # noqa: E402

VERSION = '0.5.0'
NAME = 'davidewastaken/packer'
README = """# paCker for PHP

Fast 3D cuboid packing: boxes, products, stock, weight limits, rotations and stable
support. The native C engine is bundled for Windows x64 and Linux x64; no PHP extension,
FFI or compiler is needed. PHP 8.1+ with `ext-json` and `proc_open`.

```sh
composer require {name}
```

```php
require 'vendor/autoload.php';

$packer = new \\paCker\\Packer();
$packer->addBox(['id' => 'carton', 'width' => 300, 'length' => 200, 'height' => 150, 'max_weight' => 5000]);
$packer->addItem(['id' => 'book', 'width' => 240, 'length' => 170, 'height' => 30, 'weight' => 400], 6);
$packer->setOptions(['time_limit_ms' => 1000]);
$result = $packer->pack();   // bins with positions, unpacked products, stats
```

Options include `support_mode` (`stable` by default, `contact`, `full_base`, `geometric`), `improve` (keep
searching until the time limit) and `gap`. On other platforms pass your own build:
`new \\paCker\\Packer('/path/to/packer')` or set `PACKER_BINARY`.

Engine {version}. Source, documentation and the C library: https://github.com/DavideWasTaken/paCker

MIT licensed; the bundled engine includes cJSON (MIT, see LICENSE-cJSON).
"""


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / f'release/{VERSION}/composer'
    windows = windows_binary()
    if output.exists():
        # Git marks its objects read-only on Windows.
        shutil.rmtree(output, onerror=lambda function, path, _: (os.chmod(path, 0o700), function(path)))
    (output / 'src').mkdir(parents=True)
    (output / 'bin').mkdir()
    shutil.copy2(ROOT / 'php/src/Packer.php', output / 'src/Packer.php')
    shutil.copy2(windows, output / 'bin/packer-windows-x64.exe')
    shutil.copy2(linux_static(), output / 'bin/packer-linux-x64')
    shutil.copy2(ROOT / 'LICENSE', output / 'LICENSE')
    shutil.copy2(ROOT / 'third_party/cJSON.LICENSE', output / 'LICENSE-cJSON')
    (output / 'README.md').write_text(README.format(name=NAME, version=VERSION), encoding='utf-8')
    (output / '.gitattributes').write_text('bin/* binary\n', encoding='utf-8')
    composer = {
        'name': NAME,
        'description': 'Fast 3D cuboid packing with a bundled native engine: boxes, stock, weight, rotations, stable support',
        'type': 'library', 'license': 'MIT', 'homepage': 'https://github.com/DavideWasTaken/paCker',
        'keywords': ['bin packing', 'box packing', '3d packing', 'shipping', 'cuboid'],
        'require': {'php': '>=8.1', 'ext-json': '*'},
        'autoload': {'psr-4': {'paCker\\': 'src/'}, 'files': ['src/Packer.php']},
    }
    (output / 'composer.json').write_text(json.dumps(composer, indent=4) + '\n', encoding='utf-8')
    # A ready repository: the Linux executable keeps its mode even when committed on Windows.
    git = ['git', '-C', str(output)]
    subprocess.run([*git, 'init', '-q', '-b', 'main'], check=True)
    subprocess.run([*git, 'add', '-A'], check=True)
    subprocess.run([*git, 'update-index', '--chmod=+x', 'bin/packer-linux-x64'], check=True)
    subprocess.run([*git, 'commit', '-q', '-m', f'paCker {VERSION}'], check=True)
    subprocess.run([*git, 'tag', f'v{VERSION}'], check=True)
    print(f'Staged {NAME} {VERSION} in {output}')


if __name__ == '__main__':
    main()
