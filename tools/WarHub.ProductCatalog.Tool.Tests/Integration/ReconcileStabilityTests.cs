using WarHub.CatalogStore.Reconcile;
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;
using WarHub.ProductCatalog.Tool.Reconcile;

namespace WarHub.ProductCatalog.Tool.Tests.Integration;

public class ReconcileStabilityTests
{
    private static Product P(string name, decimal? usd = null, string? firstSeen = "2026-07-07") => new()
    {
        Name = name, Category = "miniatures", Packaging = "single",
        Status = "current", FirstSeen = firstSeen, PriceUsd = usd,
        Availability = "in_stock",
    };

    [Fact]
    public async Task IdenticalRescrape_ProducesByteIdenticalFile()
    {
        var adapter = new ProductRecordAdapter();
        var reconciler = new CatalogReconciler<Product>(adapter);
        var noAliases = new Dictionary<string, string>();
        var noRetract = new HashSet<string>();

        var existing = new List<Product> { P("Wardens", 10m), P("Halberdiers", 20m) };
        var fresh = new List<Product> { P("Wardens", 10m, firstSeen: null), P("Halberdiers", 20m, firstSeen: null) };

        ReconcileResult<Product> r1 = reconciler.Reconcile(existing, fresh, noAliases, noRetract, "2026-07-07");
        ReconcileResult<Product> r2 = reconciler.Reconcile(r1.Records, fresh, noAliases, noRetract, "2026-07-08");

        string dir = Path.Combine(Path.GetTempPath(), $"stab-{Guid.NewGuid():N}");
        try
        {
            FactionCatalog Cat(IReadOnlyList<Product> p) => new()
            {
                Manufacturer = "CMON", ManufacturerSlug = "cmon",
                GameSystem = "ASOIAF", GameSystemSlug = "asoiaf",
                Faction = "Baratheon", FactionSlug = "baratheon",
                Products = p.ToList(),
            };
            await YamlCatalogWriter.WriteFactionAsync(Cat(r1.Records), dir);
            string first = await File.ReadAllTextAsync(Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml"));
            await YamlCatalogWriter.WriteFactionAsync(Cat(r2.Records), dir);
            string second = await File.ReadAllTextAsync(Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml"));

            Assert.Equal(first, second);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public void PartialScrape_KeepsAllRecords()
    {
        var reconciler = new CatalogReconciler<Product>(new ProductRecordAdapter());
        var existing = new List<Product> { P("A"), P("B"), P("C") };
        var fresh = new List<Product> { P("A") }; // B and C missing this run

        ReconcileResult<Product> result = reconciler.Reconcile(
            existing, fresh, new Dictionary<string, string>(), new HashSet<string>(), "2026-07-08");

        Assert.Equal(3, result.Records.Count);
    }
}
