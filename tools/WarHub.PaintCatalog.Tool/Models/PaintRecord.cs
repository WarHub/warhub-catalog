namespace WarHub.PaintCatalog.Tool.Models;

/// <summary>
/// Archival paint record: shared storage core at top level, paint-specific
/// color/physical fields nested under <see cref="Details"/>. This is the only
/// shape written to disk / reconciled / ledgered. Built from the flat working
/// <see cref="Paint"/> by PaintRecordMapper. Property order drives YAML order.
/// </summary>
public record PaintRecord
{
    public required string Name { get; init; }
    /// <summary>Constant "paint" for this catalog.</summary>
    public required string Category { get; init; }
    /// <summary>Archival lifecycle: current | suspected-discontinued | discontinued | delisted.</summary>
    public required string Status { get; init; }
    /// <summary>Volatile purchasability: in_stock | out_of_stock | pre_order | limited | unknown.</summary>
    public required string Availability { get; init; }
    /// <summary>Write-once, immutable.</summary>
    public string? FirstSeen { get; init; }
    public string? ProductCode { get; init; }
    public string? Ean { get; init; }
    /// <summary>
    /// Further barcodes the SAME paint is sold under beyond the primary <see cref="Ean"/>, so a
    /// scan of any of them still identifies this paint. Today these are concurrent REGIONAL trade
    /// variants (e.g. a spray sold as both an R/O-Europe and a UK/ROW SKU with one shared SSC
    /// code), NOT retired barcodes -- do not present them as superseded. Null (never an empty
    /// list) when there is only one barcode, so the key is omitted from the archive YAML.
    ///
    /// Declared as <c>List</c>, not <c>IReadOnlyList</c>: YamlDotNet SERIALIZES a read-only list
    /// happily but has no node deserializer for one, so the archive wrote a shape it could not read
    /// back. That is invisible until a record actually gains the key -- which happened the first
    /// time the bridge matched the 9 regional spray pairs, and the very next load of
    /// citadel-colour.yaml then died with "No node deserializer was able to deserialize the node
    /// into type IReadOnlyList&lt;String&gt;" at the first `additionalEans` entry. Any list property
    /// added to this archival record must be round-trip tested, not just written.
    /// </summary>
    public List<string>? AdditionalEans { get; init; }
    public string? ImageUrl { get; init; }
    public required PaintDetails Details { get; init; }
}

/// <summary>Paint-specific color/physical fields (the category extension block).</summary>
public record PaintDetails
{
    public required string Set { get; init; }
    public required int R { get; init; }
    public required int G { get; init; }
    public required int B { get; init; }
    public required string Hex { get; init; }
    public int? VolumeMl { get; init; }
    /// <summary>Bottle type (dropper | pot | spray | ...). Was the legacy `packaging` field.</summary>
    public string? Container { get; init; }
    public string? Type { get; init; }
    public string? Finish { get; init; }
}

/// <summary>Per-brand archival file envelope. No derived counts (recomputed at publish).</summary>
public record BrandArchive
{
    public required string Brand { get; init; }
    public required string BrandSlug { get; init; }
    public string Source { get; init; } = "Arcturus5404/miniature-paints";
    public string License { get; init; } = "MIT";
    public required List<PaintRecord> Paints { get; init; }
}
