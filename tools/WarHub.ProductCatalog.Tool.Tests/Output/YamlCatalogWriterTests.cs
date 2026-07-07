using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;

namespace WarHub.ProductCatalog.Tool.Tests.Output;

public class YamlCatalogWriterTests
{
    private static FactionCatalog Catalog(params Product[] products) => new()
    {
        Manufacturer = "CMON", ManufacturerSlug = "cmon",
        GameSystem = "ASOIAF", GameSystemSlug = "asoiaf",
        Faction = "Baratheon", FactionSlug = "baratheon",
        Products = products.ToList(),
    };

    private static Product P(string name, string? ean) => new()
    {
        Name = name, Category = "miniatures", Packaging = "single",
        Status = "current", Availability = "in_stock", FirstSeen = "2026-07-07", Ean = ean,
    };

    [Fact]
    public async Task Write_QuotesEanAndOmitsProductCount()
    {
        string dir = Path.Combine(Path.GetTempPath(), $"cat-{Guid.NewGuid():N}");
        try
        {
            await YamlCatalogWriter.WriteFactionAsync(Catalog(P("Wardens", "0889696010223")), dir);
            string file = Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml");
            string yaml = await File.ReadAllTextAsync(file);

            Assert.Contains("ean: '0889696010223'", yaml);
            Assert.DoesNotContain("productCount", yaml);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task Write_IsByteIdenticalForSameInput()
    {
        string dir = Path.Combine(Path.GetTempPath(), $"cat-{Guid.NewGuid():N}");
        try
        {
            FactionCatalog c = Catalog(P("Wardens", "1"), P("Halberdiers", "2"));
            await YamlCatalogWriter.WriteFactionAsync(c, dir);
            string file = Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml");
            string first = await File.ReadAllTextAsync(file);

            await YamlCatalogWriter.WriteFactionAsync(c, dir);
            string second = await File.ReadAllTextAsync(file);

            Assert.Equal(first, second);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }
}
