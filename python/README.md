# packer3d

Fast 3D cuboid packing for Python. Give it box types and products; it returns which boxes to use and
where every product goes. The native C engine is bundled in the wheel for Windows x64 and Linux x64
(static, any distribution): no compiler, no dependencies. Python 3.10+.

```sh
pip install packer3d
```

```python
from packer3d import Packer

packer = Packer()
packer.add_box(id='small', width=300, length=200, height=150, max_weight=5000)
packer.add_box(id='large', width=600, length=400, height=300, max_weight=20000, quantity=2)
packer.add_item(id='book', width=240, length=170, height=30, weight=400, quantity=6)
packer.add_item(id='mug', width=120, length=120, height=100, weight=350, rotation='any')
result = packer.pack()

for box in result['bins']:
    print(box['type_id'], [(p['id'], p['x'], p['y'], p['z']) for p in box['items']])
print('not packed:', result['unpacked'])
```

## What it respects

- Box interior dimensions, no overlaps, weight limit per box, finite stock per box type.
- Rotations per product: `none`, `flat` (keep height, default) or `any`; optional diagonal yaw.
- Support: `contact` (default: every product rests on the floor or on another product, nothing floats),
  `full_base` (whole footprint supported) or `geometric` (free 3D rotation, no support rule).
- Objective: fewest unpacked products, then lowest box cost, fewest boxes, smallest box volume.

Useful options via `set_options(...)`: `time_limit_ms` (default 1000), `improve=True` (keep searching
until the time limit or a proven optimum), `support_mode`, `gap`. Results report `lower_bound` and
`proven_optimal`. Errors raise `PackerError`.

On other platforms, build the CLI from the source repository and set `PACKER_BINARY`, or pass
`Packer(binary='/path/to/packer')`.

## Extras

- `packer_adapter.validation_ordinary.validate(request, result)`: independent result checker.
- `pip install "packer3d[mcp]"`: local MCP server for agents (`packer-mcp`).
- `pip install "packer3d[images]"` plus `python -m playwright install chromium`: PNG rendering.

MIT licensed; the bundled engine includes cJSON (MIT) and the rendering assets include Three.js (MIT).
