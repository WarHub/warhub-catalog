namespace WarHub.PaintCatalog.Tool.Models;

/// <summary>
/// Per-brand output model containing all paints for a brand.
/// </summary>
public record BrandCatalog
{
    public required string Brand { get; init; }
    public required string BrandSlug { get; init; }
    public string Source { get; init; } = "Arcturus5404/miniature-paints";
    public string License { get; init; } = "MIT";
    public required int PaintCount { get; init; }
    public required List<Paint> Paints { get; init; }
}
