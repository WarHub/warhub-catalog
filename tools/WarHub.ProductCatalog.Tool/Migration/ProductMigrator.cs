using WarHub.CatalogStore;
using WarHub.CatalogStore.Ledger;
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;

namespace WarHub.ProductCatalog.Tool.Migration;

/// <summary>
/// One-time, idempotent migration of legacy faction files into the new schema.
/// Backfills firstSeen only when absent, so re-running never changes existing dates.
/// Also splits the legacy single `status` field into the new `status` (lifecycle) +
/// `availability` (volatile purchasability) pair — see
/// docs/superpowers/specs/2026-07-07-availability-lifecycle-addendum.md, section 3.
/// </summary>
public static class ProductMigrator
{
    // Legacy shape tolerant of old fields.
    private sealed record LegacyCatalog
    {
        public string Manufacturer { get; init; } = "";
        public string ManufacturerSlug { get; init; } = "";
        public string GameSystem { get; init; } = "";
        public string GameSystemSlug { get; init; } = "";
        public string Faction { get; init; } = "";
        public string FactionSlug { get; init; } = "";
        public List<LegacyProduct> Products { get; init; } = new();
    }

    private sealed record LegacyProduct
    {
        public string Name { get; init; } = "";
        public string? ProductType { get; init; }
        public string? Category { get; init; }
        public string? Packaging { get; init; }
        public string? Status { get; init; }
        public string? Availability { get; init; }
        public string? FirstSeen { get; init; }
        public string? Ean { get; init; }
        public string? EanSource { get; init; }
        public string? Sku { get; init; }
        public string? ProductCode { get; init; }
        public decimal? PriceGbp { get; init; }
        public decimal? PriceUsd { get; init; }
        public decimal? PriceEur { get; init; }
        public string? Url { get; init; }
        public string? ImageUrl { get; init; }
        public string? ReleaseDate { get; init; }
        public string? Description { get; init; }
        public List<ProductUnit>? Contents { get; init; }
    }

    public static async Task<int> MigrateAsync(string dataDir, string migrationDate, CancellationToken ct)
    {
        string manufacturersDir = Path.Combine(dataDir, "manufacturers");
        if (!Directory.Exists(manufacturersDir))
            return 0;

        var deserializer = CatalogSerializer.CreateDeserializer();
        var ledger = await LedgerStore.LoadAsync(Path.Combine(dataDir, "_liveness.yaml"), ct);

        foreach (string file in Directory.GetFiles(manufacturersDir, "*.yaml", SearchOption.AllDirectories).OrderBy(f => f))
        {
            ct.ThrowIfCancellationRequested();
            LegacyCatalog? legacy = deserializer.Deserialize<LegacyCatalog>(await File.ReadAllTextAsync(file, ct));
            if (legacy is null)
                continue;

            var products = legacy.Products.Select(lp =>
            {
                (string category, string packaging) = MapType(lp);
                (string status, string availability) = MapStatus(lp);
                string firstSeen = string.IsNullOrWhiteSpace(lp.FirstSeen) ? migrationDate : lp.FirstSeen!;
                var product = new Product
                {
                    Name = lp.Name,
                    Category = category,
                    Packaging = packaging,
                    Status = status,
                    Availability = availability,
                    FirstSeen = firstSeen,
                    Ean = lp.Ean,
                    EanSource = lp.EanSource,
                    Sku = lp.Sku,
                    ProductCode = lp.ProductCode,
                    PriceGbp = lp.PriceGbp,
                    PriceUsd = lp.PriceUsd,
                    PriceEur = lp.PriceEur,
                    Url = lp.Url,
                    ImageUrl = lp.ImageUrl,
                    ReleaseDate = lp.ReleaseDate,
                    Description = lp.Description,
                    Contents = lp.Contents,
                };

                string ledgerKey = $"{legacy.ManufacturerSlug}/{legacy.GameSystemSlug}/{legacy.FactionSlug}/{NameNormalizer.Normalize(lp.Name)}";
                if (!ledger.Records.ContainsKey(ledgerKey))
                    ledger.Records[ledgerKey] = new LedgerRecord { LastSeen = migrationDate, MissStreak = 0 };
                return product;
            })
            .OrderBy(p => NameNormalizer.Normalize(p.Name), StringComparer.Ordinal)
            .ToList();

            var catalog = new FactionCatalog
            {
                Manufacturer = legacy.Manufacturer,
                ManufacturerSlug = legacy.ManufacturerSlug,
                GameSystem = legacy.GameSystem,
                GameSystemSlug = legacy.GameSystemSlug,
                Faction = legacy.Faction,
                FactionSlug = legacy.FactionSlug,
                Products = products,
            };

            await YamlCatalogWriter.WriteFactionAsync(catalog, dataDir);
        }

        await LedgerStore.SaveAsync(Path.Combine(dataDir, "_liveness.yaml"), ledger, ct);
        return 0;
    }

    private static (string Category, string Packaging) MapType(LegacyProduct lp)
    {
        // Already-migrated files keep their category/packaging (idempotency).
        if (!string.IsNullOrWhiteSpace(lp.Category) && !string.IsNullOrWhiteSpace(lp.Packaging))
            return (lp.Category!, lp.Packaging!);

        return lp.ProductType switch
        {
            "terrain" => ("terrain", "single"),
            "book" => ("book", "single"),
            "paint_set" => ("paint", "bundle"),
            "combat_patrol" or "battleforce" or "army_box" or "box_set" => ("miniatures", "box"),
            "starter_set" => ("miniatures", "starter"),
            _ => ("miniatures", "single"),
        };
    }

    private static (string Status, string Availability) MapStatus(LegacyProduct lp)
    {
        // Already-migrated files carry a new-vocab availability — keep both values as-is (idempotency),
        // preserving any human/ledger lifecycle (delisted / suspected-discontinued / discontinued).
        if (!string.IsNullOrWhiteSpace(lp.Availability))
            return (string.IsNullOrWhiteSpace(lp.Status) ? "current" : lp.Status!, lp.Availability!);

        return lp.Status?.Trim().ToLowerInvariant() switch
        {
            "discontinued" => ("discontinued", "out_of_stock"),
            "pre_order" => ("current", "pre_order"),
            "out_of_stock" => ("current", "out_of_stock"),
            "limited" => ("current", "limited"),
            "current" => ("current", "in_stock"),
            _ => ("current", "unknown"),
        };
    }
}
