using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

public class CanonicalYamlSourceTests
{
    private static string WriteTempCatalog()
    {
        string root = Directory.CreateTempSubdirectory("canonical-src").FullName;
        Directory.CreateDirectory(Path.Combine(root, "products"));
        Directory.CreateDirectory(Path.Combine(root, "taxonomy"));
        File.WriteAllText(Path.Combine(root, "products", "test-mfg.yaml"), """
            manufacturer: test-mfg
            products:
              - id: test-mfg/99120110077
                name: 'Combat Patrol: Necrons'
                manufacturer: test-mfg
                productCode: '99120110077'
                sku: '99120110077'
                ean: '5011921194285'
                eanConfidence: confirmed
                gameSystem: test-system
                faction: necrons
                category: miniatures
                quantity: 11
                status: current
                availability: in_stock
                firstSeen: '2026-07-07'
                priceGbp: 76.5
                url: https://example/necrons
                evidence:
                  - legacy-catalog:test-mfg/test-system/necrons/combat-patrol-necrons
            """);
        File.WriteAllText(Path.Combine(root, "taxonomy", "game-systems.yaml"), """
            gameSystems:
              - slug: test-system
                label: Test System
            """);
        File.WriteAllText(Path.Combine(root, "taxonomy", "factions.yaml"), """
            factions:
              - slug: necrons
                label: Necrons
            """);
        return root;
    }

    [Fact]
    public void LoadCanonicalCatalogs_reads_flat_manufacturer_files()
    {
        var catalogs = YamlSource.LoadCanonicalCatalogs(WriteTempCatalog()).ToList();
        var catalog = Assert.Single(catalogs);
        Assert.Equal("test-mfg", catalog.Manufacturer);
        var product = Assert.Single(catalog.Products);
        Assert.Equal("test-mfg/99120110077", product.Id);
        Assert.Equal("5011921194285", product.Ean);
        Assert.Equal("confirmed", product.EanConfidence);
        Assert.Equal(11, product.Quantity);
        Assert.Equal("test-system", product.GameSystem);
        Assert.Equal(76.5m, product.PriceGbp);
    }

    [Fact]
    public void LoadTaxonomyLabels_reads_label_maps()
    {
        var labels = YamlSource.LoadTaxonomyLabels(WriteTempCatalog());
        Assert.Equal("Test System", labels.GameSystems["test-system"]);
        Assert.Equal("Necrons", labels.Factions["necrons"]);
    }

    [Fact]
    public void LoadTaxonomyLabels_missing_files_yield_empty_maps()
    {
        string root = Directory.CreateTempSubdirectory("canonical-empty").FullName;
        var labels = YamlSource.LoadTaxonomyLabels(root);
        Assert.Empty(labels.GameSystems);
        Assert.Empty(labels.Factions);
    }
}
