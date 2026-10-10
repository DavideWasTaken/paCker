# Publishing packer3d (PyPI) and davidewastaken/packer (Composer)

Both packages bundle the native CLI, so users need no compiler. Build them on Windows from a clean
checkout; nothing here publishes anything by itself.

## Build

```powershell
./build.ps1                          # build/packer.exe and native tests
python tools/build_wheels.py         # release/0.5.0/python/*.whl (Windows x64, static Linux x64)
python tools/build_composer.py       # release/0.5.0/composer: a ready Git repository tagged v0.5.0
```

The Linux executable is cross-compiled with the project's Zig as a static musl binary, tagged
`manylinux2014_x86_64.musllinux_1_1_x86_64`. Both wheels and the Composer package were installed and
run on Windows and on Ubuntu (WSL) before the first release.

## PyPI

1. Create a PyPI account and an API token; optionally try TestPyPI first.
2. `python -m pip install twine`
3. `python -m twine upload release/0.5.0/python/*.whl`

Only wheels are uploaded: a source distribution would need a C compiler at install time.

## Packagist

1. Create an empty public GitHub repository, for example `DavideWasTaken/packer-php`.
2. From `release/0.5.0/composer`:
   `git remote add origin https://github.com/DavideWasTaken/packer-php.git`, then
   `git push -u origin main --tags`.
3. On packagist.org, submit the repository URL and enable the GitHub hook for updates.

Users then run `composer require davidewastaken/packer`. The package name comes from its
`composer.json`; change it in `tools/build_composer.py` before the first push if needed.

## Next versions

Bump `OP_VERSION`/`OP3_VERSION`, `CMakeLists.txt`, `python/pyproject.toml`, `packer3d.__version__`
and `VERSION` in `tools/build_composer.py`, rebuild, then repeat the steps above. For Composer, copy
the new staged files into your existing package repository and tag the new version there.
