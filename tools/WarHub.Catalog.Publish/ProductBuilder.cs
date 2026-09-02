namespace WarHub.Catalog.Publish;

/// <summary>
/// Turns the canonical per-manufacturer product YAML into the consolidated +
/// per-game-system JSON documents. Every product is included; <c>ean</c> is optional, and so is
/// <c>gameSystems</c> -- a product genuinely belonging to no game system (a base, a gaming mat, a
/// paint/tool bundle, dice, an advent calendar, ...) has an EMPTY <c>GameSystems</c>. Such a
/// product is published in <c>products.json</c> / <c>products/index.json</c> like everything
/// else, but is excluded from every <c>products/by-system/*.json</c> partition -- it belongs to
/// none of them.
///
/// A product may belong to SEVERAL systems, and then it appears in several partitions. The two
/// invariants that follow are worth stating because they stopped being the same number: a record
/// appears EXACTLY ONCE in <c>products.json</c>, and once in each partition it names. So the
/// partition counts sum to at least the total and the index's <c>total</c> is the product count,
/// not the sum of its partitions.
/// </summary>
internal static class ProductBuilder
{
    /// <summary>
    /// Assemble + write in one step, with no cross-catalog links. Kept for callers that publish
    /// products on their own; <see cref="Publisher"/> uses the two phases separately so the
    /// barcode link pass can run between them.
    /// </summary>
    public static int Build(
        IEnumerable<CanonicalProductCatalog> catalogs,
        TaxonomyLabels labels,
        Provenance prov,
        CatalogWriter writer) => Write(Assemble(catalogs, labels), prov, writer);

