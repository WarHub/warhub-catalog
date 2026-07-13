using System.Text.Json;
using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// ProductBuilder must fail loudly (not silently drop or default) when a canonical product
/// references taxonomy that isn't there -- these are data-integrity bugs (a bad slug, a
/// missing faction label) that should stop the build, not produce a quietly wrong catalog. A
/// null gameSystem is NOT one of these -- it is a valid, expected state (a product genuinely
/// belonging to no game system) and must publish, not throw.
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
            GameSystem = null,
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
    public void Missing_game_system_label_throws_naming_the_slug()
    {
        var product = new CanonicalProduct
        {
            Id = "test-mfg/unmapped-system",
            Name = "Mystery Box",
            Manufacturer = "test-mfg",
            Status = "current",
            GameSystem = "no-such-system",
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
            GameSystem = "warhammer-40k",
            Faction = "no-such-faction",
        };

        var ex = Assert.Throws<InvalidOperationException>(
            () => ProductBuilder.Build([CatalogOf(product)], labels, Prov(), Writer()));

        Assert.Contains("no-such-faction", ex.Message, StringComparison.Ordinal);
        Assert.Contains("test-mfg/unmapped-faction", ex.Message, StringComparison.Ordinal);
    }
}
