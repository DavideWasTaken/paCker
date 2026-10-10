# Geometric JSON and PHP (development)

The standalone C API remains available without JSON, PHP or Python; see
[the C API guide](free3d-c-api.md). The optional CLI reads one strict UTF-8 JSON
request from stdin or a file and writes one JSON result. Invalid input returns
a nonzero exit code and `{"error":"..."}`. Input limits are 1 MiB, nesting
depth 16, 64 box types, 256 expanded items and 63 UTF-8 bytes per ID.
Duplicate JSON members and duplicate type IDs are errors.

Set `options.support_mode` to `"geometric"` to obtain schema 2. Omitting it, or
using `"stable"` (the default), `"contact"` or `"full_base"`, selects ordinary packing and schema 1.
Without `free3d` products and with zero clearance, geometric mode starts from the
ordinary engine's layout (converted to schema 2 and rechecked with the geometric
predicates) and spends the rest of its budget trying to improve it.
Geometric mode allows `rotation: "free3d"` per item; it requires
`diagonal: true` (the default). Other items retain `none`, `flat` or `any`.
`none` preserves original axes, `flat` preserves original positive Z and allows
yaw, and `any` selects a face and allows yaw. Disabling diagonals restricts
`flat`/`any` to orthogonal attitudes. `free3d` in ordinary mode is an error.

`clearance` defaults to zero, accepts finite values from 0 to 1e6, and requires
wall separation and expansion of each item's local half-sides by half the
margin for pair checks. This pair rule is not an exact Euclidean offset.
Geometric mode rejects a nonzero `gap`; zero is accepted. Ordinary mode rejects
the `clearance` field even when its value is zero.

Padding is supplied by the user. Geometric results check containment and
separation within the documented numerical tolerance; they do not certify
support, gravity, friction, deformation, padding design or insertion paths.
Search is finite and heuristic. A partial result does not prove impossibility.

Schema 2 includes `schema_version: 2`, `support_mode: "geometric"`, effective
`clearance`, and the engine `version` (`0.5.0-free3d-dev` during development).
Every item retains its original `width`, `length`, `height`, identity, instance
and weight. Its pose is a `center: [cx,cy,cz]` and an active local-to-container
`orientation: [qx,qy,qz,qw]`. Coordinates are right-handed with X as width, Y as
length and Z as height. Quaternions have squared norm error at most 1e-12 and
canonical sign: first nonzero component in w,x,y,z order positive. Their
mathematically normalized rotation defines the geometry. Schema 2 has no
`x/y/z/angle` placement fields. All doubles serialize with 17 significant
digits; signed zero uses a decimal token to preserve floating-point decoding.

Bins use sequential `bin-1`, `bin-2`, ... IDs. Unpacked instances, costs,
stock and weights use the same identity conventions as ordinary requests.
`stats.options` records all effective options, including seed and zero gap;
`stats.seed` also exposes the effective seed. `stats.stop_reason` is one of
`completed`, `search_exhausted`, `time_limit`, or `candidate_limit`.
The time/candidate flags describe global stops even when the incumbent is
complete. `xy_candidates` and `xy_elapsed_ms` report actual initialization work.
The cooperative engine deadline excludes JSON and process startup; actual
elapsed time is reported. Candidate-bounded runs with ample time replay;
time-bounded results can vary.

Machine-readable structural contracts are in
[request-v2.json](../schemas/request-v2.json) and
[result-v2.json](../schemas/result-v2.json). Cross-field constraints, UTF-8 byte
limits, quaternion normalization, geometry and accounting require validation
against the original request in addition to JSON Schema validation.

The PHP 8.1+ facade keeps `addBox()`, `addItem()`, `setOptions()` and `pack()`.
It recognizes both response schemas and checks request identities, dimensions,
quantities, stock, weights, statistics and effective options. Schema 2 checks
also cover quaternion convention, rotation permissions, containment and pair
clearance. PHP uses its own double arithmetic for these additional checks; the
C API validates retained exact double poses with conservative interval geometry.
The wrapper requires `proc_open` and the compiled executable, with no Python
runtime. Run `php examples/php-free3d.php [path/to/packer]` for the tilted rod.
Keep PHP's `serialize_precision=-1` default when exporting the returned array
so the engine's double values survive another JSON encoding.
