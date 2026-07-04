namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Represents a unit/model within a product (e.g., "5x Intercessors on 32mm bases").
/// </summary>
public record ProductUnit
{
    public required string UnitName { get; init; }
    public required int Quantity { get; init; }
    public string? BaseSize { get; init; }
}
