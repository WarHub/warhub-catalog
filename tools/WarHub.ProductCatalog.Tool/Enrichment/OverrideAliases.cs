// tools/WarHub.ProductCatalog.Tool/Enrichment/OverrideAliases.cs (finalized in Task 11)
namespace WarHub.ProductCatalog.Tool.Enrichment;

public static class OverrideAliases
{
    public static (IReadOnlyDictionary<string, string> Aliases, ISet<string> Retracted) Load(
        string? overridesPath, string mfgSlug, string gsSlug, string factionSlug)
        => (new Dictionary<string, string>(), new HashSet<string>());
}
