namespace WarHub.Catalog.Publish;

// Local read-models for equivalences.yaml. The tool's own equivalence records use
// IReadOnlyList<T>, which YamlDotNet cannot instantiate on read; these use List<T>.

internal sealed class EquivFile
{
    public List<EquivEntry> Equivalences { get; set; } = [];
}

internal sealed class EquivEntry
{
    public EquivRef Source { get; set; } = null!;
    public List<EquivMatch> Matches { get; set; } = [];
}

internal sealed class EquivMatch
{
    public EquivRef Paint { get; set; } = null!;
    public double DeltaE { get; set; }
    public string? Tier { get; set; }
}

internal sealed class EquivRef
{
    public string BrandSlug { get; set; } = "";
    public string Name { get; set; } = "";
    public string Set { get; set; } = "";
    public string? ProductCode { get; set; }
}
