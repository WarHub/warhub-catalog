using System.Text.Json;
using System.Text.Json.Serialization;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Output document model for the published catalog. This project owns the public
/// schema; the shapes here are what clients consume (camelCase JSON). Every data
/// document carries a self-describing envelope (version / provenance) plus its payload.
/// </summary>
internal static class JsonConfig
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };
}

internal sealed record Partition(string Type, string Key, string Label);

internal sealed record ReleaseRef(string Tag, string Url);

internal sealed record SourceRef(string Repo, ReleaseRef? Release = null, string? PageUrl = null);

/// <summary>
/// A retail product. <c>ean</c> is optional — not every product carries a barcode. A product
/// genuinely repackaged over time (same contents, new box/barcode) carries its extra barcodes in
/// <c>additionalEans</c>; <c>ean</c> stays the single primary barcode for existing consumers.
/// </summary>
internal sealed record ProductRecord
{
    [JsonPropertyOrder(1)] public string? Ean { get; init; }
    [JsonPropertyOrder(1)] public IReadOnlyList<string>? AdditionalEans { get; init; }
    [JsonPropertyOrder(2)] public required string Name { get; init; }
    [JsonPropertyOrder(3)] public string? GameSystem { get; init; }
    [JsonPropertyOrder(4)] public string? Faction { get; init; }
    [JsonPropertyOrder(5)] public required string Category { get; init; }
    [JsonPropertyOrder(6)] public required string Status { get; init; }
    [JsonPropertyOrder(7)] public required string Availability { get; init; }
    [JsonPropertyOrder(8)] public int Quantity { get; init; }
    [JsonPropertyOrder(9)] public string? ProductCode { get; init; }
    [JsonPropertyOrder(10)] public string? Url { get; init; }
    [JsonPropertyOrder(11)] public string? ImageUrl { get; init; }
    [JsonPropertyOrder(12)] public string? EanConfidence { get; init; }
    [JsonPropertyOrder(13)] public decimal? PriceGbp { get; init; }
    [JsonPropertyOrder(14)] public decimal? PriceUsd { get; init; }
    [JsonPropertyOrder(15)] public decimal? PriceEur { get; init; }
    [JsonPropertyOrder(16)] public decimal? PriceCad { get; init; }
    // Unit volume in millilitres, for paints/sprays (e.g. 12, 18, 24, 400). Null for everything else.
    [JsonPropertyOrder(17)] public int? VolumeMl { get; init; }
}

/// <summary>A cross-brand near match; lower <c>deltaE</c> is closer.</summary>
internal sealed record PaintEquivalent(
    [property: JsonPropertyOrder(1)] string Id,
    [property: JsonPropertyOrder(2)] double DeltaE,
    [property: JsonPropertyOrder(3)] string? Tier);

/// <summary>A single paint. <c>id</c> is the stable global key (<c>brand-slug/paint-slug</c>).</summary>
internal sealed record PaintRecord(
    [property: JsonPropertyOrder(1)] string Id,
    [property: JsonPropertyOrder(2)] string Brand,
    [property: JsonPropertyOrder(3)] string Category,
    [property: JsonPropertyOrder(4)] string? Range,
    [property: JsonPropertyOrder(5)] string Name,
    // Null = colour not yet known (harvested additions await chart-swatch extraction); the
    // property is omitted from the JSON entirely rather than published as "".
    [property: JsonPropertyOrder(6)] string? Hex,
    [property: JsonPropertyOrder(7)] string? Type,
    [property: JsonPropertyOrder(8)] string? Finish,
    [property: JsonPropertyOrder(9)] int? VolumeMl,
    [property: JsonPropertyOrder(10)] string? Container,
    // ean/productCode are the manufacturer's retail identifiers, optional (only some brands supply
    // them -- currently GW/Citadel via the trade-barcode bridge, and Vallejo via computed EAN).
    [property: JsonPropertyOrder(11)] string? ProductCode,
    [property: JsonPropertyOrder(12)] string? Ean,
    [property: JsonPropertyOrder(13)] string Status,
    [property: JsonPropertyOrder(14)] string Availability,
    [property: JsonPropertyOrder(15)] IReadOnlyList<PaintEquivalent> Equivalents);

// ---- Envelope-bearing documents ------------------------------------------------

internal sealed class ProductCatalogDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "product-catalog";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(5)] public Partition? Partition { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required SourceRef Source { get; init; }
    [JsonPropertyOrder(8)] public required IReadOnlyList<ProductRecord> Products { get; init; }
}

internal sealed class PaintCatalogDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "paint-catalog";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(5)] public Partition? Partition { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required SourceRef Source { get; init; }
    [JsonPropertyOrder(8)] public required IReadOnlyList<PaintRecord> Paints { get; init; }
}

internal sealed record IndexEntry(string Key, string Label, int Records, string File);

internal sealed class IndexDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public required string Kind { get; init; }        // product-index | paint-index
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public required string PartitionType { get; init; } // gameSystem | brand
    [JsonPropertyOrder(5)] public required int Total { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyList<IndexEntry> Partitions { get; init; }
}

internal sealed record FileEntry(
    string Path, string Kind, string? Partition, int? Records, long Bytes, string Sha256);

internal sealed class ManifestDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "manifest";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(5)] public required SourceRef Source { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required IReadOnlyList<FileEntry> Files { get; init; }
}

internal static class SchemaInfo
{
    public const string SchemaVersion = "1.0";
}
