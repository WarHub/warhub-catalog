<#
.SYNOPSIS
    Generates a markdown summary table of the product catalog with enrichment coverage.
.DESCRIPTION
    Reads all YAML product files under manufacturers/ and produces a markdown table
    showing product counts and enrichment coverage percentages per manufacturer.
.PARAMETER UpdateReadme
    When set, injects the summary into README.md between SUMMARY markers.
.PARAMETER RepoRoot
    Root directory of the repository. Defaults to the script's grandparent directory.
#>
[CmdletBinding()]
param(
    [switch]$UpdateReadme,
    [string]$RepoRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    if (-not $RepoRoot) { $RepoRoot = $PSScriptRoot | Split-Path -Parent }
}
# Handle case when running from repo root via relative path
if (-not (Test-Path (Join-Path $RepoRoot 'manufacturers'))) {
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

$manufacturersDir = Join-Path $RepoRoot 'manufacturers'
$yamlFiles = Get-ChildItem -Path $manufacturersDir -Filter '*.yaml' -Recurse

# Collect per-manufacturer stats
$mfgStats = [ordered]@{}

foreach ($file in $yamlFiles) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding utf8
    $data = ConvertFrom-Yaml $content

    $mfgName = $data.manufacturer
    $gameSystem = $data.gameSystem
    $products = $data.products
    if (-not $products) { continue }

    if (-not $mfgStats.Contains($mfgName)) {
        $mfgStats[$mfgName] = @{
            Name         = $mfgName
            GameSystems  = [System.Collections.Generic.HashSet[string]]::new()
            Products     = 0
            HasEan       = 0
            HasDesc      = 0
            HasPrice     = 0
            HasImage     = 0
        }
    }

    $stats = $mfgStats[$mfgName]
    [void]$stats.GameSystems.Add($gameSystem)

    foreach ($p in $products) {
        $stats.Products++

        if ($p.ContainsKey('ean') -and $p.ean) {
            $stats.HasEan++
        }
        if ($p.ContainsKey('description') -and $p.description) {
            $stats.HasDesc++
        }
        if (($p.ContainsKey('priceGbp') -and $p.priceGbp) -or
            ($p.ContainsKey('priceUsd') -and $p.priceUsd) -or
            ($p.ContainsKey('priceEur') -and $p.priceEur)) {
            $stats.HasPrice++
        }
        if ($p.ContainsKey('imageUrl') -and $p.imageUrl) {
            $stats.HasImage++
        }
    }
}

# Sort manufacturers alphabetically
$sorted = $mfgStats.Values | Sort-Object Name

# Compute totals
$totalProducts = ($sorted | Measure-Object -Property Products -Sum).Sum
$totalGameSystems = ($sorted | ForEach-Object { $_.GameSystems.Count } | Measure-Object -Sum).Sum
$totalMfg = $sorted.Count
$totalEan = ($sorted | Measure-Object -Property HasEan -Sum).Sum
$totalDesc = ($sorted | Measure-Object -Property HasDesc -Sum).Sum
$totalPrice = ($sorted | Measure-Object -Property HasPrice -Sum).Sum
$totalImage = ($sorted | Measure-Object -Property HasImage -Sum).Sum

function Format-Pct([int]$count, [int]$total) {
    if ($total -eq 0) { return '—' }
    $pct = [math]::Round(($count / $total) * 100)
    return "$pct%"
}

function Format-Num([int]$n) {
    return $n.ToString('N0', [System.Globalization.CultureInfo]::InvariantCulture)
}

# Build markdown
$sb = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine('> Auto-generated from product data — do not edit manually.')
[void]$sb.AppendLine()
[void]$sb.AppendLine("**$(Format-Num $totalProducts)** products from **$totalMfg** manufacturers across **$(Format-Num $totalGameSystems)** game systems.")
[void]$sb.AppendLine()
[void]$sb.AppendLine('| Manufacturer | Game Systems | Products | EAN | Description | Price | Image |')
[void]$sb.AppendLine('|---|---:|---:|---:|---:|---:|---:|')

foreach ($s in $sorted) {
    $gs = $s.GameSystems.Count
    $pr = Format-Num $s.Products
    $ean = Format-Pct $s.HasEan $s.Products
    $desc = Format-Pct $s.HasDesc $s.Products
    $price = Format-Pct $s.HasPrice $s.Products
    $img = Format-Pct $s.HasImage $s.Products
    [void]$sb.AppendLine("| $($s.Name) | $gs | $pr | $ean | $desc | $price | $img |")
}

$eanTotal = Format-Pct $totalEan $totalProducts
$descTotal = Format-Pct $totalDesc $totalProducts
$priceTotal = Format-Pct $totalPrice $totalProducts
$imgTotal = Format-Pct $totalImage $totalProducts
[void]$sb.AppendLine("| **Total** | **$(Format-Num $totalGameSystems)** | **$(Format-Num $totalProducts)** | **$eanTotal** | **$descTotal** | **$priceTotal** | **$imgTotal** |")

$markdown = $sb.ToString().TrimEnd()

if ($UpdateReadme) {
    $readmePath = Join-Path $RepoRoot 'README.md'
    $readmeContent = Get-Content -Path $readmePath -Raw -Encoding utf8

    $startMarker = '<!-- SUMMARY:START -->'
    $endMarker = '<!-- SUMMARY:END -->'

    $pattern = "(?s)$([regex]::Escape($startMarker)).*?$([regex]::Escape($endMarker))"
    $replacement = "$startMarker`n$markdown`n$endMarker"

    if ($readmeContent -match [regex]::Escape($startMarker)) {
        $newContent = [regex]::Replace($readmeContent, $pattern, $replacement)
    }
    else {
        Write-Error "README.md does not contain summary markers ($startMarker / $endMarker)"
        exit 1
    }

    Set-Content -Path $readmePath -Value $newContent -NoNewline -Encoding utf8
    Write-Host "README.md updated with summary table." -ForegroundColor Green
}
else {
    Write-Output $markdown
}
