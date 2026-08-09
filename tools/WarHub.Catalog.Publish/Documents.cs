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
    // Id + Manufacturer are published so an archival/lineage link (supersededBy / supersedes) has
    // a stable target to point at -- the resolver's entity id, `manufacturer/<code-or-slug>`.
    [JsonPropertyOrder(0)] public required string Id { get; init; }
    [JsonPropertyOrder(0)] public required string Manufacturer { get; init; }
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
    // Unit NET WEIGHT in grams, for the things sold by mass rather than volume (glue, basing sand).
    // Mirrors the paint record's field so the cross-catalog seam cannot disagree with itself: a
    // barcode that resolves to both a paint and a product (paintIds/productIds, CrossCatalogLinks)
    // would otherwise publish net contents on one side and silence on the other for one physical
    // tub. Measured 2026-08-06: 3 of 22,529 products name a mass (2 GW plastic glue SKUs at 15 g,
    // 1 Mantic basing sand at 400 g) and NONE of them carries a volume, so unlike the paint side
    // nothing here is currently wrong -- this closes an absence, not an error.
    [JsonPropertyOrder(17)] public int? WeightG { get; init; }
    // Archival lineage between two product codes for the same product (a re-code, a repackaging).
    // BOTH records are published: a retired one keeps its own productCode/ean and points forward
    // with <c>supersededBy</c>; the current one lists its predecessors in <c>supersedes</c>. So a
    // decade-old box still scans to a record, and that record says what replaced it. Note the
    // relation is NOT encoded in <c>status</c> -- a consumer filtering on status keeps working
    // unchanged, and a retired record's status is still whatever the evidence says it is.
    [JsonPropertyOrder(18)] public IReadOnlyList<string>? Supersedes { get; init; }
    [JsonPropertyOrder(19)] public string? SupersededBy { get; init; }
    // Cross-catalog seam: the paint records that share a barcode with this product. Plural
    // because neither side is 1:1 -- one colour ships as many SKUs, and a barcode can be
    // carried by more than one record on either side. Null (omitted) when there is no link.
    // See CrossCatalogLinks for how it is computed and why it is emitted, not assumed.
    [JsonPropertyOrder(20)] public IReadOnlyList<string>? PaintIds { get; init; }
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
    // NET CONTENTS in grams for the products sold by mass instead of by volume -- 2 paints as of
    // 2026-08-06, both Green Stuff World foam-primer tubs. A SIBLING of volumeMl, in the style of
    // the four price scalars below: the unit is in the name, both may be present (a pigment
    // weighed into a jar of stated size), and a consumer that never reads it behaves exactly as it
    // did before the field existed. Deliberately NOT a {unit, amount} pair or a repurposed
    // volumeMl -- either would force every existing reader of volumeMl to be rewritten and would
    // have to migrate 7,903 values for a 2-record problem.
    [property: JsonPropertyOrder(9)] int? WeightG,
    [property: JsonPropertyOrder(10)] string? Container,
    // ean/productCode are the manufacturer's retail identifiers, optional (only some brands supply
    // them -- currently GW/Citadel via the trade-barcode bridge, and Vallejo via computed EAN).
    [property: JsonPropertyOrder(11)] string? ProductCode,
    [property: JsonPropertyOrder(12)] string? Ean,
    // Further barcodes the same paint is sold under (today: concurrent regional trade variants),
    // so a scan of any of them resolves. Mirrors ProductRecord.AdditionalEans; null -> omitted.
    [property: JsonPropertyOrder(12)] IReadOnlyList<string>? AdditionalEans,
    // Product/swatch image from the manufacturer or a harvested catalog page.
    [property: JsonPropertyOrder(13)] string? ImageUrl,
    // Manufacturer list price, mirroring ProductRecord. Availability deliberately does NOT come
    // with it: the trade evidence that carries paint prices carries no stock signal at all, and one
    // paint identity spans several retail SKUs whose stock differs.
    [property: JsonPropertyOrder(14)] decimal? PriceGbp,
    [property: JsonPropertyOrder(15)] decimal? PriceUsd,
    [property: JsonPropertyOrder(16)] decimal? PriceEur,
    [property: JsonPropertyOrder(17)] decimal? PriceCad,
    [property: JsonPropertyOrder(18)] string Status,
    [property: JsonPropertyOrder(19)] string Availability,
    // `false` when a source states this pot is only available inside a boxed set; ABSENT
    // whenever no source said, which is nearly always and is a different claim from `true`.
    // A consumer that has never heard of this field sees exactly what it saw before -- which
    // is the point of it being a sibling rather than a new `availability` value, the same
    // reasoning `supersedes` records just below.
    [property: JsonPropertyOrder(19)] bool? SoldSeparately,
    // Archival lineage between two paint identities for the same colour -- a reformulation that
    // moved the paint into another range keeps BOTH records: the retired one points forward with
    // `supersededBy`, the replacement lists its predecessors in `supersedes`. Values are paint ids,
    // so an old pot still resolves and says what replaced it. As on ProductRecord the relation is
    // deliberately NOT encoded in `status` -- a consumer filtering on status keeps working, and a
    // retired paint's status stays whatever the evidence says it is.
    [property: JsonPropertyOrder(20)] IReadOnlyList<string>? Supersedes,
    [property: JsonPropertyOrder(21)] string? SupersededBy,
    [property: JsonPropertyOrder(22)] IReadOnlyList<PaintEquivalent> Equivalents,
    // Cross-catalog seam: the product records that share a barcode with this paint. Plural
    // because one colour is sold as many SKUs (pot, spray, contrast, a paint-set component),
    // so a paint routinely resolves to several products. Mirrors ProductRecord.PaintIds;
    // null -> omitted. Defaulted so the link pass can fill it via `with` after assembly.
    [property: JsonPropertyOrder(23)] IReadOnlyList<string>? ProductIds = null);

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

/// <summary>One record that carries a barcode. <c>catalog</c> is <c>product</c> or <c>paint</c>.</summary>
internal sealed record BarcodeRef(
    [property: JsonPropertyOrder(1)] string Catalog,
    [property: JsonPropertyOrder(2)] string Id);

/// <summary>
/// The cross-catalog barcode index: every barcode in either catalog, mapped to the records that
/// carry it. Keyed by the barcode itself so a scanner does one lookup, not a scan. A key whose
/// value names records from BOTH catalogs is the seam this document exists for -- the same
/// physical thing published twice, once as a SKU and once as a colour.
/// </summary>
internal sealed class BarcodeIndexDocument
{
    [JsonPropertyOrder(0)] public string SchemaVersion { get; init; } = SchemaInfo.SchemaVersion;
    [JsonPropertyOrder(1)] public string Kind { get; init; } = "barcode-index";
    [JsonPropertyOrder(2)] public required string Version { get; init; }
    [JsonPropertyOrder(3)] public required string GeneratedAt { get; init; }
    [JsonPropertyOrder(4)] public string? GitCommit { get; init; }
    [JsonPropertyOrder(6)] public required IReadOnlyDictionary<string, int> Counts { get; init; }
    [JsonPropertyOrder(7)] public required SourceRef Source { get; init; }
    // Dictionary keys are NOT camelCased -- JsonSerializerOptions.PropertyNamingPolicy applies to
    // property names only, DictionaryKeyPolicy is unset, so barcodes pass through verbatim.
    [JsonPropertyOrder(8)] public required IReadOnlyDictionary<string, IReadOnlyList<BarcodeRef>> Barcodes { get; init; }
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
    public const string SchemaVersion = "1.1";
}
