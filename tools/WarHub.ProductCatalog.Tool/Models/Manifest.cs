namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Manifest metadata for the entire catalog generation run.
/// </summary>
public record Manifest
{
    public required string ToolVersion { get; init; }
    public required int TotalProducts { get; init; }
    public required IReadOnlyList<ManufacturerSummary> Manufacturers { get; init; }
}

/// <summary>
/// Summary info for one manufacturer in the manifest.
/// </summary>
public record ManufacturerSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required int ProductCount { get; init; }
    public required IReadOnlyList<GameSystemSummary> GameSystems { get; init; }
}

/// <summary>
/// Summary info for one game system within a manufacturer.
/// </summary>
public record GameSystemSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required int ProductCount { get; init; }
    public required IReadOnlyList<FactionSummary> Factions { get; init; }
}

/// <summary>
/// Summary info for one faction within a game system.
/// </summary>
public record FactionSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required int ProductCount { get; init; }
}
