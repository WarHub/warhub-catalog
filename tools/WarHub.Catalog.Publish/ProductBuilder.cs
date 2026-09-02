namespace WarHub.Catalog.Publish;

/// <summary>
/// Turns the canonical per-manufacturer product YAML into the consolidated +
/// per-game-system JSON documents. Every product is included; <c>ean</c> is optional, and so is
/// <c>gameSystem</c> -- a product genuinely belonging to no game system (a base, a gaming mat, a
/// paint/tool bundle, dice, an advent calendar, ...) has a null <c>GameSystem</c>. Such a
/// product is published in <c>products.json</c> / <c>products/index.json</c> like everything
/// else, but is excluded from every <c>products/by-system/*.json</c> partition -- it belongs to
/// none of them.
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
        var systemless = new List<ProductRecord>();
        foreach (var catalog in catalogs)
        {
            foreach (var p in catalog.Products)
            {
                string? gameSystemKey = null;
                string? gameSystemLabel = null;
                if (!string.IsNullOrEmpty(p.GameSystem))
                {
                    gameSystemKey = Slug.Make(p.GameSystem);
                    if (!labels.GameSystems.TryGetValue(gameSystemKey, out gameSystemLabel))
                    {
                        throw new InvalidOperationException($"no label for game system slug '{gameSystemKey}' (product {p.Id})");
                    }
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

                var record = new ProductRecord
                {
                    Id = p.Id,
                    Manufacturer = p.Manufacturer,
                    Ean = string.IsNullOrWhiteSpace(p.Ean) ? null : p.Ean.Trim(),
                    AdditionalEans = extraEans.Count > 0 ? extraEans : null,
                    EanConfidence = p.EanConfidence,
                    PriceGbp = p.PriceGbp,
                    PriceUsd = p.PriceUsd,
                    PriceEur = p.PriceEur,
                    PriceCad = p.PriceCad,
                    Name = p.Name,
                    GameSystem = gameSystemLabel,
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
                };

                if (gameSystemKey is null)
                {
                    systemless.Add(record);
                    continue;
                }

                if (!partitions.TryGetValue(gameSystemKey, out var data))
                {
                    partitions[gameSystemKey] = data = new ProductPartitionData(gameSystemLabel!, []);
                }
                data.Products.Add(record);
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
        systemless.Sort(CompareProducts);

        var orderedKeys = partitions.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();
        return new ProductAssembly(orderedKeys, partitions, systemless);
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

        // Partitions + index
        var indexEntries = new List<IndexEntry>();
        foreach (string key in orderedKeys)
        {
            ProductPartitionData data = partitions[key];
            string relPath = $"products/by-system/{key}.json";
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
            indexEntries.Add(new IndexEntry(key, data.Label, data.Products.Count, relPath));
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
    List<ProductRecord> systemless)
{
    public IReadOnlyList<string> OrderedKeys => orderedKeys;

    public IReadOnlyDictionary<string, ProductPartitionData> Partitions => partitions;

    /// <summary>
    /// Every record in consolidated order: each game system in key order, then the systemless
    /// products (they have no partition key to order them alongside).
    /// </summary>
    public IEnumerable<ProductRecord> Records =>
        orderedKeys.SelectMany(k => partitions[k].Products).Concat(systemless);

    /// <summary>
    /// Rewrites every record in place, preserving order. Records are immutable, so a link pass
    /// replaces them rather than mutating them.
    /// </summary>
    public void MapRecords(Func<ProductRecord, ProductRecord> map)
    {
        foreach (ProductPartitionData data in partitions.Values)
        {
            Rewrite(data.Products, map);
        }
        Rewrite(systemless, map);
    }

    private static void Rewrite(List<ProductRecord> records, Func<ProductRecord, ProductRecord> map)
    {
        for (int i = 0; i < records.Count; i++)
        {
            records[i] = map(records[i]);
        }
    }
}
