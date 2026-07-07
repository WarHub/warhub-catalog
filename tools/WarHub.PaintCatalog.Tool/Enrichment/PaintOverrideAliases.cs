using WarHub.CatalogStore;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>Loads rename aliases and retractions from overrides.yaml, scoped to one brand.</summary>
public static class PaintOverrideAliases
{
    private sealed class OverridesFile
    {
        public Dictionary<string, Dictionary<string, string>>? Aliases { get; init; }
        public Dictionary<string, List<string>>? Retract { get; init; }
    }

    public static (IReadOnlyDictionary<string, string> Aliases, ISet<string> Retracted) Load(
        string? overridesPath, string brandSlug)
    {
        var aliases = new Dictionary<string, string>(StringComparer.Ordinal);
        var retracted = new HashSet<string>(StringComparer.Ordinal);

        if (string.IsNullOrWhiteSpace(overridesPath) || !File.Exists(overridesPath))
            return (aliases, retracted);

        OverridesFile? parsed = CatalogSerializer.CreateDeserializer()
            .Deserialize<OverridesFile>(File.ReadAllText(overridesPath));
        if (parsed is null)
            return (aliases, retracted);

        if (parsed.Aliases is not null && parsed.Aliases.TryGetValue(brandSlug, out var scopedAliases))
            foreach (var (newKey, oldKey) in scopedAliases)
                aliases[NameNormalizer.Normalize(newKey)] = NameNormalizer.Normalize(oldKey);

        if (parsed.Retract is not null && parsed.Retract.TryGetValue(brandSlug, out var scopedRetract))
            foreach (string key in scopedRetract)
                retracted.Add(NameNormalizer.Normalize(key));

        return (aliases, retracted);
    }
}
