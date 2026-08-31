using System.Text.Json;
using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// ProductBuilder must fail loudly (not silently drop or default) when a canonical product
/// references taxonomy that isn't there -- these are data-integrity bugs (a bad slug, a
/// missing faction label) that should stop the build, not produce a quietly wrong catalog. An
/// EMPTY gameSystems is NOT one of these -- it is a valid, expected state (a product genuinely
/// belonging to no game system) and must publish, not throw. Neither is a product belonging to
/// SEVERAL, which lands in several partitions and in the consolidated document exactly once.
/// </summary>
public sealed class ProductBuilderGuardTests
{
    private static readonly TaxonomyLabels EmptyLabels = new(
        new Dictionary<string, string>(), new Dictionary<string, string>());

    private static CatalogWriter Writer() => WriterWithDist().Writer;

    private static (CatalogWriter Writer, string Dist) WriterWithDist()
    {
        string schemaDir = Path.Combine(AppContext.BaseDirectory, "schema");
        string dist = Path.Combine(Path.GetTempPath(), "warhub-catalog-guard-tests", Guid.NewGuid().ToString("N"));
        return (new CatalogWriter(dist, SchemaValidator.LoadFrom(schemaDir)), dist);
    }

    private static Provenance Prov() => new()
    {
        Version = "guard-test",
        GeneratedAt = "2026-07-12T00:00:00Z",
        Repo = "WarHub/warhub-catalog",
    };

    private static CanonicalProductCatalog CatalogOf(CanonicalProduct product) => new()
    {
        Manufacturer = product.Manufacturer,
        Products = [product],
    };

    [Fact]
    public void Null_game_system_publishes_and_is_excluded_from_by_system_partitions()
    {
        var product = new CanonicalProduct
        {
            Id = "test-mfg/no-game-system",
            Name = "Mystery Box",
            Manufacturer = "test-mfg",
            Status = "current",
            GameSystems = [],
        };

        (CatalogWriter writer, string dist) = WriterWithDist();

        int total = ProductBuilder.Build([CatalogOf(product)], EmptyLabels, Prov(), writer);

        Assert.Equal(1, total);
        // no by-system partition file was written at all -- the product belongs to none.
        Assert.DoesNotContain(writer.Files, f => f.Path.StartsWith("products/by-system/", StringComparison.Ordinal));

        string productsJson = File.ReadAllText(Path.Combine(dist, "products.json"));
        using JsonDocument doc = JsonDocument.Parse(productsJson);
        JsonElement onlyProduct = Assert.Single(doc.RootElement.GetProperty("products").EnumerateArray());
        Assert.Equal("Mystery Box", onlyProduct.GetProperty("name").GetString());
        Assert.False(onlyProduct.TryGetProperty("gameSystem", out _)); // null -> omitted, not published as null
    }

    [Fact]
    public void Additional_eans_of_a_repackaged_product_flow_into_products_json()
    {
        // A product repackaged over time carries extra barcodes; `ean` stays the single primary
        // one and the rest publish under `additionalEans` (validated against the product schema by
        // the writer). Existing single-barcode consumers keep reading `ean` unchanged.
        var product = new CanonicalProduct
        {
            Id = "mantic-games/MGKWB112",
            Name = "Basilean Army",
            Manufacturer = "mantic-games",
            Status = "current",
            Ean = "5060924985581",
            EanConfidence = "confirmed",
            AdditionalEans = ["5060469664330"],
            GameSystems = [],
        };

        (CatalogWriter writer, string dist) = WriterWithDist();
        ProductBuilder.Build([CatalogOf(product)], EmptyLabels, Prov(), writer);

        string productsJson = File.ReadAllText(Path.Combine(dist, "products.json"));
        using JsonDocument doc = JsonDocument.Parse(productsJson);
        JsonElement p = Assert.Single(doc.RootElement.GetProperty("products").EnumerateArray());
        Assert.Equal("5060924985581", p.GetProperty("ean").GetString());
        string[] extra = p.GetProperty("additionalEans").EnumerateArray().Select(e => e.GetString()!).ToArray();
        Assert.Equal(["5060469664330"], extra);
    }

