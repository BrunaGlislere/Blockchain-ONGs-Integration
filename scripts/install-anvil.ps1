$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $project '.tools'
$target = Join-Path $tools 'anvil.exe'
if (Test-Path -LiteralPath $target) {
    & $target --version
    exit $LASTEXITCODE
}
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'Use um binário Anvil compatível com o sistema e configure ONG_ANVIL.'
}
New-Item -ItemType Directory -Path $tools -Force | Out-Null
npm.cmd install --prefix $tools --no-audit --no-fund --ignore-scripts '@foundry-rs/anvil-win32-amd64@1.7.1'
if ($LASTEXITCODE -ne 0) { throw 'Falha ao obter Anvil pelo npm.' }
Copy-Item -LiteralPath (Join-Path $tools 'node_modules/@foundry-rs/anvil-win32-amd64/bin/anvil.exe') -Destination $target
& $target --version
