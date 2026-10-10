$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    New-Item -ItemType Directory -Path .tools -Force | Out-Null
    $compiler = '.tools\zig-x86_64-windows-0.15.2\zig.exe'
    if (!(Test-Path -LiteralPath $compiler)) {
        Invoke-WebRequest 'https://ziglang.org/download/0.15.2/zig-x86_64-windows-0.15.2.zip' -OutFile '.tools\zig.zip'
        if ((Get-FileHash '.tools\zig.zip' -Algorithm SHA256).Hash.ToLowerInvariant() -ne '3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c') { throw 'Compiler checksum mismatch' }
        Expand-Archive -LiteralPath '.tools\zig.zip' -DestinationPath '.tools' -Force
    }
    & ./build.ps1
} finally { Pop-Location }
