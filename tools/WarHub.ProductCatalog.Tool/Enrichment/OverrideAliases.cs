using WarHub.CatalogStore;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Loads rename aliases and retractions from overrides.yaml, scoped to one
/// faction path (mfgSlug/gsSlug/factionSlug). Names are normalized to match
/// reconciler identity keys.
/// </summary>
public static class OverrideAliases
{
    private sealed class OverridesFile
    {
        public Dictionary<string, Dictionary<string, string>>? Aliases { get; init; }
        public Dictionary<string, List<string>>? Retract { get; init; }
    }

    public static (IReadOnlyDictionary<string, string> Aliases, ISet<string> Retracted) Load(
        string? overridesPath, string mfgSlug, string gsSlug, string factionSlug)
    {
        var aliases = new Dictionary<string, string>(StringComparer.Ordinal);
        var retracted = new HashSet<string>(StringComparer.Ordinal);

        if (string.IsNullOrWhiteSpace(overridesPath) || !File.Exists(overridesPath))
            return (aliases, retracted);

        string scope = $"{mfgSlug}/{gsSlug}/{factionSlug}";
        OverridesFile? parsed = CatalogSerializer.CreateDeserializer()
            .Deserialize<OverridesFile>(File.ReadAllText(overridesPath));
        if (parsed is null)
            return (aliases, retracted);

        if (parsed.Aliases is not null && parsed.Aliases.TryGetValue(scope, out var scopedAliases))
            foreach (var (newName, oldName) in scopedAliases)
                aliases[NameNormalizer.Normalize(newName)] = NameNormalizer.Normalize(oldName);

        if (parsed.Retract is not null && parsed.Retract.TryGetValue(scope, out var scopedRetract))
            foreach (string name in scopedRetract)
                retracted.Add(NameNormalizer.Normalize(name));

        return (aliases, retracted);
    }
}
