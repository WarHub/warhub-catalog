<#
.SYNOPSIS
    Builds JSON release assets from the YAML product catalog.
.DESCRIPTION
    Converts all YAML product files to JSON and produces two release assets:
    - product-catalog.json (single merged file with all products)
    - product-catalog-files.zip (individual JSON files preserving directory structure)
.PARAMETER OutputDir
    Directory to write release assets into. Created if it doesn't exist.
.PARAMETER RepoRoot
    Root of the repository. Defaults to parent of the scripts directory.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$OutputDir,

    [string]$RepoRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) {
    $RepoRoot = $PSScriptRoot | Split-Path -Parent
}
if (-not (Test-Path (Join-Path $RepoRoot 'manufacturers'))) {
    $RepoRoot = Get-Location
}

# Ensure powershell-yaml is available
if (-not (Get-Module -ListAvailable -Name powershell-yaml)) {
    Write-Host 'Installing powershell-yaml module...' -ForegroundColor Yellow
    Install-Module -Name powershell-yaml -Force -Scope CurrentUser
}
Import-Module powershell-yaml -ErrorAction Stop

# Prepare output directories
$jsonFilesDir = Join-Path $OutputDir 'json-files'
New-Item -ItemType Directory -Path $jsonFilesDir -Force | Out-Null

$manufacturersDir = Join-Path $RepoRoot 'manufacturers'
$yamlFiles = Get-ChildItem -Path $manufacturersDir -Filter '*.yaml' -Recurse

# Convert manifest.yaml
$manifestPath = Join-Path $RepoRoot 'manifest.yaml'
if (Test-Path $manifestPath) {
    $manifestYaml = Get-Content -Path $manifestPath -Raw -Encoding utf8
    $manifestData = ConvertFrom-Yaml $manifestYaml
    $manifestJson = $manifestData | ConvertTo-Json -Depth 10
    $manifestOutPath = Join-Path $jsonFilesDir 'manifest.json'
    Set-Content -Path $manifestOutPath -Value $manifestJson -Encoding utf8
    Write-Host "Converted manifest.yaml" -ForegroundColor Gray
}

# Convert individual YAML files and collect products for merged output
$allProducts = [System.Collections.Generic.List[object]]::new()
$fileCount = 0

foreach ($file in $yamlFiles) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding utf8
    $data = ConvertFrom-Yaml $content

    # Preserve directory structure relative to manufacturers/
    $relativePath = $file.FullName.Substring($manufacturersDir.Length + 1)
    $jsonRelativePath = [System.IO.Path]::ChangeExtension($relativePath, '.json')
    $jsonOutPath = Join-Path $jsonFilesDir 'manufacturers' $jsonRelativePath

    $jsonOutDir = Split-Path -Parent $jsonOutPath
    New-Item -ItemType Directory -Path $jsonOutDir -Force | Out-Null

    $json = $data | ConvertTo-Json -Depth 10
    Set-Content -Path $jsonOutPath -Value $json -Encoding utf8
    $fileCount++

    # Collect products for merged file
    $products = $data.products
    if (-not $products) { continue }

    $manufacturer = $data.manufacturer
    $manufacturerSlug = $data.manufacturerSlug
    $gameSystem = $data.gameSystem
    $gameSystemSlug = $data.gameSystemSlug
    $faction = $data.faction
    $factionSlug = $data.factionSlug

    foreach ($p in $products) {
        $merged = [ordered]@{
            manufacturer     = $manufacturer
            manufacturerSlug = $manufacturerSlug
            gameSystem       = $gameSystem
            gameSystemSlug   = $gameSystemSlug
            faction          = $faction
            factionSlug      = $factionSlug
        }
        foreach ($key in $p.Keys) {
            $merged[$key] = $p[$key]
        }
        $allProducts.Add($merged)
    }
}

Write-Host "Converted $fileCount YAML files to JSON" -ForegroundColor Green

# Build merged product-catalog.json
$catalog = [ordered]@{
    generatedAt   = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')
    totalProducts = $allProducts.Count
    products      = $allProducts
}

$catalogJson = $catalog | ConvertTo-Json -Depth 10
$catalogPath = Join-Path $OutputDir 'product-catalog.json'
Set-Content -Path $catalogPath -Value $catalogJson -Encoding utf8
Write-Host "Created product-catalog.json ($($allProducts.Count) products)" -ForegroundColor Green

# Create zip of individual JSON files
$zipPath = Join-Path $OutputDir 'product-catalog-files.zip'
if (Test-Path $zipPath) { Remove-Item $zipPath }
Compress-Archive -Path (Join-Path $jsonFilesDir '*') -DestinationPath $zipPath
Write-Host "Created product-catalog-files.zip" -ForegroundColor Green

# Output summary
Write-Host "`nRelease assets in: $OutputDir" -ForegroundColor Cyan
Get-ChildItem -Path $OutputDir -File | ForEach-Object {
    $sizeMb = [math]::Round($_.Length / 1MB, 2)
    Write-Host "  $($_.Name) ($sizeMb MB)"
}
