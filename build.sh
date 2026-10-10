#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
out=build
opt='-O2'
while [ "$#" -gt 0 ]; do
  case "$1" in
    --debug) opt='-O0 -g'; shift ;;
    --output-dir) out=$2; shift 2 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done
mkdir -p "$out"
compile() { ${CC:-cc} -std=c11 $opt -Wall -Wextra -Werror -Iinclude "$@"; }
for source in oblique geometry3d packer3d search3d; do
  compile -fPIC -c "src/$source.c" -o "$out/$source.o"
done
${AR:-ar} rcs "$out/liboblique.a" "$out/oblique.o"
${AR:-ar} rcs "$out/libpacker3d.a" "$out/geometry3d.o" "$out/packer3d.o" "$out/search3d.o" "$out/oblique.o"
case "$(uname -s)" in
  Darwin) shared='-dynamiclib'; extension=dylib ;;
  *) shared='-shared'; extension=so ;;
esac
${CC:-cc} $shared "$out/oblique.o" -lm -o "$out/liboblique.$extension"
${CC:-cc} $shared "$out/geometry3d.o" "$out/packer3d.o" "$out/search3d.o" "$out/oblique.o" -lm -o "$out/libpacker3d.$extension"
compile src/cli.c src/json3d.c third_party/cJSON.c "$out/liboblique.a" "$out/libpacker3d.a" -lm -o "$out/packer"
compile tests/test_core.c "$out/liboblique.a" -lm -o "$out/test_core"
compile tests/test_geometry3d.c "$out/geometry3d.o" -lm -o "$out/test_geometry3d"
compile tests/test_free3d.c "$out/libpacker3d.a" -lm -o "$out/test_free3d"
compile tests/test_json3d.c src/json3d.c third_party/cJSON.c "$out/libpacker3d.a" -lm -o "$out/test_json3d"
compile tests/search3d_refinement.c "$out/geometry3d.o" -lm -o "$out/test_search3d_refinement"
compile examples/ordinary.c "$out/liboblique.a" -lm -o "$out/ordinary_example"
compile examples/free3d.c "$out/libpacker3d.a" -lm -o "$out/free3d_example"
for name in test_core test_geometry3d test_free3d test_json3d test_search3d_refinement ordinary_example free3d_example; do
  "$out/$name"
done
if command -v "${CXX:-c++}" >/dev/null 2>&1; then
  ${CXX:-c++} -std=c++11 -Wall -Wextra -Werror -Iinclude tests/cpp_link.cpp "$out/liboblique.a" "$out/libpacker3d.a" -lm -o "$out/cpp_link"
  "$out/cpp_link"
fi
printf 'Built native CLI, ordinary/geometric libraries and C examples in %s\n' "$out"
