<#
.SYNOPSIS
    Builds the WarHub app product-catalog artifact from the YAML catalog.
.DESCRIPTION
    Emits warhub-products.json in the schema the WarHub app consumes
    (ProductCatalogArtifact): only products that carry an EAN, flattened to
    { ean, name, gameSystem, faction, quantity, imageUrl, productCode }.
    Duplicate EANs resolve deterministically (status 'current' first, then
    name ascending). Fails if the emitted+skipped count doesn't match the
    number of `ean:` entries in the YAML (guards against YAML integer
    parsing corrupting codes).
.PARAMETER OutputPath
    File path to write warhub-products.json to. Parent created if missing.
.PARAMETER Version
    Artifact version string. Defaults to v<yyyy.MM.dd> (UTC) to match release tags.
.PARAMETER RepoRoot
    Root of the repository. Defaults to parent of the scripts directory.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$OutputPath,

    [string]$Version,

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
if (-not $Version) {
    $Version = 'v{0:yyyy.MM.dd}' -f (Get-Date).ToUniversalTime()
}

# Ensure powershell-yaml is available
if (-not (Get-Module -ListAvailable -Name powershell-yaml)) {
    Write-Host 'Installing powershell-yaml module...' -ForegroundColor Yellow
    Install-Module -Name powershell-yaml -Force -Scope CurrentUser
}
Import-Module powershell-yaml -ErrorAction Stop

$manufacturersDir = Join-Path $RepoRoot 'manufacturers'
$yamlFiles = Get-ChildItem -Path $manufacturersDir -Filter '*.yaml' -Recurse

$candidates = [System.Collections.Generic.List[object]]::new()
$skipped = 0

foreach ($file in $yamlFiles) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding utf8
    $data = ConvertFrom-Yaml $content

    $products = if ($data.Contains('products')) { $data.products } else { $null }
    if (-not $products) { continue }

    # Raw ean scalars as written in the file, for the digit-level parity check.
    $rawEans = [regex]::Matches($content, '(?m)^\s+ean:\s*["'']?([^"''\s#]+)') |
        ForEach-Object { $_.Groups[1].Value } | Sort-Object
    $parsedEans = [System.Collections.Generic.List[string]]::new()

    foreach ($p in $products) {
        if (-not $p.Contains('ean') -or $null -eq $p.ean) { continue }

        # YAML parses unquoted EANs as integers (powershell-yaml even eats
        # leading zeros); the parity check below proves the coerced string
        # matches what the file literally says. Leading-zero codes must be
        # quoted in the YAML.
        $ean = ([string]$p.ean).Trim()
        $parsedEans.Add($ean)
        if ($ean -notmatch '^\d{8,14}$') {
            Write-Warning "Skipping product '$($p.name)' in $($file.Name): EAN '$ean' is not 8-14 digits"
            $skipped++
            continue
        }

        # Scraper artifact: some imageUrl values carry a trailing ");".
        $imageUrl = if ($p.Contains('imageUrl') -and $p.imageUrl) { ([string]$p.imageUrl).TrimEnd(');') } else { $null }

        $candidates.Add([pscustomobject]@{
                ean         = $ean
                name        = [string]$p.name
                gameSystem  = $data.gameSystem
                faction     = $data.faction
                quantity    = 1
                imageUrl    = $imageUrl
                productCode = if ($p.Contains('productCode') -and $p.productCode) { [string]$p.productCode } else { $null }
                status      = if ($p.Contains('status') -and $p.status) { [string]$p.status } else { '' }
            })
    }

    # Digit-level parity: the coerced strings must equal the raw file text,
    # or YAML parsing corrupted a code (e.g. dropped a leading zero).
    $parsedSorted = $parsedEans | Sort-Object
    if (($rawEans -join ',') -ne ($parsedSorted -join ',')) {
        throw "EAN parity check failed in $($file.FullName): raw [$($rawEans -join ',')] vs parsed [$($parsedSorted -join ',')]"
    }
}

$yamlEanCount = ($yamlFiles | Select-String -Pattern '^\s+ean:').Count

# Deterministic winner per EAN: status 'current' first, then name ascending.
$products = $candidates |
    Group-Object -Property ean |
    ForEach-Object {
        $winner = $_.Group |
            Sort-Object -Property @{ Expression = { if ($_.status -eq 'current') { 0 } else { 1 } } }, name |
            Select-Object -First 1
        $winner | Select-Object -Property ean, name, gameSystem, faction, quantity, imageUrl, productCode
    } |
    Sort-Object -Property ean

$artifact = [ordered]@{
    version  = $Version
    products = @($products)
}

$outputDir = Split-Path -Parent $OutputPath
if ($outputDir) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}
$json = $artifact | ConvertTo-Json -Depth 5
Set-Content -Path $OutputPath -Value $json -Encoding utf8

$sizeMb = [math]::Round((Get-Item $OutputPath).Length / 1MB, 2)
$dupes = $candidates.Count - @($products).Count
Write-Host "Created $OutputPath ($sizeMb MB): $(@($products).Count) products, version $Version" -ForegroundColor Green
Write-Host "  ($yamlEanCount ean entries: $skipped skipped, $dupes duplicate-EAN losers dropped)" -ForegroundColor Gray
