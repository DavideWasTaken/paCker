param([switch]$Debug, [string]$OutputDir = 'build')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $out = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $OutputDir))
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    $compiler = Join-Path $PSScriptRoot '.tools\zig-x86_64-windows-0.15.2\zig.exe'
    if (!(Test-Path -LiteralPath $compiler)) {
        $zigCommand = Get-Command zig -ErrorAction SilentlyContinue
        if ($zigCommand) { $compiler = $zigCommand.Source }
    }
    $configuration = if ($Debug) { 'Debug' } else { 'Release' }
    if (Test-Path -LiteralPath $compiler) {
        $flags = @('-std=c11', '-Wall', '-Wextra', '-Werror', '-Iinclude')
        $flags += if ($Debug) { @('-O0', '-g') } else { @('-O2') }
        function Compile-C {
            & $compiler cc @flags @args
            if ($LASTEXITCODE) { throw "C compilation failed: $args" }
        }
        foreach ($source in @('oblique', 'geometry3d', 'packer3d', 'search3d')) {
            Compile-C -c "src/$source.c" -o "$out/$source.o"
        }
        & $compiler ar rcs "$out/liboblique.a" "$out/oblique.o"
        if ($LASTEXITCODE) { throw 'Ordinary static library creation failed' }
        & $compiler ar rcs "$out/libpacker3d.a" "$out/geometry3d.o" "$out/packer3d.o" "$out/search3d.o" "$out/oblique.o"
        if ($LASTEXITCODE) { throw 'Geometric static library creation failed' }
        & $compiler cc -shared "$out/oblique.o" "-Wl,--out-implib,$out/liboblique.dll.a" -o "$out/oblique.dll"
        if ($LASTEXITCODE) { throw 'Ordinary shared library creation failed' }
        & $compiler cc -shared "$out/geometry3d.o" "$out/packer3d.o" "$out/search3d.o" "$out/oblique.o" "-Wl,--out-implib,$out/libpacker3d.dll.a" -o "$out/packer3d.dll"
        if ($LASTEXITCODE) { throw 'Geometric shared library creation failed' }
        Compile-C src/cli.c src/json3d.c third_party/cJSON.c "$out/liboblique.a" "$out/libpacker3d.a" -o "$out/packer.exe"
        Compile-C tests/test_core.c "$out/liboblique.a" -o "$out/test_core.exe"
        Compile-C tests/test_geometry3d.c "$out/geometry3d.o" -o "$out/test_geometry3d.exe"
        Compile-C tests/test_free3d.c "$out/libpacker3d.a" -o "$out/test_free3d.exe"
        Compile-C tests/test_json3d.c src/json3d.c third_party/cJSON.c "$out/libpacker3d.a" -o "$out/test_json3d.exe"
        Compile-C tests/search3d_refinement.c "$out/geometry3d.o" -o "$out/test_search3d_refinement.exe"
        Compile-C examples/ordinary.c "$out/liboblique.a" -o "$out/ordinary_example.exe"
        Compile-C examples/free3d.c "$out/libpacker3d.a" -o "$out/free3d_example.exe"
        & $compiler c++ -std=c++11 -Wall -Wextra -Werror -Iinclude tests/cpp_link.cpp "$out/liboblique.a" "$out/libpacker3d.a" -o "$out/cpp_link.exe"
        if ($LASTEXITCODE) { throw 'C++ consumer link failed' }
    } else {
        # Output paths are fixed for this build/profile; never select a stale recursive match.
        cmake -S . -B "$out/cmake" "-DCMAKE_BUILD_TYPE=$configuration" "-DPACKER_OUTPUT_DIRECTORY=$out"
        if ($LASTEXITCODE) { throw 'CMake configuration failed: install a C compiler and CMake or run setup.ps1' }
        cmake --build "$out/cmake" --config $configuration
        if ($LASTEXITCODE) { throw 'Compilation failed' }
    }
    foreach ($name in @('test_core','test_geometry3d','test_free3d','test_json3d','test_search3d_refinement','ordinary_example','free3d_example')) {
        & "$out/$name.exe"
        if ($LASTEXITCODE) { throw "Native check failed: $name" }
    }
    if (Test-Path -LiteralPath "$out/cpp_link.exe") {
        & "$out/cpp_link.exe"
        if ($LASTEXITCODE) { throw 'C++ consumer check failed' }
    }
    Write-Host "Built $configuration native CLI, ordinary/geometric libraries and C examples in $out"
} finally { Pop-Location }
