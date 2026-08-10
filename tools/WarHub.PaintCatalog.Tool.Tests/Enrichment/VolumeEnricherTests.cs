using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class VolumeEnricherTests
{
    private static Paint MakePaint(string set) => new()
    {
        Name = "Test Paint",
        Set = set,
        R = 100,
        G = 100,
        B = 100,
        Hex = "#646464"
    };

    [Theory]
    [InlineData("Citadel Colour", "Base", 12, "pot")]
    [InlineData("Citadel Colour", "Layer", 12, "pot")]
    [InlineData("Citadel Colour", "Shade", 18, "pot")]
    [InlineData("Citadel Colour", "Contrast", 18, "pot")]
    [InlineData("Citadel Colour", "Technical", 24, "pot")]
    [InlineData("Citadel Colour", "Spray", 400, "spray")]
    [InlineData("Citadel Colour", "Dry", 12, "pot")]
    // 24, not 12: measured 926/926 `AIR: … (24ML)` rows across every committed trade
    // workbook, zero at 12. See the rule comment in VolumeTable.
    [InlineData("Citadel Colour", "Air", 24, "pot")]
    public void Enrich_Citadel_CorrectVolume(string brand, string set, int expectedVolume, string expectedPackaging)
    {
        Paint paint = MakePaint(set);

        Paint enriched = VolumeEnricher.Enrich(paint, brand);

        Assert.Equal(expectedVolume, enriched.VolumeMl);
        Assert.Equal(expectedPackaging, enriched.Packaging);
    }

    [Theory]
    [InlineData("Vallejo", "Model Color", 18, "dropper")]
    [InlineData("Vallejo", "Game Color", 18, "dropper")]
    [InlineData("Vallejo", "Model Air", 17, "dropper")]
    [InlineData("Vallejo", "Mecha Color", 17, "dropper")]
    [InlineData("Vallejo", "Metal Color", 32, "dropper")]
    [InlineData("Vallejo", "Xpress Color", 18, "dropper")]
    public void Enrich_Vallejo_CorrectVolume(string brand, string set, int expectedVolume, string expectedPackaging)
    {
        Paint paint = MakePaint(set);

        Paint enriched = VolumeEnricher.Enrich(paint, brand);

        Assert.Equal(expectedVolume, enriched.VolumeMl);
        Assert.Equal(expectedPackaging, enriched.Packaging);
    }

    // Green Stuff World's brand-wide rule is a 17 ml dropper, which was wrong for 79 records --
    // measured 2026-08-06 against each one's own barcode in the mfr-greenstuffworld evidence. 64 of
    // them are these five sets; the other 15 sit in mixed-volume sets and are asserted per record
    // in data/paints/overrides.yaml. See the rule comment in VolumeTable.
    [Theory]
    [InlineData("Flexible", 240, "dropper")]
    [InlineData("Dry Brush", 30, "dropper")]
    [InlineData("Spray Primer", 400, "spray")]
    [InlineData("Chameleon Spray", 400, "spray")]
    [InlineData("Chrome Spray", 400, "spray")]
    public void Enrich_GreenStuffWorld_SetSpecificRulesBeatTheBrandWideDefault(
        string set, int expectedVolume, string expectedPackaging)
    {
        // This is the ordering test as much as the value test. `Lookup` returns on the FIRST rule
        // matching the brand and the brand-wide rule has a null set list, which matches every set,
        // so a set-specific row placed BELOW it is unreachable and every assertion here comes back
        // 17/dropper. That failure looks exactly like the repair never happening.
        Paint enriched = VolumeEnricher.Enrich(MakePaint(set), "Green Stuff World");

        Assert.Equal(expectedVolume, enriched.VolumeMl);
        Assert.Equal(expectedPackaging, enriched.Packaging);
    }

    // The rules above must not widen the brand's default. `Dipping Inks` is the one that would
    // hurt: it holds 36 records at an evidenced 17 ml (including all 31 pots minted in c709958)
    // beside 33 at an evidenced 60, so any per-set constant for it is wrong for one group or the
    // other -- and the 33 are handled by overrides, which run last.
    [Theory]
    [InlineData("Dipping Inks")]
    [InlineData("Acrylic Colors")]
    [InlineData("Primer")]
    [InlineData("Varnish")]
    [InlineData("Blackest Black")]
    public void Enrich_GreenStuffWorld_UnlistedSetsStillGetTheBrandWideDefault(string set)
    {
        Paint enriched = VolumeEnricher.Enrich(MakePaint(set), "Green Stuff World");

        Assert.Equal(17, enriched.VolumeMl);
        Assert.Equal("dropper", enriched.Packaging);
    }

    [Fact]
    public void Enrich_ArmyPainter_18mlDropper()
    {
        Paint paint = MakePaint("Warpaints");

        Paint enriched = VolumeEnricher.Enrich(paint, "Army Painter");

        Assert.Equal(18, enriched.VolumeMl);
        Assert.Equal("dropper", enriched.Packaging);
    }

    [Fact]
    public void Enrich_Monument_22mlDropper()
    {
        Paint paint = MakePaint("Pro Acryl");

        Paint enriched = VolumeEnricher.Enrich(paint, "Monument (Pro Acryl)");

        Assert.Equal(22, enriched.VolumeMl);
        Assert.Equal("dropper", enriched.Packaging);
    }

    [Fact]
    public void Enrich_UnknownBrand_LeavesVolumeNull()
    {
        Paint paint = MakePaint("Unknown Set");

        Paint enriched = VolumeEnricher.Enrich(paint, "Unknown Brand");

        Assert.Null(enriched.VolumeMl);
        Assert.Null(enriched.Packaging);
    }

    [Fact]
    public void Enrich_DiscontinuedSet_StillGetsVolume()
    {
        Paint paint = MakePaint("Foundation (discontinued)");

        Paint enriched = VolumeEnricher.Enrich(paint, "Citadel Colour");

        // VolumeTable should handle stripping "(discontinued)" suffix
        Assert.NotNull(enriched.VolumeMl);
    }

    [Fact]
    public void Enrich_PreservesOtherFields()
    {
        Paint paint = new()
        {
            Name = "Test Paint",
            ProductCode = "70.950",
            Set = "Model Color",
            R = 100,
            G = 100,
            B = 100,
            Hex = "#646464",
            IsDiscontinued = true
        };

        Paint enriched = VolumeEnricher.Enrich(paint, "Vallejo");

        Assert.Equal("Test Paint", enriched.Name);
        Assert.Equal("70.950", enriched.ProductCode);
        Assert.Equal("Model Color", enriched.Set);
        Assert.Equal(100, enriched.R);
        Assert.True(enriched.IsDiscontinued);
    }
}
