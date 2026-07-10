using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.Catalog.Publish;

/// <summary>
/// Turns the per-faction product YAML into the consolidated + per-game-system JSON
/// documents. Every product is included; <c>ean</c> is optional.
/// </summary>
internal static class ProductBuilder
{
    private sealed record PartitionData(string Label, List<ProductRecord> Products);

    public static int Build(IEnumerable<FactionCatalog> factions, Provenance prov, CatalogWriter writer)
    {
        var partitions = new Dictionary<string, PartitionData>(StringComparer.Ordinal);

        foreach (FactionCatalog faction in factions)
        {
            string key = Slug.Make(faction.GameSystemSlug is { Length: > 0 } gss ? gss : faction.GameSystem);
            if (!partitions.TryGetValue(key, out PartitionData? data))
            {
                data = new PartitionData(faction.GameSystem, []);
                partitions[key] = data;
            }

            foreach (Product p in faction.Products)
            {
                data.Products.Add(new ProductRecord(
                    Ean: string.IsNullOrWhiteSpace(p.Ean) ? null : p.Ean.Trim(),
                    Name: p.Name,
                    GameSystem: faction.GameSystem,
                    Faction: faction.Faction,
                    Category: p.Category,
                    Status: p.Status,
                    Availability: p.Availability,
                    Quantity: 1,
                    ProductCode: p.ProductCode ?? p.Sku,
                    Url: p.Url,
                    ImageUrl: p.ImageUrl));
            }
        }

        // Deterministic ordering everywhere for reproducible output / stable sha256.
        foreach (PartitionData data in partitions.Values)
        {
            data.Products.Sort(static (a, b) =>
            {
                int c = string.CompareOrdinal(a.Name, b.Name);
                return c != 0 ? c : string.CompareOrdinal(a.Ean ?? "", b.Ean ?? "");
            });
        }

        var orderedKeys = partitions.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();
        var allProducts = orderedKeys.SelectMany(k => partitions[k].Products).ToList();
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
