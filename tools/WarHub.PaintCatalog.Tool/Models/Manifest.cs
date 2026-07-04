namespace WarHub.PaintCatalog.Tool.Models;

/// <summary>
/// Manifest metadata for the entire catalog generation run.
/// </summary>
public record Manifest
{
    public required string ToolVersion { get; init; }
    public required string SourceRepo { get; init; }
    public string? SourceCommit { get; init; }
    public required int TotalPaints { get; init; }
    public required IReadOnlyList<BrandSummary> Brands { get; init; }
}

public record BrandSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required int PaintCount { get; init; }
    public required bool HasProductCodes { get; init; }
}
