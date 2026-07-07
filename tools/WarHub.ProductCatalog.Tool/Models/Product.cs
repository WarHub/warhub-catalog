namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Represents a single catalog product (miniature kit, terrain, accessory, etc.).
/// Field declaration order defines YAML emission order.
/// </summary>
public record Product
{
    public required string Name { get; init; }

    /// <summary>What the thing is: miniatures | terrain | accessory | paint | book | tool.</summary>
    public required string Category { get; init; }

    /// <summary>How it is sold: single | bundle | box | starter.</summary>
    public required string Packaging { get; init; }

    /// <summary>Archival lifecycle: current | suspected-discontinued | discontinued | delisted.</summary>
    public required string Status { get; init; }

    /// <summary>Volatile purchasability: in_stock | out_of_stock | pre_order | limited | unknown.</summary>
    public required string Availability { get; init; }

    /// <summary>Write-once ISO yyyy-MM-dd date the record was first archived.</summary>
    public string? FirstSeen { get; init; }

    public string? Ean { get; init; }

    /// <summary>How the EAN was resolved: "upcitemdb", "shopify:{host}", "not_found".</summary>
    public string? EanSource { get; init; }

    public string? Sku { get; init; }
    public string? ProductCode { get; init; }
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public string? Url { get; init; }
    public string? ImageUrl { get; init; }
    public string? ReleaseDate { get; init; }
    public string? Description { get; init; }
    public List<ProductUnit>? Contents { get; init; }
}
