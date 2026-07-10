namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Per-faction output model containing all products for a manufacturer/game system/faction.
/// </summary>
public record FactionCatalog
{
    public required string Manufacturer { get; init; }
    public required string ManufacturerSlug { get; init; }
    public required string GameSystem { get; init; }
    public required string GameSystemSlug { get; init; }
    public required string Faction { get; init; }
    public required string FactionSlug { get; init; }
    public required List<Product> Products { get; init; }
}
