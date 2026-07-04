using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Equivalence;

/// <summary>
/// Represents a single paint reference in an equivalence entry.
/// </summary>
public record PaintRef
{
    public required string Brand { get; init; }
    public required string BrandSlug { get; init; }
    public required string Name { get; init; }
    public string? ProductCode { get; init; }
    public required string Set { get; init; }
    public required string Hex { get; init; }
}

/// <summary>
/// A match for a source paint — another paint with its Delta E distance.
/// </summary>
public record PaintMatch
{
    public required PaintRef Paint { get; init; }
    public required double DeltaE { get; init; }
    public required string Tier { get; init; } // "close" or "substitute"
}

/// <summary>
/// All equivalences for a single source paint.
/// </summary>
public record PaintEquivalenceEntry
{
    public required PaintRef Source { get; init; }
    public required IReadOnlyList<PaintMatch> Matches { get; init; }
}

/// <summary>
/// The full equivalences output file.
/// </summary>
public record EquivalencesFile
{
    public required EquivalenceThresholds Thresholds { get; init; }
    public required int TotalEntries { get; init; }
    public required IReadOnlyList<PaintEquivalenceEntry> Equivalences { get; init; }
}

/// <summary>
/// Delta E thresholds used for categorizing matches.
/// </summary>
public record EquivalenceThresholds
{
    public required double Close { get; init; }
    public required double Substitute { get; init; }
}
