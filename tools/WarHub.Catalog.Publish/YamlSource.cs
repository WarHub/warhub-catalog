using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Reads the source-of-truth YAML: the canonical product catalog (this project's own
/// DTOs) and the paint brand/equivalence files. Ignores unmatched keys so upstream
/// metadata (e.g. the verbose <c>generatedAt</c> block on brand files) is tolerated.
/// </summary>
internal static class YamlSource
{
    private static readonly IDeserializer Deserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>Loads every brand catalog under <c>{paintsDir}/brands/*.yaml</c>.</summary>
    public static IEnumerable<BrandFile> LoadBrands(string paintsDir)
    {
        string brands = Path.Combine(paintsDir, "brands");
        if (!Directory.Exists(brands))
        {
            yield break;
        }

        foreach (string file in Directory
            .EnumerateFiles(brands, "*.yaml", SearchOption.TopDirectoryOnly)
            .OrderBy(f => f, StringComparer.Ordinal))
        {
            var catalog = Deserializer.Deserialize<BrandFile>(File.ReadAllText(file));
            if (catalog is not null)
            {
                yield return catalog;
            }
        }
    }

    /// <summary>Loads the cross-brand equivalences file, if present.</summary>
    public static EquivFile? LoadEquivalences(string paintsDir)
    {
        string file = Path.Combine(paintsDir, "equivalences.yaml");
        return File.Exists(file)
            ? Deserializer.Deserialize<EquivFile>(File.ReadAllText(file))
            : null;
    }

    /// <summary>
    /// Loads the canonical product catalog under <c>{catalogDir}/products/*.yaml</c> (not recursive),
    /// ONE CATALOG PER MANUFACTURER however many files hold it. The resolver writes a manufacturer
    /// too big for one file as shards named <c>{manufacturer}.{prefix}.yaml</c>, each in the same
    /// document shape (tools/acquisition/src/warhub_acquisition/resolve/layout.py). They are merged
    /// back here with the products in id order, which is the order a single file holds them in. So
    /// the records reach <see cref="ProductBuilder"/> in the same sequence whichever layout is on
    /// disk, and the published documents are byte-identical across a relayout.
    ///
    /// A file whose <c>manufacturer:</c> is not its name up to the first dot, or an id held by two
    /// files, throws. The resolver writes neither, so either one means the tree was edited by hand.
    /// </summary>
    public static IEnumerable<CanonicalProductCatalog> LoadCanonicalCatalogs(string catalogDir)
    {
        string products = Path.Combine(catalogDir, "products");
        if (!Directory.Exists(products))
        {
            return [];
        }

        // Manufacturers in the order their first file sorts, as they were read one file each.
        var order = new List<string>();
        var merged = new Dictionary<string, List<CanonicalProduct>>(StringComparer.Ordinal);
        var heldBy = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string file in Directory
            .EnumerateFiles(products, "*.yaml", SearchOption.TopDirectoryOnly)
            .OrderBy(f => f, StringComparer.Ordinal))
        {
            var catalog = Deserializer.Deserialize<CanonicalProductCatalog>(File.ReadAllText(file));
            if (catalog is null)
            {
                continue;
            }

            string name = Path.GetFileName(file);
            if (catalog.Manufacturer != name[..name.IndexOf('.')])
            {
                throw new InvalidOperationException($"{name} declares manufacturer '{catalog.Manufacturer}'");
            }
            foreach (CanonicalProduct p in catalog.Products)
            {
                if (!heldBy.TryAdd(p.Id, name))
                {
                    throw new InvalidOperationException($"{p.Id} is in both {heldBy[p.Id]} and {name}");
                }
            }
            if (!merged.TryGetValue(catalog.Manufacturer, out List<CanonicalProduct>? records))
            {
                merged[catalog.Manufacturer] = records = [];
                order.Add(catalog.Manufacturer);
            }
            records.AddRange(catalog.Products);
        }

        return [.. order.Select(m => new CanonicalProductCatalog
        {
            Manufacturer = m,
            Products = [.. merged[m].OrderBy(p => p.Id, StringComparer.Ordinal)],
        })];
    }

    /// <summary>
    /// Loads the boxed-set relation from <c>{catalogDir}/set-contents/*.yaml</c> (not recursive),
    /// merging every manufacturer block into one map keyed by manufacturer slug.
    ///
    /// The directory is OPTIONAL -- a catalog with no boxed sets, and every fixture that does not
    /// exercise them, publishes an empty relation rather than failing. A duplicate manufacturer
    /// key across two files throws instead of letting one file silently win: the generator writes
    /// exactly one file per manufacturer, so a collision means the tree has been hand-edited.
    /// </summary>
    public static IReadOnlyDictionary<string, CanonicalSetContentsFile> LoadSetContents(string catalogDir)
    {
        var merged = new Dictionary<string, CanonicalSetContentsFile>(StringComparer.Ordinal);
        string dir = Path.Combine(catalogDir, "set-contents");
        if (!Directory.Exists(dir))
        {
            return merged;
        }

        foreach (string file in Directory
            .EnumerateFiles(dir, "*.yaml", SearchOption.TopDirectoryOnly)
            .OrderBy(f => f, StringComparer.Ordinal))
        {
            var blocks = Deserializer.Deserialize<Dictionary<string, CanonicalSetContentsFile>>(
                File.ReadAllText(file));
            foreach ((string manufacturer, CanonicalSetContentsFile block) in blocks ?? [])
            {
                if (!merged.TryAdd(manufacturer, block))
                {
                    throw new InvalidOperationException(
                        $"set-contents: manufacturer '{manufacturer}' is declared in more than one file "
                        + $"(seen again in {Path.GetFileName(file)})");
                }
            }
        }

        return merged;
    }

    /// <summary>
    /// Loads the game-system and faction slug-to-label maps from
    /// <c>{catalogDir}/taxonomy/game-systems.yaml</c> and <c>taxonomy/factions.yaml</c>.
    /// A missing file yields an empty map for that dimension.
    /// </summary>
    public static TaxonomyLabels LoadTaxonomyLabels(string catalogDir)
    {
        string taxonomy = Path.Combine(catalogDir, "taxonomy");
        var gameSystems = ReadLabelFile<GameSystemLabelsFile>(Path.Combine(taxonomy, "game-systems.yaml"))?.GameSystems;
        var factions = ReadLabelFile<FactionLabelsFile>(Path.Combine(taxonomy, "factions.yaml"))?.Factions;
        var settings = ReadLabelFile<SettingLabelsFile>(Path.Combine(taxonomy, "settings.yaml"))?.Settings;
        var settingOfGame = (gameSystems ?? [])
            .Where(e => !string.IsNullOrEmpty(e.Setting))
            .ToDictionary(e => e.Slug, e => e.Setting!);
        return new TaxonomyLabels(ToLabelMap(gameSystems), ToLabelMap(factions), ToLabelMap(settings), settingOfGame);
    }

    private static T? ReadLabelFile<T>(string file)
    {
        return File.Exists(file)
            ? Deserializer.Deserialize<T>(File.ReadAllText(file))
            : default;
    }

    private static IReadOnlyDictionary<string, string> ToLabelMap(IEnumerable<LabelEntry>? entries)
    {
        return entries is null
            ? new Dictionary<string, string>()
            : entries.ToDictionary(e => e.Slug, e => e.Label);
    }

    private record LabelEntry
    {
        public required string Slug { get; init; }
        public required string Label { get; init; }
    }

    // A game system's entry also names the SETTING it is played in (game-systems.yaml
    // `setting:`); a catch-all bucket is the one entry allowed to name none.
    private sealed record GameSystemEntry : LabelEntry
    {
        public string? Setting { get; init; }
        public bool? CatchAll { get; init; }
    }

    private sealed record SettingLabelsFile
    {
        public required List<LabelEntry> Settings { get; init; }
    }

    private sealed record GameSystemLabelsFile
    {
        public required List<GameSystemEntry> GameSystems { get; init; }
    }

    private sealed record FactionLabelsFile
    {
        public required List<LabelEntry> Factions { get; init; }
    }
}
