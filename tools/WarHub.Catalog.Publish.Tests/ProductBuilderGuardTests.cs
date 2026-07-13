using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// ProductBuilder must fail loudly (not silently drop or default) when a canonical product
/// references taxonomy that isn't there -- these are data-integrity bugs (a bad slug, a
/// resolver defect that let a gameSystem-less product through) that should stop the build,
/// not produce a quietly wrong catalog.
/// </summary>
public sealed class ProductBuilderGuardTests
{
    private static readonly TaxonomyLabels EmptyLabels = new(
        new Dictionary<string, string>(), new Dictionary<string, string>());

    private static CatalogWriter Writer()
    {
        string schemaDir = Path.Combine(AppContext.BaseDirectory, "schema");
        string dist = Path.Combine(Path.GetTempPath(), "warhub-catalog-guard-tests", Guid.NewGuid().ToString("N"));
        return new CatalogWriter(dist, SchemaValidator.LoadFrom(schemaDir));
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
    public void Null_game_system_throws_naming_the_product_id()
    {
        var product = new CanonicalProduct
        {
            Id = "test-mfg/no-game-system",
            Name = "Mystery Box",
            Manufacturer = "test-mfg",
            Status = "current",
            GameSystem = null,
        };

        var ex = Assert.Throws<InvalidOperationException>(
            () => ProductBuilder.Build([CatalogOf(product)], EmptyLabels, Prov(), Writer()));

        Assert.Contains("test-mfg/no-game-system", ex.Message, StringComparison.Ordinal);
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
