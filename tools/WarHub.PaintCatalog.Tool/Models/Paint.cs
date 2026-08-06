namespace WarHub.PaintCatalog.Tool.Models;

/// <summary>
/// Represents a single paint in the catalog.
/// </summary>
public record Paint
{
    public required string Name { get; init; }
    public string? ProductCode { get; init; }
    public required string Set { get; init; }
    public required int R { get; init; }
    public required int G { get; init; }
    public required int B { get; init; }
    public required string Hex { get; init; }
    public int? VolumeMl { get; init; }
    /// <summary>
    /// NET CONTENTS in grams, for a product sold by mass rather than by volume. Sibling of
    /// <see cref="VolumeMl"/>, never a replacement: a record may state either, both (a pigment
    /// weighed into a jar of known size) or neither. See <see cref="NetContents"/> for the merge
    /// rule and for why the Shopify `hints.grams` shipping weight must never feed it.
    /// </summary>
    public int? WeightG { get; init; }
    public string? Packaging { get; init; }
    public string? Ean { get; init; }
    /// <summary>Extra barcodes the same paint is sold under (regional variants). See PaintRecord.</summary>
    public List<string>? AdditionalEans { get; init; }
    public bool IsDiscontinued { get; init; }

    /// <summary>
    /// Paint type derived from brand and set classification.
    /// Examples: "Base", "Layer", "Shade", "Contrast", "Dry", "Air",
    /// "Technical", "Wash", "Speedpaint", "Glaze", "Standard".
    /// </summary>
    public string? Type { get; init; }

    /// <summary>
    /// Paint finish derived from set name and paint name patterns.
    /// Values: "Matte", "Metallic", "Gloss", "Satin".
    /// </summary>
    public string? Finish { get; init; }

    /// <summary>
    /// URL to product/swatch image from manufacturer or retailer.
    /// </summary>
    public string? ImageUrl { get; init; }

    /// <summary>Manufacturer list price per currency. See PaintRecord for why availability does NOT follow.</summary>
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public decimal? PriceCad { get; init; }

    /// <summary>
    /// The <c>{Name}|{Set}</c> identity of the paint that REPLACED this one (a reformulation into
    /// another range). Maintainer-declared in overrides.yaml; the single declared direction.
    /// </summary>
    public string? SupersededBy { get; init; }

    /// <summary>
    /// The <c>{Name}|{Set}</c> identities this paint replaced. DERIVED from the declarations above
    /// by <see cref="Enrichment.OverrideApplier.LinkSupersessions"/> — never hand-written, so the
    /// two directions cannot drift apart.
    /// </summary>
    public List<string>? Supersedes { get; init; }
}
