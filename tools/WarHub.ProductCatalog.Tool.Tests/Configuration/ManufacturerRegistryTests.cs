using WarHub.ProductCatalog.Tool.Configuration;

namespace WarHub.ProductCatalog.Tool.Tests.Configuration;

public class ManufacturerRegistryTests
{
    [Fact]
    public void GetManufacturer_KnownManufacturer_ReturnsInfo()
    {
        ManufacturerInfo? info = ManufacturerRegistry.GetManufacturer("Games Workshop");

        Assert.NotNull(info);
        Assert.Equal("Games Workshop", info.Name);
        Assert.Equal("games-workshop", info.Slug);
    }

    [Fact]
    public void GetManufacturer_CaseInsensitive()
    {
        ManufacturerInfo? info = ManufacturerRegistry.GetManufacturer("games workshop");

        Assert.NotNull(info);
        Assert.Equal("Games Workshop", info.Name);
    }

    [Fact]
    public void GetManufacturer_UnknownManufacturer_ReturnsNull()
    {
        ManufacturerInfo? info = ManufacturerRegistry.GetManufacturer("Unknown Company");

        Assert.Null(info);
    }

    [Fact]
    public void GamesWorkshop_HasExpectedGameSystems()
    {
        ManufacturerInfo? gw = ManufacturerRegistry.GetManufacturer("Games Workshop");

        Assert.NotNull(gw);
        Assert.True(gw.GameSystems.ContainsKey("Warhammer 40,000"));
        Assert.True(gw.GameSystems.ContainsKey("Age of Sigmar"));
        Assert.True(gw.GameSystems.ContainsKey("Horus Heresy"));
        Assert.True(gw.GameSystems.ContainsKey("Middle-earth"));
    }

    [Fact]
    public void Warhammer40k_HasExpectedFactions()
    {
        ManufacturerInfo? gw = ManufacturerRegistry.GetManufacturer("Games Workshop");
        Assert.NotNull(gw);

        GameSystemInfo gs = gw.GameSystems["Warhammer 40,000"];
        Assert.Contains("Space Marines", gs.Factions);
        Assert.Contains("Necrons", gs.Factions);
        Assert.Contains("Orks", gs.Factions);
        Assert.Contains("Tyranids", gs.Factions);
        Assert.Contains("Aeldari", gs.Factions);
    }

    [Fact]
    public void WarlordGames_HasExpandedGameSystems()
    {
        ManufacturerInfo? wg = ManufacturerRegistry.GetManufacturer("Warlord Games");

        Assert.NotNull(wg);
        Assert.True(wg.GameSystems.ContainsKey("Bolt Action"));
        Assert.True(wg.GameSystems.ContainsKey("Black Powder"));
        Assert.True(wg.GameSystems.ContainsKey("Hail Caesar"));
        Assert.True(wg.GameSystems.ContainsKey("Pike & Shotte"));
        Assert.True(wg.GameSystems.ContainsKey("Victory at Sea"));
        Assert.True(wg.GameSystems.ContainsKey("Blood Red Skies"));
        Assert.True(wg.GameSystems.ContainsKey("Konflikt '47"));
        Assert.True(wg.GameSystems.ContainsKey("Beyond the Gates of Antares"));
        Assert.True(wg.GameSystems.ContainsKey("Black Seas"));
        Assert.True(wg.GameSystems.Count >= 17);
    }

    [Fact]
    public void CorvusBelli_HasExpandedGameSystems()
    {
        ManufacturerInfo? cb = ManufacturerRegistry.GetManufacturer("Corvus Belli");

        Assert.NotNull(cb);
        Assert.True(cb.GameSystems.ContainsKey("Infinity"));
        Assert.True(cb.GameSystems.ContainsKey("Warcrow"));
        Assert.True(cb.GameSystems.ContainsKey("Aristeia!"));
    }

    [Fact]
    public void WyrdGames_HasExpandedGameSystems()
    {
        ManufacturerInfo? wyrd = ManufacturerRegistry.GetManufacturer("Wyrd Games");

        Assert.NotNull(wyrd);
        Assert.True(wyrd.GameSystems.ContainsKey("Malifaux"));
        Assert.True(wyrd.GameSystems.ContainsKey("The Other Side"));
        Assert.Equal(5, wyrd.GameSystems["The Other Side"].Factions.Count);
    }