    [Fact]
    public void Single_barcode_product_omits_additional_eans()
    {
        var product = new CanonicalProduct
        {
            Id = "test-mfg/single",
            Name = "Single Barcode",
            Manufacturer = "test-mfg",
            Status = "current",
            Ean = "5060924985581",
            AdditionalEans = null,
            GameSystems = [],
        };

        (CatalogWriter writer, string dist) = WriterWithDist();
        ProductBuilder.Build([CatalogOf(product)], EmptyLabels, Prov(), writer);

        string productsJson = File.ReadAllText(Path.Combine(dist, "products.json"));
        using JsonDocument doc = JsonDocument.Parse(productsJson);
        JsonElement p = Assert.Single(doc.RootElement.GetProperty("products").EnumerateArray());
        Assert.False(p.TryGetProperty("additionalEans", out _)); // null -> omitted, never published as []
    }

    [Fact]
    public void Supersession_link_publishes_on_both_records_and_counts_current_separately()
    {
        // Archival lineage: a retired product code keeps its own record and barcode and points
        // forward; the current one points back. `counts.products` includes the retired record
        // (somebody still owns that box) and `counts.currentProducts` is the subset on the shelf.
        var retired = new CanonicalProduct
        {
            Id = "games-workshop/99120204012",
            Name = "Dryads",
            Manufacturer = "games-workshop",
            Status = "discontinued",
            Ean = "5011921062164",
            EanConfidence = "confirmed",
            SupersededBy = "games-workshop/99120204035",
            GameSystems = [],
        };
        var current = new CanonicalProduct
        {
            Id = "games-workshop/99120204035",
            Name = "Dryads",
            Manufacturer = "games-workshop",
            Status = "current",
            Ean = "5011921179398",
            EanConfidence = "confirmed",
            Supersedes = ["games-workshop/99120204012"],
            GameSystems = [],
        };

        (CatalogWriter writer, string dist) = WriterWithDist();
        int total = ProductBuilder.Build(
            [new CanonicalProductCatalog { Manufacturer = "games-workshop", Products = [retired, current] }],
            EmptyLabels, Prov(), writer);

        Assert.Equal(2, total);
        string productsJson = File.ReadAllText(Path.Combine(dist, "products.json"));
        using JsonDocument doc = JsonDocument.Parse(productsJson);
        JsonElement counts = doc.RootElement.GetProperty("counts");
        Assert.Equal(2, counts.GetProperty("products").GetInt32());
        Assert.Equal(1, counts.GetProperty("currentProducts").GetInt32());

        JsonElement[] published = [.. doc.RootElement.GetProperty("products").EnumerateArray()];
        JsonElement old = published.Single(p => p.GetProperty("id").GetString() == "games-workshop/99120204012");
        JsonElement now = published.Single(p => p.GetProperty("id").GetString() == "games-workshop/99120204035");
        Assert.Equal("games-workshop/99120204035", old.GetProperty("supersededBy").GetString());
        Assert.False(old.TryGetProperty("supersedes", out _));      // null -> omitted, never []
        Assert.Equal(
            ["games-workshop/99120204012"],
            now.GetProperty("supersedes").EnumerateArray().Select(e => e.GetString()!).ToArray());
        Assert.False(now.TryGetProperty("supersededBy", out _));
        // the retired record keeps its own barcode -- it is NOT an additionalEans of the survivor
        Assert.Equal("5011921062164", old.GetProperty("ean").GetString());
        Assert.False(now.TryGetProperty("additionalEans", out _));
    }

