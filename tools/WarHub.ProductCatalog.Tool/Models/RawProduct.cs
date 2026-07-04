namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Raw scraped product data before enrichment. Used internally by scrapers.
/// </summary>
public record RawProduct
{
    public required string Name { get; init; }
    public string? ProductCode { get; init; }
    public string? Sku { get; init; }
    public string? Ean { get; init; }
    public string? ProductType { get; init; }
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public string? Url { get; init; }
    public string? ImageUrl { get; init; }
    public string? ReleaseDate { get; init; }
    public string? Status { get; init; }
    public string? Description { get; init; }
    public required string Manufacturer { get; init; }
    public required string GameSystem { get; init; }
    public string? Faction { get; init; }
    public List<ProductUnit>? Contents { get; init; }
}
