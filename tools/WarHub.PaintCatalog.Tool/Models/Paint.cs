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
    public string? Packaging { get; init; }
    public string? Ean { get; init; }
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
}
