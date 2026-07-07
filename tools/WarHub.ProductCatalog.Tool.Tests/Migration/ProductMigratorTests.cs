using WarHub.ProductCatalog.Tool.Migration;

namespace WarHub.ProductCatalog.Tool.Tests.Migration;

public class ProductMigratorTests
{
    private static string SeedLegacyTree()
    {
        string dir = Path.Combine(Path.GetTempPath(), $"mig-{Guid.NewGuid():N}");
        string factionDir = Path.Combine(dir, "manufacturers", "cmon", "asoiaf");
        Directory.CreateDirectory(factionDir);
        File.WriteAllText(Path.Combine(factionDir, "baratheon.yaml"), """
            manufacturer: CMON
            manufacturerSlug: cmon
            gameSystem: ASOIAF
            gameSystemSlug: asoiaf
            faction: Baratheon
            factionSlug: baratheon
            productCount: 2
            products:
            - name: 'Baratheon: Wardens'
              productType: single_kit
              ean: 889696010223
              status: current
            - name: 'Baratheon: Terrain Pack'
              productType: terrain
              status: discontinued
            """);
        return dir;
    }

    [Fact]
    public async Task Migrate_TransformsSchema_AndQuotesEan()
    {
        string dir = SeedLegacyTree();
        try
        {
            await ProductMigrator.MigrateAsync(dir, "2026-07-07", default);
            string yaml = await File.ReadAllTextAsync(
                Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml"));

            Assert.Contains("ean: '889696010223'", yaml);
            Assert.Contains("category: miniatures", yaml);
            Assert.Contains("packaging: single", yaml);
            Assert.Contains("category: terrain", yaml);
            Assert.Contains("firstSeen: '2026-07-07'", yaml);
            Assert.DoesNotContain("productType", yaml);
            Assert.DoesNotContain("productCount", yaml);
            Assert.True(File.Exists(Path.Combine(dir, "_liveness.yaml")));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task Migrate_MapsLegacyStatusToStatusAndAvailability()
    {
        string dir = SeedLegacyTree();
        try
        {
            await ProductMigrator.MigrateAsync(dir, "2026-07-07", default);
            string yaml = await File.ReadAllTextAsync(
                Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml"));

            // 'current' legacy status -> status: current, availability: in_stock
            Assert.Contains("status: current", yaml);
            Assert.Contains("availability: in_stock", yaml);

            // 'discontinued' legacy status -> status: discontinued, availability: out_of_stock
            Assert.Contains("status: discontinued", yaml);
            Assert.Contains("availability: out_of_stock", yaml);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task Migrate_IsIdempotent()
    {
        string dir = SeedLegacyTree();
        try
        {
            await ProductMigrator.MigrateAsync(dir, "2026-07-07", default);
            string file = Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml");
            string first = await File.ReadAllTextAsync(file);

            await ProductMigrator.MigrateAsync(dir, "2099-01-01", default); // different date must NOT change firstSeen
            string second = await File.ReadAllTextAsync(file);

            Assert.Equal(first, second);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }
}
