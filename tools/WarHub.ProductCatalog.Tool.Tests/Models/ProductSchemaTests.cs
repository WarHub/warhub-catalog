using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Tests.Models;

public class ProductSchemaTests
{
    [Fact]
    public void Product_HasCategoryPackagingAndFirstSeen()
    {
        var p = new Product
        {
            Name = "Test",
            Category = "miniatures",
            Packaging = "single",
            Status = "current",
            FirstSeen = "2026-07-07",
        };

        Assert.Equal("miniatures", p.Category);
        Assert.Equal("single", p.Packaging);
        Assert.Equal("2026-07-07", p.FirstSeen);
    }

    [Fact]
    public void FactionCatalog_HasNoProductCountProperty()
    {
        Assert.Null(typeof(FactionCatalog).GetProperty("ProductCount"));
    }

    [Fact]
    public void Product_HasNoProductTypeProperty()
    {
        Assert.Null(typeof(Product).GetProperty("ProductType"));
    }
}
