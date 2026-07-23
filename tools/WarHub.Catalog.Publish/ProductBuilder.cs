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
    private sealed record PartitionData(string Label, List<ProductRecord> Products);

    public static int Build(
        IEnumerable<CanonicalProductCatalog> catalogs,
        TaxonomyLabels labels,
        Provenance prov,
        CatalogWriter writer)
    {
        var partitions = new Dictionary<string, PartitionData>(StringComparer.Ordinal);
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

                var record = new ProductRecord
                {
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
                    Category = p.Category ?? "miniatures",
                    Status = p.Status,
                    Availability = p.Availability ?? "unknown",
                    Quantity = p.Quantity ?? 1,
                    VolumeMl = p.VolumeMl,
                    ProductCode = p.ProductCode ?? p.Sku,
                    Url = p.Url,
                    ImageUrl = p.ImageUrl,
                };

                if (gameSystemKey is null)
                {
                    systemless.Add(record);
                    continue;
                }

                if (!partitions.TryGetValue(gameSystemKey, out var data))
                {
                    partitions[gameSystemKey] = data = new PartitionData(gameSystemLabel!, []);
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
        foreach (PartitionData data in partitions.Values)
        {
            data.Products.Sort(CompareProducts);
        }
        systemless.Sort(CompareProducts);

        var orderedKeys = partitions.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();
        // Systemless products sort after every partitioned game system in the consolidated
        // list -- they have no partition key to order them alongside.
        var allProducts = orderedKeys.SelectMany(k => partitions[k].Products).Concat(systemless).ToList();
        int total = allProducts.Count;

        // Consolidated
        writer.Write("products.json", "product-catalog", "product-catalog", null, total,
            new ProductCatalogDocument
            {
                Version = prov.Version,
                GeneratedAt = prov.GeneratedAt,
                GitCommit = prov.GitCommit,
                Counts = new Dictionary<string, int> { ["products"] = total, ["gameSystems"] = orderedKeys.Count },
                Source = prov.SourceFor("products.json"),
                Products = allProducts,
            });

        // Partitions + index
        var indexEntries = new List<IndexEntry>();
        foreach (string key in orderedKeys)
        {
            PartitionData data = partitions[key];
            string relPath = $"products/by-system/{key}.json";
            writer.Write(relPath, "product-catalog", "product-catalog-partition", key, data.Products.Count,
                new ProductCatalogDocument
                {
                    Kind = "product-catalog-partition",
                    Version = prov.Version,
                    GeneratedAt = prov.GeneratedAt,
                    GitCommit = prov.GitCommit,
                    Partition = new Partition("gameSystem", key, data.Label),
                    Counts = new Dictionary<string, int> { ["products"] = data.Products.Count },
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
