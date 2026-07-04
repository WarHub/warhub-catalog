using WarHub.ProductCatalog.Tool.Enrichment;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class OverrideApplierTests
{
    [Fact]
    public void Apply_NoOverridesPath_ReturnsOriginal()
    {
        var products = CreateTestProducts();

        IReadOnlyList<Product> result = OverrideApplier.Apply(products, "games-workshop", "warhammer-40k", null);

        Assert.Same(products, result);
    }

    [Fact]
    public void Apply_NonExistentFile_ReturnsOriginal()
    {
        var products = CreateTestProducts();

        IReadOnlyList<Product> result = OverrideApplier.Apply(products, "games-workshop", "warhammer-40k", "/nonexistent/overrides.yaml");

        Assert.Same(products, result);
    }

    [Fact]
    public void Apply_EmptyOverrides_ReturnsOriginal()
    {
        var products = CreateTestProducts();
        string tempFile = CreateTempOverrides("{}");

        try
        {
            IReadOnlyList<Product> result = OverrideApplier.Apply(products, "games-workshop", "warhammer-40k", tempFile);

            Assert.Equal(products.Count, result.Count);
            Assert.Equal(products[0].Name, result[0].Name);
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    [Fact]
    public void Apply_MatchingOverride_AppliesChanges()
    {
        var products = CreateTestProducts();
        string tempFile = CreateTempOverrides("""
            games-workshop/warhammer-40k:
              Intercessors:
                sku: OVERRIDE-SKU
                ean: "1234567890123"
            """);

        try
        {
            IReadOnlyList<Product> result = OverrideApplier.Apply(products, "games-workshop", "warhammer-40k", tempFile);

            Assert.Equal("OVERRIDE-SKU", result[0].Sku);
            Assert.Equal("1234567890123", result[0].Ean);
            // Non-overridden fields preserved
            Assert.Equal("Intercessors", result[0].Name);
            Assert.Equal(35.00m, result[0].PriceGbp);
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    [Fact]
    public void Apply_DifferentSection_DoesNotApply()
    {
        var products = CreateTestProducts();
        string tempFile = CreateTempOverrides("""
            corvus-belli/infinity:
              Intercessors:
                sku: SHOULD-NOT-APPLY
            """);

        try
        {
            IReadOnlyList<Product> result = OverrideApplier.Apply(products, "games-workshop", "warhammer-40k", tempFile);

            Assert.Null(result[0].Sku);
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    [Fact]
    public void Apply_InvalidYaml_ReturnsOriginal()
    {
        var products = CreateTestProducts();
        string tempFile = CreateTempOverrides("not: valid: yaml: {{{");

        try
        {
            IReadOnlyList<Product> result = OverrideApplier.Apply(products, "games-workshop", "warhammer-40k", tempFile);

            Assert.Equal(products.Count, result.Count);
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    private static IReadOnlyList<Product> CreateTestProducts()
    {
        return
        [
            new Product
            {
                Name = "Intercessors",
                ProductType = "single_kit",
                PriceGbp = 35.00m,
                Status = "current",
            },
            new Product
            {
                Name = "Necron Warriors",
                ProductType = "single_kit",
                PriceGbp = 29.00m,
                Status = "current",
            },
        ];
    }

    private static string CreateTempOverrides(string yaml)
    {
        string path = Path.GetTempFileName();
        File.WriteAllText(path, yaml);
        return path;
    }
}
