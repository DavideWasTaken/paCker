# Publishing packer3d (PyPI) and davidewastaken/packer (Composer)

Both packages bundle the native CLI for Windows x64 and Linux x64 (a static musl build that runs on any
x86-64 distribution), so users need no compiler.

## PyPI: `pip install packer3d`

The [Wheels workflow](../.github/workflows/wheels.yml) builds and tests both wheels on every push. Publishing
uses PyPI Trusted Publishing, so no token is stored anywhere.

One-time setup on pypi.org (Account → Publishing → Add a new pending publisher):

| Field | Value |
|---|---|
| PyPI project name | `packer3d` |
| Owner | `DavideWasTaken` |
| Repository name | `paCker` |
| Workflow name | `wheels.yml` |
| Environment name | `pypi` |

Then publish: GitHub → Actions → Wheels → Run workflow, with *Publish the wheels to PyPI* checked
(or `gh workflow run wheels.yml -f publish=true`). Bump the version first: PyPI never accepts the same
version twice.

Each GitHub release also carries the wheels, installable directly with
`pip install https://github.com/DavideWasTaken/paCker/releases/download/v<version>/<wheel file>`.

## Packagist: `composer require davidewastaken/packer`

The Composer package lives in its own repository,
[DavideWasTaken/paCker-php](https://github.com/DavideWasTaken/paCker-php), because it ships prebuilt
executables. One-time setup: on packagist.org, Submit → `https://github.com/DavideWasTaken/paCker-php`,
then enable the GitHub hook so new tags appear automatically.

New version: `python tools/build_composer.py` stages `release/<version>/composer`; copy its files into
the package repository, commit, tag `v<version>` and push the tag.

## Local builds

```sh
python tools/build_wheels.py dist        # both wheels, on Windows or Linux with Zig on PATH
python tools/build_composer.py           # release/<version>/composer, a Git repository tagged v<version>
```

## Version bump

Update `OP_VERSION`/`OP3_VERSION`, `CMakeLists.txt`, `python/pyproject.toml`, `packer3d.__version__`,
`VERSION` in `tools/build_composer.py`, the schema 2 version constant, and the version lists in the PHP
facade and tests.