    [Fact]
    public void Missing_game_system_label_throws_naming_the_slug()
    {
        var product = new CanonicalProduct
        {
            Id = "test-mfg/unmapped-system",
            Name = "Mystery Box",
            Manufacturer = "test-mfg",
            Status = "current",
            GameSystems = ["no-such-system"],
        };

        var ex = Assert.Throws<InvalidOperationException>(
            () => ProductBuilder.Build([CatalogOf(product)], EmptyLabels, Prov(), Writer()));

        Assert.Contains("no-such-system", ex.Message, StringComparison.Ordinal);
        Assert.Contains("test-mfg/unmapped-system", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Missing_faction_label_throws_naming_the_slug()
    {
        var labels = new TaxonomyLabels(
            new Dictionary<string, string> { ["warhammer-40k"] = "Warhammer 40,000" },
            new Dictionary<string, string>());
        var product = new CanonicalProduct
        {
            Id = "test-mfg/unmapped-faction",
            Name = "Mystery Box",
            Manufacturer = "test-mfg",
            Status = "current",
            GameSystems = ["warhammer-40k"],
            Faction = "no-such-faction",
        };

        var ex = Assert.Throws<InvalidOperationException>(
            () => ProductBuilder.Build([CatalogOf(product)], labels, Prov(), Writer()));

        Assert.Contains("no-such-faction", ex.Message, StringComparison.Ordinal);
        Assert.Contains("test-mfg/unmapped-faction", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void A_product_in_two_systems_lands_in_both_partitions_and_the_catalog_once()
    {
        // THE INVARIANT THAT STOPPED BEING ONE NUMBER. `products.json` used to be built by
        // concatenating the partitions, which was correct only while every product had at most one
        // game system. GW's own store shelves 183 products under two, so that concatenation would
        // now publish each of them twice -- with the same id, in the same document.
        var labels = new TaxonomyLabels(
            new Dictionary<string, string>
            {
                ["warhammer-40k"] = "Warhammer 40,000",
                ["horus-heresy"] = "The Horus Heresy",
            },
            new Dictionary<string, string>());
        var dual = new CanonicalProduct
        {
            Id = "test-mfg/dual",
            Name = "Custodian Guard",
            Manufacturer = "test-mfg",
            Status = "current",
            GameSystems = ["horus-heresy", "warhammer-40k"],
        };
        var single = new CanonicalProduct
        {
            Id = "test-mfg/single",
            Name = "Aggressors",
            Manufacturer = "test-mfg",
            Status = "current",
            GameSystems = ["warhammer-40k"],
        };

        (CatalogWriter writer, string dist) = WriterWithDist();
        int total = ProductBuilder.Build([CatalogOf2(dual, single)], labels, Prov(), writer);

        Assert.Equal(2, total);
        using JsonDocument all = JsonDocument.Parse(File.ReadAllText(Path.Combine(dist, "products.json")));
        string[] ids = [.. all.RootElement.GetProperty("products").EnumerateArray()
            .Select(p => p.GetProperty("id").GetString()!)];
        Assert.Equal(["test-mfg/dual", "test-mfg/single"], [.. ids.Order(StringComparer.Ordinal)]);

        // ...and it names both systems, by LABEL, in slug order.
        JsonElement published = all.RootElement.GetProperty("products").EnumerateArray()
            .Single(p => p.GetProperty("id").GetString() == "test-mfg/dual");
        Assert.Equal(
            ["The Horus Heresy", "Warhammer 40,000"],
            [.. published.GetProperty("gameSystems").EnumerateArray().Select(v => v.GetString()!)]);

        Assert.Equal(["test-mfg/dual"], PartitionIds(dist, "horus-heresy"));
        Assert.Equal(["test-mfg/dual", "test-mfg/single"], PartitionIds(dist, "warhammer-40k"));

        // The index totals the PRODUCTS, not the partition rows -- those now sum to more.
        using JsonDocument index = JsonDocument.Parse(
            File.ReadAllText(Path.Combine(dist, "products", "index.json")));
        Assert.Equal(2, index.RootElement.GetProperty("total").GetInt32());
        Assert.Equal(3, index.RootElement.GetProperty("partitions").EnumerateArray()
            .Sum(p => p.GetProperty("records").GetInt32()));
    }

    private static string[] PartitionIds(string dist, string key)
    {
        using JsonDocument doc = JsonDocument.Parse(
            File.ReadAllText(Path.Combine(dist, "products", "by-system", key + ".json")));
        return [.. doc.RootElement.GetProperty("products").EnumerateArray()
            .Select(p => p.GetProperty("id").GetString()!).Order(StringComparer.Ordinal)];
    }

    private static CanonicalProductCatalog CatalogOf2(params CanonicalProduct[] products) => new()
    {
        Manufacturer = products[0].Manufacturer,
        Products = [.. products],
    };
}
