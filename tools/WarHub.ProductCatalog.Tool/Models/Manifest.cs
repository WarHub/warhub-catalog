namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>Manifest listing the catalog's manufacturers → game systems → factions.</summary>
public record Manifest
{
    public required string ToolVersion { get; init; }
    public required IReadOnlyList<ManufacturerSummary> Manufacturers { get; init; }
}

public record ManufacturerSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required IReadOnlyList<GameSystemSummary> GameSystems { get; init; }
}

public record GameSystemSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required IReadOnlyList<FactionSummary> Factions { get; init; }
}

public record FactionSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
}
