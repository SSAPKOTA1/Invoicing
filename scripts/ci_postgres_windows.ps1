# Makes a PostgreSQL server available on a GitHub Actions Windows runner and exports its connection string
# (SUPPLIER_TEST_PG_DSN for the tests, SUPPLIERAPP_PG_DSN for the program) to the following steps.
$ErrorActionPreference = "Stop"

function Test-Dsn([string]$dsn) {
    & python -c "import psycopg,sys; psycopg.connect(sys.argv[1], connect_timeout=5).close()" $dsn 2>$null
    return ($LASTEXITCODE -eq 0)
}

$candidates = @("root", "postgres", "ci")
$dsn = $null

# 1. the PostgreSQL that is part of the runner image (service installed, not started)
$svc = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($svc) {
    if ($svc.Status -ne "Running") { Start-Service $svc.Name; Start-Sleep -Seconds 5 }
    foreach ($pw in $candidates) {
        $try = "host=127.0.0.1 port=5432 user=postgres password=$pw dbname=postgres"
        if (Test-Dsn $try) { $dsn = $try; break }
    }
}

# 2. otherwise install it
if (-not $dsn) {
    choco install postgresql16 --params "/Password:ci" --no-progress -y
    Start-Sleep -Seconds 10
    $try = "host=127.0.0.1 port=5432 user=postgres password=ci dbname=postgres"
    if (Test-Dsn $try) { $dsn = $try }
}

if (-not $dsn) { throw "No PostgreSQL server could be reached on this runner." }
"SUPPLIER_TEST_PG_DSN=$dsn" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"SUPPLIERAPP_PG_DSN=$dsn" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Host "PostgreSQL ready."