    /// <summary>
    /// Builds every record and settles the ordering, but writes nothing. Split out from
    /// <see cref="Write"/> so the cross-catalog link pass can stamp <c>paintIds</c> onto these
    /// records first -- that link needs the paint catalog's ids, which do not exist until the
    /// paint side has been assembled too.
    /// </summary>
    public static ProductAssembly Assemble(
        IEnumerable<CanonicalProductCatalog> catalogs,
        TaxonomyLabels labels)
    {
        var partitions = new Dictionary<string, ProductPartitionData>(StringComparer.Ordinal);
        var all = new List<ProductRecord>();
        foreach (var catalog in catalogs)
        {
            foreach (var p in catalog.Products)
            {
                // Slugs kept in the resolver's order (it writes them sorted), deduplicated, and
                // every one resolved to a label before anything is built -- an unknown slug is a
                // taxonomy fault and must fail the publish rather than produce a partition nobody
                // can name.
                var systemKeys = new List<string>();
                var systemLabels = new List<string>();
                foreach (var raw in p.GameSystems)
                {
                    if (string.IsNullOrWhiteSpace(raw)) continue;
                    string key = Slug.Make(raw);
                    if (systemKeys.Contains(key, StringComparer.Ordinal)) continue;
                    if (!labels.GameSystems.TryGetValue(key, out string? label))
                    {
                        throw new InvalidOperationException($"no label for game system slug '{key}' (product {p.Id})");
                    }
                    systemKeys.Add(key);
                    systemLabels.Add(label);
                }
                // Settings resolve the same way and fail the same way: a slug the taxonomy does
                // not declare is a data fault, not a value to pass through.
                var settingLabels = new List<string>();
                foreach (var raw in p.Settings)
                {
                    if (string.IsNullOrWhiteSpace(raw)) continue;
                    string key = Slug.Make(raw);
                    if (!labels.Settings.TryGetValue(key, out string? label))
                    {
                        throw new InvalidOperationException($"no label for setting slug '{key}' (product {p.Id})");
                    }
                    if (!settingLabels.Contains(label, StringComparer.Ordinal)) settingLabels.Add(label);
                }
                string? factionLabel = null;
                if (!string.IsNullOrEmpty(p.Faction))
                {
                    if (!labels.Factions.TryGetValue(p.Faction, out factionLabel))
                    {
                        throw new InvalidOperationException($"no label for faction slug '{p.Faction}' (product {p.Id})");
                    }
                }

                var extraEans = (p.AdditionalEans ?? [])
                    .Select(e => e?.Trim())
                    .Where(e => !string.IsNullOrEmpty(e))
                    .Select(e => e!)
                    .ToList();

                var supersedes = (p.Supersedes ?? [])
                    .Select(s => s?.Trim())
                    .Where(s => !string.IsNullOrEmpty(s))
                    .Select(s => s!)
                    .ToList();

                var extraCodes = (p.AdditionalCodes ?? [])
                    .Select(c => c?.Trim())
                    .Where(c => !string.IsNullOrEmpty(c))
                    .Select(c => c!)
                    .ToList();

                var record = new ProductRecord
                {
                    Id = p.Id,
                    Manufacturer = p.Manufacturer,
                    Ean = string.IsNullOrWhiteSpace(p.Ean) ? null : p.Ean.Trim(),
                    AdditionalEans = extraEans.Count > 0 ? extraEans : null,
                    AdditionalCodes = extraCodes.Count > 0 ? extraCodes : null,
                    EanConfidence = p.EanConfidence,
                    PriceGbp = p.PriceGbp,
                    PriceUsd = p.PriceUsd,
                    PriceEur = p.PriceEur,
                    PriceCad = p.PriceCad,
                    Name = p.Name,
                    GameSystems = systemLabels.Count > 0 ? systemLabels : null,
                    Settings = settingLabels.Count > 0 ? settingLabels : null,
                    Faction = factionLabel,
                    Category = p.Category,
                    Status = p.Status,
                    Availability = p.Availability ?? "unknown",
                    Quantity = p.Quantity ?? 1,
                    VolumeMl = p.VolumeMl,
                    WeightG = p.WeightG,
                    ProductCode = p.ProductCode ?? p.Sku,
                    Url = p.Url,
                    ImageUrl = p.ImageUrl,
                    Supersedes = supersedes.Count > 0 ? supersedes : null,
                    SupersededBy = string.IsNullOrWhiteSpace(p.SupersededBy) ? null : p.SupersededBy.Trim(),
                    BundleOf = string.IsNullOrWhiteSpace(p.BundleOf) ? null : p.BundleOf.Trim(),
                };

                // ONE AUTHORITATIVE LIST, and the partitions hold the same instances. Building
                // the consolidated document by concatenating the partitions -- which is what this
                // did -- publishes a two-system product twice the moment one exists.
                all.Add(record);
                for (int i = 0; i < systemKeys.Count; i++)
                {
                    if (!partitions.TryGetValue(systemKeys[i], out var data))
                    {
                        partitions[systemKeys[i]] = data = new ProductPartitionData(systemLabels[i], []);
                    }
                    data.Products.Add(record);
                }
            }
        }

        static int CompareProducts(ProductRecord a, ProductRecord b)
        {
            int c = string.CompareOrdinal(a.Name, b.Name);
            return c != 0 ? c : string.CompareOrdinal(a.Ean ?? "", b.Ean ?? "");
        }

        // Deterministic ordering everywhere for reproducible output / stable sha256.
        foreach (ProductPartitionData data in partitions.Values)
        {
            data.Products.Sort(CompareProducts);
        }
        all.Sort(CompareProducts);

        var orderedKeys = partitions.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();
        return new ProductAssembly(orderedKeys, partitions, all, labels);
    }

