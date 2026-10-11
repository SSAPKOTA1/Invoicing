# Starts a throw-away PostgreSQL server on a GitHub Actions Windows runner (binaries of the runner image, private
# data folder, trust authentication, port 54329) and exports its connection string to the following steps:
# SUPPLIER_TEST_PG_DSN for the tests, SUPPLIERAPP_PG_DSN for the program.
$ErrorActionPreference = "Stop"

$bin = $null
if ($env:PGBIN -and (Test-Path (Join-Path $env:PGBIN "initdb.exe"))) { $bin = $env:PGBIN }
if (-not $bin) {
    $found = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName "bin" } |
        Where-Object { Test-Path (Join-Path $_ "initdb.exe") } | Select-Object -First 1
    if ($found) { $bin = $found }
}
if (-not $bin) {
    choco install postgresql16 --params "/Password:ci" --no-progress -y
    $bin = "C:\Program Files\PostgreSQL\16\bin"
}
Write-Host "PostgreSQL binaries: $bin"

$data = Join-Path $env:RUNNER_TEMP "pgdata"
$log = Join-Path $env:RUNNER_TEMP "pg.log"
& "$bin\initdb.exe" -D $data -U postgres -A trust -E UTF8 --locale=C
if ($LASTEXITCODE -ne 0) { throw "initdb failed" }
& "$bin\pg_ctl.exe" start -D $data -l $log -w -t 60 -o "-p 54329 -c fsync=off -c synchronous_commit=off -c max_connections=200"
if ($LASTEXITCODE -ne 0) { Get-Content $log -ErrorAction SilentlyContinue; throw "pg_ctl start failed" }

$dsn = "host=127.0.0.1 port=54329 user=postgres dbname=postgres"
"SUPPLIER_TEST_PG_DSN=$dsn" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"SUPPLIERAPP_PG_DSN=$dsn" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Host "PostgreSQL ready."
