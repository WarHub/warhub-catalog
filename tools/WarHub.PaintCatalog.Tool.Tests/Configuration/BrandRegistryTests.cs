using WarHub.PaintCatalog.Tool.Configuration;

namespace WarHub.PaintCatalog.Tool.Tests.Configuration;

public class BrandRegistryTests
{
    [Theory]
    [InlineData("Vallejo.md")]
    [InlineData("Citadel_Colour.md")]
    [InlineData("Army_Painter.md")]
    [InlineData("AK.md")]
    [InlineData("Scale75.md")]
    [InlineData("Monument.md")]
    [InlineData("KimeraKolors.md")]
    [InlineData("TurboDork.md")]
    [InlineData("Reaper.md")]
    [InlineData("Tamiya.md")]
    [InlineData("Mig.md")]
    public void IsMiniatureBrand_KnownBrand_ReturnsTrue(string fileName)
    {
        Assert.True(BrandRegistry.IsMiniatureBrand(fileName));
    }

    [Theory]
    [InlineData("Pantone.md")]
    [InlineData("RAL.md")]
    [InlineData("Golden.md")]
    [InlineData("Liquitex.md")]
    [InlineData("FolkArt.md")]
    public void IsMiniatureBrand_CraftBrand_ReturnsFalse(string fileName)
    {
        Assert.False(BrandRegistry.IsMiniatureBrand(fileName));
    }

    [Fact]
    public void GetByFileName_Vallejo_ReturnsCorrectInfo()
    {
        BrandInfo? info = BrandRegistry.GetByFileName("Vallejo.md");

        Assert.NotNull(info);
        Assert.Equal("Vallejo", info.DisplayName);
        Assert.Equal("vallejo", info.Slug);
    }

    [Fact]
    public void GetByFileName_CitadelColour_ReturnsCorrectInfo()
    {
        BrandInfo? info = BrandRegistry.GetByFileName("Citadel_Colour.md");

        Assert.NotNull(info);
        Assert.Equal("Citadel Colour", info.DisplayName);
        Assert.Equal("citadel-colour", info.Slug);
    }

    [Fact]
    public void GetByFileName_Mig_ReturnsCorrectInfo()
    {
        BrandInfo? info = BrandRegistry.GetByFileName("Mig.md");

        Assert.NotNull(info);
        Assert.Equal("AMMO by Mig Jimenez", info.DisplayName);
        Assert.Equal("ammo-mig", info.Slug);
    }

    [Fact]
    public void GetByFileName_UnknownBrand_ReturnsNull()
    {
        BrandInfo? info = BrandRegistry.GetByFileName("UnknownBrand.md");

        Assert.Null(info);
    }

    [Fact]
    public void IsExcluded_CraftBrand_ReturnsTrue()
    {
        Assert.True(BrandRegistry.IsExcluded("Pantone.md"));
        Assert.True(BrandRegistry.IsExcluded("RAL.md"));
    }

    [Fact]
    public void IsExcluded_MiniatureBrand_ReturnsFalse()
    {
        Assert.False(BrandRegistry.IsExcluded("Vallejo.md"));
        Assert.False(BrandRegistry.IsExcluded("Mig.md"));
    }

    [Fact]
    public void AllBrands_HasExpectedCount()
    {
        // We expect at least 15 miniature brands
        IReadOnlyList<BrandInfo> brands = BrandRegistry.AllBrands;
        Assert.True(brands.Count >= 15, $"Expected at least 15 brands, got {brands.Count}");
    }

    [Fact]
    public void AllBrands_SlugsAreUnique()
    {
        IReadOnlyList<BrandInfo> brands = BrandRegistry.AllBrands;
        var slugs = brands.Select(b => b.Slug).ToList();
        Assert.Equal(slugs.Count, slugs.Distinct().Count());
    }
}
