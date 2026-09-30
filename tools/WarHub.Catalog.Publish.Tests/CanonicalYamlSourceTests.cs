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
                additionalEans:
                  - '5011921194506'
                supersedes:
                  - test-mfg/99120110076
                gameSystems:
                  - test-system
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
                setting: test-setting
            """);
        File.WriteAllText(Path.Combine(root, "taxonomy", "settings.yaml"), """
            settings:
              - slug: test-setting
                label: Test Setting
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
        Assert.Equal(["5011921194506"], product.AdditionalEans);
        Assert.Equal(["test-mfg/99120110076"], product.Supersedes);
        Assert.Equal(11, product.Quantity);
        Assert.Equal(["test-system"], product.GameSystems);
        Assert.Equal(76.5m, product.PriceGbp);
    }

    private static string WriteProducts(params (string File, string Manufacturer, string[] Ids)[] files)
    {
        string root = Directory.CreateTempSubdirectory("canonical-shards").FullName;
        Directory.CreateDirectory(Path.Combine(root, "products"));
        foreach ((string file, string manufacturer, string[] ids) in files)
        {
            string rows = string.Concat(ids.Select(id =>
                $"  - id: {id}\n    name: {id}\n    manufacturer: {manufacturer}\n    status: current\n"));
            File.WriteAllText(Path.Combine(root, "products", file), $"manufacturer: {manufacturer}\nproducts:\n{rows}");
        }
        return root;
    }

    [Fact]
    public void LoadCanonicalCatalogs_merges_a_sharded_manufacturer_back_into_one_catalog_in_id_order()
    {
        // The resolver's shard names (layout.py): a longest-prefix shard per code prefix and `_` for
        // the rest. Read file by file, the ids arrive out of order -- `99.yaml` sorts before
        // `991.yaml` but holds 997. Merged, they come out as the single file held them.
        string root = WriteProducts(
            ("big-mfg._.yaml", "big-mfg", ["big-mfg/WG-1", "big-mfg/abc"]),
            ("big-mfg.99.yaml", "big-mfg", ["big-mfg/997"]),
            ("big-mfg.991.yaml", "big-mfg", ["big-mfg/9910", "big-mfg/9912"]),
            ("small-mfg.yaml", "small-mfg", ["small-mfg/1"]));

        var catalogs = YamlSource.LoadCanonicalCatalogs(root).ToList();

        Assert.Equal(["big-mfg", "small-mfg"], catalogs.Select(c => c.Manufacturer));
        Assert.Equal(
            ["big-mfg/9910", "big-mfg/9912", "big-mfg/997", "big-mfg/WG-1", "big-mfg/abc"],
            catalogs[0].Products.Select(p => p.Id));
    }

    [Fact]
    public void LoadCanonicalCatalogs_refuses_an_id_two_files_hold()
    {
        string root = WriteProducts(
            ("big-mfg.9.yaml", "big-mfg", ["big-mfg/91"]),
            ("big-mfg.91.yaml", "big-mfg", ["big-mfg/91"]));
        var ex = Assert.Throws<InvalidOperationException>(() => YamlSource.LoadCanonicalCatalogs(root));
        Assert.Contains("big-mfg/91", ex.Message);
    }

    [Fact]
    public void LoadCanonicalCatalogs_refuses_a_file_that_names_another_manufacturer()
    {
        string root = WriteProducts(("big-mfg.9.yaml", "other-mfg", ["other-mfg/9"]));
        var ex = Assert.Throws<InvalidOperationException>(() => YamlSource.LoadCanonicalCatalogs(root));
        Assert.Contains("big-mfg.9.yaml", ex.Message);
    }

    [Fact]
    public void LoadTaxonomyLabels_reads_label_maps()
    {
        var labels = YamlSource.LoadTaxonomyLabels(WriteTempCatalog());
        Assert.Equal("Test System", labels.GameSystems["test-system"]);
        Assert.Equal("test-setting", labels.SettingOfGameSystem["test-system"]);
        Assert.Equal("Test Setting", labels.Settings["test-setting"]);
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
