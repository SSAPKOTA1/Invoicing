<#
 Builds the self-contained Windows package (no Python / Tesseract needed on the target PC).

   powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1

 Steps: PyInstaller one-folder build -> copy tesseract.exe + DLLs + tessdata (deu, eng, osd) into
 dist\SupplierApp\tesseract -> zip to dist\SupplierApp-windows-x64.zip.
 Requires: Python 3.11 with requirements-dev.txt installed and Tesseract installed (see ci.yml).
#>
param(
    [string]$TesseractDir = "",
    [string]$OutZip = "dist\SupplierApp-windows-x64.zip"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- locate the Tesseract installation -------------------------------------------------------
if (-not $TesseractDir) {
    $candidates = @("$env:ProgramFiles\Tesseract-OCR", "${env:ProgramFiles(x86)}\Tesseract-OCR", "C:\Program Files\Tesseract-OCR")
    $cmd = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($cmd) { $candidates = @((Split-Path -Parent $cmd.Source)) + $candidates }
    $TesseractDir = $candidates | Where-Object { $_ -and (Test-Path (Join-Path $_ "tesseract.exe")) } | Select-Object -First 1
}
if (-not $TesseractDir -or -not (Test-Path (Join-Path $TesseractDir "tesseract.exe"))) {
    throw "tesseract.exe not found. Install Tesseract (e.g. 'choco install tesseract') or pass -TesseractDir."
}
Write-Host "Using Tesseract from $TesseractDir"

# --- make sure the German and English language data exist -----------------------------------------
$tessdata = Join-Path $TesseractDir "tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null
foreach ($lang in @("deu", "eng", "osd")) {
    $file = Join-Path $tessdata "$lang.traineddata"
    if (-not (Test-Path $file)) {
        Write-Host "Downloading $lang.traineddata"
        Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$lang.traineddata" -OutFile $file
    }
}

# --- PyInstaller ---------------------------------------------------------------------------------------
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist\SupplierApp) { Remove-Item -Recurse -Force dist\SupplierApp }
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\SupplierApp.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# --- bundle Tesseract ---------------------------------------------------------------------------------------
$target = Join-Path $root "dist\SupplierApp\tesseract"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item (Join-Path $TesseractDir "tesseract.exe") $target
Get-ChildItem $TesseractDir -Filter *.dll | Copy-Item -Destination $target
$targetData = Join-Path $target "tessdata"
New-Item -ItemType Directory -Force -Path $targetData | Out-Null
foreach ($lang in @("deu", "eng", "osd")) { Copy-Item (Join-Path $tessdata "$lang.traineddata") $targetData }
$configs = Join-Path $tessdata "configs"
if (Test-Path $configs) { Copy-Item $configs $targetData -Recurse -Force }
Copy-Item (Join-Path $root "README.md") "dist\SupplierApp\README.md"
Copy-Item (Join-Path $root "LICENSE-THIRD-PARTY.txt") "dist\SupplierApp\LICENSE-THIRD-PARTY.txt" -ErrorAction SilentlyContinue

# --- zip -----------------------------------------------------------------------------------------------------------
if (Test-Path $OutZip) { Remove-Item $OutZip }
Compress-Archive -Path "dist\SupplierApp" -DestinationPath $OutZip -CompressionLevel Optimal
Write-Host "Package: $OutZip ($([math]::Round((Get-Item $OutZip).Length / 1MB, 1)) MB)"
