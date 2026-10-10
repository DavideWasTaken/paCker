# MCP server

paCker ships a local [MCP](https://modelcontextprotocol.io) server, so an AI agent can pack real
orders instead of guessing. The agent supplies boxes, products and constraints; the C engine finds
the layout and an independent validator checks it before anything is returned. It runs locally over
stdio, keeps no state and opens no network port.

## Quick start

```sh
pip install "packer3d[mcp]"
```

This installs the `packer-mcp` command with the engine bundled (Windows x64 and Linux x64,
Python 3.10+). Then register it with your client.

**Claude Code**

```sh
claude mcp add packer -- packer-mcp
```

**Claude Desktop, Cursor and other clients** that use an `mcpServers` file:

```json
{
  "mcpServers": {
    "packer": { "command": "packer-mcp" }
  }
}
```

If the client cannot find `packer-mcp` on its `PATH`, use the full path of the command inside the
environment where you installed it, for example `C:\\path\\to\\venv\\Scripts\\packer-mcp.exe` or
`/path/to/venv/bin/packer-mcp`.

Ask something like *"Pack 12 books 240×170×30 mm and 4 mugs 120×90×100 mm into cartons of
300×200×150 or 500×400×300"* and the agent calls `pack_order`.

### Images (optional)

To let tools return PNG renders of the packed boxes:

```sh
pip install "packer3d[mcp,images]"
python -m playwright install chromium
```

On Linux, `python -m playwright install --with-deps chromium` also installs Chromium's system
libraries. Without it, everything works except images: a render request returns the verified
packing with a `render_error`.

## Tools

| Tool | Arguments | What it does |
|---|---|---|
| `pack_order` | `request`, optional `include_image`, `box_indexes` or `box_ids`, `view` | Solves the order, validates the result and optionally adds PNGs. |
| `validate_packing` | `request`, `result` | Checks an existing result: quantities, geometry, weights, support and statistics. |
| `render_packing` | `request`, `result`, optional `box_indexes` or `box_ids`, `view` | Validates an existing result and returns PNGs, without solving again. |
| `get_capabilities` | none | Versions, schemas, limits, modes and whether rendering is available. |

`request` is exactly the [CLI request](../README.md#quick-start): `boxes`, `items` and optional `options`
(see [rules and options](../README.md#rules-and-options)).
Dimensions are in any consistent unit (millimetres in the examples), weights likewise.

```json
{
  "request": {
    "boxes": [
      {"id": "small", "width": 300, "length": 200, "height": 150, "max_weight": 5000},
      {"id": "large", "width": 500, "length": 400, "height": 300, "quantity": 2}
    ],
    "items": [
      {"id": "book", "width": 240, "length": 170, "height": 30, "weight": 400, "quantity": 12},
      {"id": "mug", "width": 120, "length": 90, "height": 100, "weight": 350, "quantity": 4, "rotation": "any"}
    ],
    "options": {"time_limit_ms": 1000}
  },
  "include_image": true,
  "view": "isometric"
}
```

- `rotation`: `flat` (default, keeps the height), `any` or `none`.
- `options.support_mode`: `stable` (default), `contact`, `full_base` or `geometric`. For geometric
  packing set an item's `rotation` to `free3d`; see [schema 2](schema2.md) for its pose format.
- `options.improve: true` keeps searching until the time limit or a proven optimum.
- `view`: `isometric` (default) or `top`. `box_indexes` are zero-based positions in `result.bins`;
  `box_ids` are packed-box IDs such as `bin-1`. Omit both to render every box.

## Responses

Every call except `get_capabilities` returns the same envelope as structured content, plus a text
copy for older clients and one image block per PNG:

```json
{
  "packing": {"status": "complete", "bins": [], "unpacked": [], "stats": {}},
  "validation": {"status": "valid", "valid": true, "violations": []},
  "rendering": {"status": "not_requested", "images": [], "omitted": []},
  "timings": {"solver_ms": 0, "validation_ms": 0, "render_ms": 0, "total_ms": 0},
  "error": null
}
```

`packing` is the engine output unchanged, including `stats.lower_bound` and `stats.proven_optimal`.
Products that do not fit give `status: "partial"` with the `unpacked` list; that is still a
successful call.

On failure `isError` is true and `error.code` is one of `invalid_input`, `incompatible_engine`,
`engine_error`, `invalid_result`, `validation_error`, `validation_timeout` or `render_error`. A
result that fails validation is never returned as a success or rendered.

## Limits

- 64 box types, 256 products after expanding quantities, 1 MiB request.
- Identifiers of 1–63 bytes; dimensions from 0.0001 to 1,000,000. Unknown fields are rejected.
- Engine deadline 70 s, validation 30 s.
- Images are 1024×768, at most four per response and 4 MiB in total; further boxes are listed in
  `rendering.omitted` and can be requested with `render_packing`.

## Other platforms and source builds

On platforms without a bundled engine, build the CLI from this repository (`./build.sh` or
`./build.ps1`) and point the server at it:

```sh
pip install "./python[mcp]"
packer-mcp --binary /absolute/path/to/packer
```

`PACKER_BINARY` works too, as in [examples/mcp-config.json](../examples/mcp-config.json). The server
checks the engine's capabilities at start and refuses an incompatible build. Protocol messages go to
stdout, diagnostics to stderr.

## Tests

```sh
python -m unittest discover -s tests -p test_mcp.py
```

The tests drive the server through a real MCP stdio client: discovery, ordinary, geometric and
partial packings, invalid input and results, engine failures, validation timeouts, cancellation,
missing Chromium and PNG output. Tests that need an optional extra skip when it is not installed.
