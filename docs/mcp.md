# Local MCP adapter

paCker exposes four stateless tools over local stdio. The C executable solves the
order; independent Python verifiers check its original result; optional Chromium
images show those same final poses. An agent supplies actual product dimensions,
quantities, box dimensions, and constraints. No model invents coordinates.

## Install and start

Build the CLI from this checkout with `./build.ps1` on Windows or `./build.sh` on
Linux. This build includes `--capabilities`. An earlier ordinary-only binary may
also report an older version; version text alone is insufficient and the adapter
rejects an incompatible capability handshake.

Python 3.10 or newer is required. From the repository root:

```sh
python -m venv .venv
# Activate .venv using your shell, then:
python -m pip install "./python[mcp,images]"
python -m playwright install chromium
```

On Linux, install Chromium system dependencies using your distribution's normal
administrative workflow, or `python -m playwright install --with-deps chromium`.
The optional `images` extra is unnecessary for numeric tools. Install
`"./python[mcp]"` to use MCP without Playwright. Independent validation alone
requires `./python` and has no third-party dependencies.

Direct runtime dependencies are pinned in `python/pyproject.toml`. Exact observed
MCP and image dependency environments are recorded in
`python/requirements-windows.lock` (Python 3.13.12) and
`python/requirements-linux.lock` (Python 3.14.4). To reproduce the applicable
environment, install its lockfile first and then install the local project with
`python -m pip install --no-deps ./python`. These locks do not claim verification
on every supported Python version. Chromium is installed separately by
Playwright 1.63.0.

Configure the executable outside tool input:

```sh
python -m packer_adapter.mcp_server --binary /absolute/path/to/packer
```

Alternatively set `PACKER_BINARY`, then run `packer-mcp` or
`python -m packer_adapter.mcp_server`. On Windows use the installed
`venv\Scripts\python.exe` and an absolute path to `packer.exe`. Paths containing
spaces work because processes receive separate arguments, never a shell command.
The server writes protocol messages to stdout and diagnostics to stderr.

Adapt `examples/mcp-config.json` to the local client's configuration format. Its
`mcpServers` envelope is a common client convention, not a universal MCP setting.
The Python interpreter must belong to the environment where the adapter was
installed. If you set `PLAYWRIGHT_BROWSERS_PATH` during browser installation, pass
the same setting in the server environment. No server URL or HTTP listener is
used. Installing this package does not change any global agent configuration.

## Tools and data

| Tool | Arguments | Behavior |
|---|---|---|
| `get_capabilities` | `{}` | Engine versions, result schemas, modes, limits, geometric conventions, and installed renderer availability. Availability detects the Chromium executable; rendering verifies that it can launch. |
| `pack_order` | `request`, optional `include_image`, `box_indexes` or `box_ids`, `view` | One C solve, independent validation, and optional PNGs. `include_image` defaults to `false`. |
| `validate_packing` | Original `request` and `result` | Checks identities, quantities, geometry, constraints, and statistics; returns violations with JSON locations where applicable. |
| `render_packing` | Original `request` and `result`, optional `box_indexes` or `box_ids`, `view` | Validates and renders the original result without running the solver. |

All advertised input objects are closed. `request` is exactly the CLI request,
with `boxes`, `items`, and optional `options`; there is no second solver format.
Result input accepts the original ordinary CLI result or the documented schema-2
result, with their declared fields. Unknown pose aliases and arbitrary paths,
URLs, or commands are rejected. `view` is `isometric` (default) or `top`.
`box_indexes` are zero-based indexes in `result.bins`; `box_ids` are packed-box
IDs such as `bin-1`, not source box type IDs. Supply at most one selection form.
Selections must be unique and identify existing packed boxes. An omitted
selection means all packed boxes; an empty list requests none.

Example `pack_order` arguments:

```json
{
  "request": {
    "boxes": [{"id": "carton", "width": 100, "length": 100, "height": 100, "quantity": 1}],
    "items": [{"id": "product", "width": 40, "length": 30, "height": 20, "quantity": 2}],
    "options": {"seed": 42, "max_candidates": 200000, "time_limit_ms": 1000}
  },
  "include_image": true,
  "box_indexes": [0],
  "view": "isometric"
}
```