    /// <summary>Writes the consolidated document, the per-game-system partitions and the index.</summary>
    public static int Write(ProductAssembly assembly, Provenance prov, CatalogWriter writer)
    {
        IReadOnlyList<string> orderedKeys = assembly.OrderedKeys;
        IReadOnlyDictionary<string, ProductPartitionData> partitions = assembly.Partitions;
        List<ProductRecord> allProducts = [.. assembly.Records];
        int total = allProducts.Count;

        // `products` counts EVERY record, archival ones included -- a superseded product is still a
        // product you can own and scan. `currentProducts` is the subset nothing has replaced, so a
        // consumer showing "what's on the shelf" has the number without re-deriving it.
        static int CountCurrent(IEnumerable<ProductRecord> records) =>
            records.Count(r => r.SupersededBy is null);

        // Consolidated
        writer.Write("products.json", "product-catalog", "product-catalog", null, total,
            new ProductCatalogDocument
            {
                Version = prov.Version,
                GeneratedAt = prov.GeneratedAt,
                GitCommit = prov.GitCommit,
                Counts = new Dictionary<string, int>
                {
                    ["products"] = total,
                    ["currentProducts"] = CountCurrent(allProducts),
                    ["gameSystems"] = orderedKeys.Count,
                },
                Source = prov.SourceFor("products.json"),
                Products = allProducts,
            });

        // Partitions + index. Each game partition also names the SETTING it belongs to, and the
        // index lists the settings themselves, so a consumer can group the partitions by universe
        // -- "everything in Warhammer 40,000" is Kill Team + Necromunda + The Horus Heresy + the
        // flagship, and the index is where that grouping is published.
        TaxonomyLabels labels = assembly.Labels;
        var indexEntries = new List<IndexEntry>();
        var settingKeys = new SortedSet<string>(StringComparer.Ordinal);
        foreach (string key in orderedKeys)
        {
            ProductPartitionData data = partitions[key];
            string relPath = $"products/by-system/{key}.json";
            string? settingKey = labels.SettingOfGameSystem.TryGetValue(key, out string? s) ? s : null;
            if (settingKey is not null)
            {
                if (!labels.Settings.ContainsKey(settingKey))
                {
                    throw new InvalidOperationException($"game system '{key}' names setting '{settingKey}', which settings.yaml does not declare");
                }
                settingKeys.Add(settingKey);
            }
            writer.Write(relPath, "product-catalog", "product-catalog-partition", key, data.Products.Count,
                new ProductCatalogDocument
                {
                    Kind = "product-catalog-partition",
                    Version = prov.Version,
                    GeneratedAt = prov.GeneratedAt,
                    GitCommit = prov.GitCommit,
                    Partition = new Partition("gameSystem", key, data.Label),
                    Counts = new Dictionary<string, int>
                    {
                        ["products"] = data.Products.Count,
                        ["currentProducts"] = CountCurrent(data.Products),
                    },
                    Source = prov.SourceFor(relPath),
                    Products = data.Products,
                });
            indexEntries.Add(new IndexEntry(key, data.Label, data.Products.Count, relPath, settingKey));
        }

        writer.Write("products/index.json", "index", "product-index", null, total,
            new IndexDocument
            {
                Kind = "product-index",
                Version = prov.Version,
                GeneratedAt = prov.GeneratedAt,
                PartitionType = "gameSystem",
                Total = total,
                Partitions = indexEntries,
                Settings = settingKeys.Count > 0
                    ? settingKeys.Select(k => new SettingEntry(k, labels.Settings[k])).ToList()
                    : null,
            });

        return total;
    }
}

internal sealed record ProductPartitionData(string Label, List<ProductRecord> Products);

/// <summary>
/// Products built and ordered, but not yet serialized -- the handoff between
/// <see cref="ProductBuilder.Assemble"/> and <see cref="ProductBuilder.Write"/>.
///
/// The partition lists are the single source of truth; the consolidated order is derived from
/// them on demand by <see cref="Records"/>, exactly as it always was. Nothing caches a second
/// copy of a record, so a link pass that rewrites the partition lists cannot leave the
/// consolidated document holding stale, unlinked copies.
/// </summary>
internal sealed class ProductAssembly(
    List<string> orderedKeys,
    Dictionary<string, ProductPartitionData> partitions,
    List<ProductRecord> all,
    TaxonomyLabels labels)
{
    public IReadOnlyList<string> OrderedKeys => orderedKeys;

    /// <summary>The taxonomy the records were resolved against -- the index names settings from it.</summary>
    public TaxonomyLabels Labels => labels;

    public IReadOnlyDictionary<string, ProductPartitionData> Partitions => partitions;

    /// <summary>
    /// Every record exactly once, in name order. Held directly rather than derived by
    /// concatenating the partitions: a product may belong to more than one game system, and
    /// concatenation would publish it once per system.
    /// </summary>
    public IEnumerable<ProductRecord> Records => all;

    /// <summary>
    /// Rewrites every record in place, preserving order. Records are immutable, so a link pass
    /// replaces them rather than mutating them.
    ///
    /// <para>MAPPED ONCE PER PRODUCT, THEN DISTRIBUTED BY ID. The partitions hold the same
    /// instances as <see cref="Records"/>, and a product in two systems is in three lists at
    /// once; calling <paramref name="map"/> per list would run it two or three times for that
    /// product and leave each list holding a different instance of the same content.</para>
    /// </summary>
    public void MapRecords(Func<ProductRecord, ProductRecord> map)
    {
        var mapped = new Dictionary<string, ProductRecord>(all.Count, StringComparer.Ordinal);
        for (int i = 0; i < all.Count; i++)
        {
            ProductRecord replacement = map(all[i]);
            mapped[replacement.Id] = replacement;
            all[i] = replacement;
        }
        foreach (ProductPartitionData data in partitions.Values)
        {
            for (int i = 0; i < data.Products.Count; i++)
            {
                data.Products[i] = mapped[data.Products[i].Id];
            }
        }
    }
}
