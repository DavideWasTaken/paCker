# Geometric C API (development)

`include/packer3d.h` exposes the separate C11 API `op3_default_options()` and
`op3_pack()`. The ordinary `oblique.h` ABI and schema 1 are unchanged. This API models
geometric cuboids with user-supplied padding; it does not model mechanical
support, gravity, friction or insertion paths. The optional CLI/PHP integration
is documented in [the schema 2 contract](schema2.md).

Run `./build.ps1` on Windows or `sh build.sh` on Linux. They build the CLI,
ordinary and geometric static/shared libraries, API tests, `ordinary_example`
and `free3d_example` in `build/`. With the Windows Zig compiler the geometric libraries are
`libpacker3d.a`, `packer3d.dll`, and the DLL import library `libpacker3d.dll.a`.
Linux produces `libpacker3d.a` and `libpacker3d.so`. Both scripts run C tests.

Alternatively run `cmake -S . -B build/cmake`, `cmake --build build/cmake`,
and `ctest --test-dir build/cmake --output-on-failure`, then run
`build/cmake/free3d_example` (Windows multi-config generators add `Release/`).
The `packer3d` static target produces a self-contained archive;
`packer3d_shared` produces a shared library.
The runnable source is `examples/free3d.c`. Applications can call `op3_pack()`
in their own process, without PHP, JSON conversion or process startup. Windows
shared-library builds export the API functions.
On Windows CMake names the static library `packer3d_static` to avoid colliding
with the shared library's import library. Both the CMake and script-built static
archives include their geometry code; there is no additional geometry archive
to link manually.
Use the matching header and library. `OP3_VERSION` identifies the header
version; `op3_version()` returns the version of the linked geometric engine,
currently `0.4.1-free3d-dev`. Ordinary responses use `0.4.1`. The geometric library now contains the ordinary engine too: for
orders without `free3d` and with zero clearance, `op3_pack()` seeds its search
with an `op_pack()` layout (contact support, improvement on, half the budget).
To build only the native API with CMake, use
`cmake --build build/cmake --target packer3d packer3d_shared free3d_example`.
Neither PHP nor Python is needed to build or call the C API.

For an application using the ordinary API, include `oblique.h` and link
`liboblique.a`; for geometric packing, include `packer3d.h` and link
`libpacker3d.a`. With the standard Linux build, the complete examples can also
be compiled as consumers:

```sh
cc -std=c11 -Iinclude examples/ordinary.c build/liboblique.a -lm -o ordinary_example
cc -std=c11 -Iinclude examples/free3d.c build/libpacker3d.a -lm -o free3d_example
```

For shared linking use the matching `.so` or Windows DLL import library and
make the shared library available to the operating system loader. The static
archives avoid that runtime deployment step. Both public headers have C++
linkage guards; the engine itself remains C11. The native distribution keeps
headers in `include/`, libraries in `lib/`, and executables in `bin/`.

Initialize options with `op3_default_options`, fill the request and call:

```c
Op3Request request = {0};
Op3Result result;
char error[128];
op3_default_options(&request.options);
/* Fill request.items/boxes and item_count/box_count; see examples/free3d.c. */
int rc = op3_pack(&request, &result, error, sizeof error);
```

The caller expands quantities into at most 256 items. Each `(id, instance)` is
unique. Up to 64 box types use quantity `-1` for unlimited stock, `0` for none.
Return `0` means a valid request and valid complete or partial packing. Return
`1` means invalid arguments or allocation failure, with a zeroed result and
bounded diagnostic. Empty orders are complete; zero box types return a valid
partial result for nonempty orders. `error` may be NULL or its size nonpositive.

Placements retain original dimensions, a center, and a canonical active
local-to-world quaternion `[x,y,z,w]`. Save doubles with 17 significant digits.
Every retained double pose is canonicalized before the conservative interval
geometry checks. Uncertainty rejects a candidate; it never relaxes tolerances.
Wall clearance and half-axis expansion between items follow the public header.

Rotation permissions remain per item: `NONE` is identity; `FLAT` keeps original
positive Z and permits yaw; `ANY` selects a face and yaw; `FREE3D` permits tilt.
Disabling diagonal permission restricts `FLAT`/`ANY` to orthogonal orientations;
`FREE3D` with diagonal disabled is an error. The geometric XY control replaces
only `FREE3D` with `ANY` in a copied request and uses the same search mechanisms.

The objective is lexicographic: unpacked count, cost, bins, original box volume.
A small beam, multiple orders, dimension-directed and distributed attitudes,
contact planes and local quaternion/position refinement explore alternatives.
Search is finite and heuristic; partial results do not prove impossibility.

All work shares a monotonic cooperative deadline, including preparation,
generation, deduplication and refinement. A full candidate is one canonical
double pose submitted to containment/pair checks. `candidates` never exceeds
the requested limit. The initial XY stage for requests containing `FREE3D`
uses at most one quarter of that candidate budget and a deadline at one quarter
of the global time; it can finish early. `xy_candidates` and `xy_elapsed_ms`
report actual initialization work. A phase limit never asserts global stop
flags. Single validation calls can overrun a deadline; actual elapsed time is
reported. Candidate-bounded runs with ample time replay deterministically;
time-based outcomes may vary.

`stop_reason` distinguishes completed/exhausted search from global time or
candidate stops; stop flags remain present even when the incumbent is complete.
`restarts` counts unique orderings started, including those reused in both
phases. Search state is per call, and it never changes caller FPU settings.

`tests/free3d_capi.py` is a small ctypes binding of this API used by the tests;
it emits round-trippable schema 2 JSON that `packer_adapter.validation_3d`
checks independently. Free 3D search can find worse layouts than the
orthogonal search at the same budget on ordinary orders: enable `free3d` for
products that need inclination.