For geometric packing set `options.support_mode` to `geometric` and, when needed,
an item's `rotation` to `free3d`. `gap` must be zero; optional `clearance` is the
geometric margin. `free3d` requires `diagonal: true` (the default). Geometric mode
assumes padding supplied by the user and checks neither gravity nor insertion
paths. See [schema 2](schema2.md) for its center/quaternion convention. Ordinary
mode defaults to `stable` support (`contact` or `full_base` on request) and accepts
`improve: true`; it forbids `free3d` and `clearance`.

The CLI and adapter enforce 64 box types, 256 expanded product instances, 1 MiB
request JSON, nesting depth 16, and identifiers of 1–63 UTF-8 bytes. Dimensions
are finite numbers from 0.0001 to 1,000,000; booleans and numeric strings are not
dimensions. Quantities, stock, weights, costs, and search options retain their
CLI bounds, exposed in discovery schemas. Duplicate type IDs, non-finite values,
unknown fields, and incompatible options fail before search. Omitted optional
values retain the CLI defaults; required dimensions are never supplied by the
adapter.

Packing, validation, and rendering calls return `structuredContent`:

```json
{
  "packing": {"status": "complete", "bins": [], "unpacked": [], "stats": {}},
  "validation": {"status": "valid", "valid": true, "violations": []},
  "rendering": {"status": "not_requested", "images": [], "omitted": []},
  "timings": {"solver_ms": 0, "validation_ms": 0, "render_ms": 0, "total_ms": 0},
  "error": null
}
```

This is a shortened envelope illustration, not a complete solver result.
`packing` contains the unmodified numeric C output. A valid partial result is a
successful tool response with `packing.status: "partial"` and its original
unpacked list. Ordinary stop flags remain in `packing.stats`; geometric output
also supplies `stop_reason`. No completeness or optimality guarantee is added.

Requested PNGs appear in actual MCP image content blocks with `mimeType:
"image/png"`; numeric content is also available as a text block for older
clients. Rendering metadata identifies each box, view, dimensions, camera,
scene items, omissions, cold/warm browser state, and PNG byte count. Images are
1024×768, with at most four PNGs and 4 MiB of raw PNG data per response. Extra
boxes or images beyond the byte budget are listed in `rendering.omitted`.
Numeric packing is retained in full; request other boxes in a subsequent
`render_packing` call.

`isError: true` and `error.code` distinguish `invalid_input`,
`incompatible_engine`, `engine_error`, `invalid_result`, `validation_error`,
`validation_timeout`, and `render_error`. Invalid geometry is never successful
or rendered. A rendering-only failure retains the independently verified packing
and provides diagnostics, even when Playwright or Chromium is absent. The
configured engine runs with a 70-second process deadline, bounded 4 MiB stdout
and 64 KiB stderr. Independent validation runs in a separate fixed Python worker
with a 30-second deadline, bounded input/output, and termination/reaping on
failure or cancellation. Rendering revalidation uses the same boundary, rather
than blocking the MCP event loop. One asynchronous browser is reused during the
server lifespan; each scene receives an isolated context.

`solver_ms` includes CLI startup, I/O, and the initial capability handshake when
needed; internal solve time remains `packing.stats.elapsed_ms`.
`validation_ms` includes worker startup and checks, including renderer
revalidation. `render_ms` measures rendering, and `total_ms` measures the complete
tool operation. They are diagnostics, not performance claims.

## Verification

With the relevant extras and Chromium installed, run from the repository root:

```sh
python -m unittest discover -s tests -p test_python_adapter.py
python -m unittest discover -s tests -p test_mcp.py
python -m unittest discover -s tests -p test_render.py
```

Adapter and MCP test classes skip when their optional dependencies are missing.
Tests use actual SDK stdio initialize/discovery/calls, ordinary/geometric and
partial results, closed schemas, bad input/results, bounded process failures,
validation timeouts/crashes, cancellation, missing Chromium, PNG decoding,
renderer lifecycle, and PHP/MCP numeric equality with identical input and no time
stop. PNG correspondence is checked against original scene items and poses;
pixel-for-pixel equality across GPUs is not required.

An MCP client that supports image content receives the PNG blocks; display
behavior can differ between clients.
