namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Represents a single miniature product (kit, box set, combat patrol, etc.).
/// </summary>
public record Product
{
    public required string Name { get; init; }
    public string? ProductCode { get; init; }
    public string? Sku { get; init; }
    public string? Ean { get; init; }
    /// <summary>
    /// Tracks how the EAN was resolved: "upcitemdb", "shopify:{host}", "not_found".
    /// When set (even without Ean), indicates the product has been searched — skip re-querying.
    /// </summary>
    public string? EanSource { get; init; }
    public required string ProductType { get; init; }
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public string? Url { get; init; }
    public string? ImageUrl { get; init; }
    public string? ReleaseDate { get; init; }
    public required string Status { get; init; }
    public string? Description { get; init; }
    public List<ProductUnit>? Contents { get; init; }
}