    [Fact]
    public void ManticGames_HasExpandedGameSystems()
    {
        ManufacturerInfo? mantic = ManufacturerRegistry.GetManufacturer("Mantic Games");

        Assert.NotNull(mantic);
        Assert.True(mantic.GameSystems.ContainsKey("Kings of War"));
        Assert.True(mantic.GameSystems.ContainsKey("Deadzone"));
        Assert.True(mantic.GameSystems.ContainsKey("Firefight"));
        Assert.True(mantic.GameSystems.ContainsKey("Armada"));
        Assert.True(mantic.GameSystems.ContainsKey("Halo: Flashpoint"));
        Assert.True(mantic.GameSystems.ContainsKey("The Walking Dead: All Out War"));
    }

    [Fact]
    public void AtomicMassGames_HasExpandedGameSystems()
    {
        ManufacturerInfo? amg = ManufacturerRegistry.GetManufacturer("Atomic Mass Games");

        Assert.NotNull(amg);
        Assert.True(amg.GameSystems.ContainsKey("Marvel Crisis Protocol"));
        Assert.True(amg.GameSystems.ContainsKey("Star Wars Legion"));
        Assert.True(amg.GameSystems.ContainsKey("Star Wars Shatterpoint"));
        Assert.True(amg.GameSystems.ContainsKey("Star Wars X-Wing"));
        Assert.True(amg.GameSystems.ContainsKey("Star Wars Armada"));
    }

    [Fact]
    public void SteamforgedGames_HasExpandedGameSystems()
    {
        ManufacturerInfo? sf = ManufacturerRegistry.GetManufacturer("Steamforged Games");

        Assert.NotNull(sf);
        Assert.True(sf.GameSystems.ContainsKey("Warmachine"));
        Assert.True(sf.GameSystems.ContainsKey("Guild Ball"));
        Assert.True(sf.GameSystems.ContainsKey("Godtear"));
        Assert.True(sf.GameSystems.ContainsKey("Epic Encounters"));
    }

    [Theory]
    [InlineData("Hello World", "hello-world")]
    [InlineData("Warhammer 40,000", "warhammer-40000")]
    [InlineData("Age of Sigmar", "age-of-sigmar")]
    [InlineData("T'au Empire", "tau-empire")]
    [InlineData("  Spaces  ", "spaces")]
    public void Slugify_ProducesExpectedResults(string input, string expected)
    {
        string result = ManufacturerRegistry.Slugify(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("combat_patrol", "combat_patrol")]
    [InlineData("Combat Patrol", "combat_patrol")]
    [InlineData("BOX_SET", "box_set")]
    [InlineData(null, "unknown")]
    [InlineData("", "unknown")]
    [InlineData("something_random", "unknown")]
    public void NormalizeProductType_HandlesVariousInputs(string? input, string expected)
    {
        string result = ManufacturerRegistry.NormalizeProductType(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    // in_stock
    [InlineData("current", "in_stock")]
    [InlineData("available", "in_stock")]
    [InlineData("in stock", "in_stock")]
    // pre_order
    [InlineData("pre-order", "pre_order")]
    [InlineData("preorder", "pre_order")]
    [InlineData("pre order", "pre_order")]
    // limited
    [InlineData("limited", "limited")]
    [InlineData("limited edition", "limited")]
    [InlineData("made to order", "limited")]
    // out_of_stock
    [InlineData("out of stock", "out_of_stock")]
    [InlineData("temporarily out of stock", "out_of_stock")]
    [InlineData("discontinued", "out_of_stock")]
    [InlineData("no longer available", "out_of_stock")]
    // unknown / default
    [InlineData(null, "unknown")]
    [InlineData("", "unknown")]
    [InlineData("   ", "unknown")]
    [InlineData("something else entirely", "unknown")]
    // case/whitespace normalization
    [InlineData("  In Stock ", "in_stock")]
    [InlineData("DISCONTINUED", "out_of_stock")]
    public void NormalizeAvailability_HandlesEveryBranch(string? input, string expected)
    {
        string result = ManufacturerRegistry.NormalizeAvailability(input);
        Assert.Equal(expected, result);
    }
}
