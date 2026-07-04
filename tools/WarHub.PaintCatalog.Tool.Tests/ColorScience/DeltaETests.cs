using WarHub.PaintCatalog.Tool.ColorScience;

namespace WarHub.PaintCatalog.Tool.Tests.ColorScience;

public class DeltaETests
{
    [Fact]
    public void Ciede2000_IdenticalColors_ReturnsZero()
    {
        var lab = CieLab.FromRgb(154, 14, 5);
        double dE = DeltaE.Ciede2000(lab, lab);

        Assert.Equal(0, dE, 5);
    }

    [Fact]
    public void Ciede2000_BlackVsWhite_LargeDifference()
    {
        double dE = DeltaE.FromRgb(0, 0, 0, 255, 255, 255);

        // Black vs white should be ~100
        Assert.True(dE > 90, $"Expected Delta E > 90 for black vs white, got {dE}");
    }

    [Fact]
    public void Ciede2000_SimilarColors_SmallDifference()
    {
        // Two similar reds
        double dE = DeltaE.FromRgb(200, 50, 50, 210, 45, 55);

        Assert.True(dE < 5, $"Expected Delta E < 5 for similar reds, got {dE}");
    }

    [Fact]
    public void Ciede2000_VeryDifferentColors_LargeDifference()
    {
        // Red vs Blue
        double dE = DeltaE.FromRgb(255, 0, 0, 0, 0, 255);

        Assert.True(dE > 50, $"Expected Delta E > 50 for red vs blue, got {dE}");
    }

    [Fact]
    public void Ciede2000_Symmetric()
    {
        var lab1 = CieLab.FromRgb(154, 14, 5);   // Mephiston Red
        var lab2 = CieLab.FromRgb(129, 4, 4);     // Gory Red

        double dE12 = DeltaE.Ciede2000(lab1, lab2);
        double dE21 = DeltaE.Ciede2000(lab2, lab1);

        Assert.Equal(dE12, dE21, 10);
    }

    // Known equivalences from redgrimm/paint-conversion
    // Format: Citadel paint → Vallejo equivalent (Delta E from redgrimm)

    [Theory]
    [InlineData(255, 255, 255, 255, 255, 255, 0.0)]       // White → White (exact)
    [InlineData(255, 255, 255, 254, 251, 253, 1.84)]      // Ceramite White → Morrow White (≈1.84)
    public void Ciede2000_KnownRedgrimmPairs_WithinTolerance(
        int r1, int g1, int b1,
        int r2, int g2, int b2,
        double expectedDeltaE)
    {
        double actualDeltaE = DeltaE.FromRgb(r1, g1, b1, r2, g2, b2);

        // Allow tolerance of ±2 since hex→RGB→Lab conversions introduce small differences
        Assert.InRange(actualDeltaE, Math.Max(0, expectedDeltaE - 2), expectedDeltaE + 2);
    }

    [Fact]
    public void Ciede2000_MephistonRedVsDragonRed_CloseMatch()
    {
        // Citadel Mephiston Red (#9B0E05) vs Army Painter Dragon Red (#9A1B1E)
        // redgrimm reports Delta E ≈ 4.47
        double dE = DeltaE.FromRgb(0x9B, 0x0E, 0x05, 0x9A, 0x1B, 0x1E);

        // Should be a close match (< 10)
        Assert.True(dE < 10, $"Expected Delta E < 10, got {dE}");
        // Should be in the ballpark of redgrimm's value
        Assert.InRange(dE, 2, 8);
    }

    [Fact]
    public void Ciede2000_AverlandSunsetVsGoldYellow_CloseMatch()
    {
        // Citadel Averland Sunset (#FBBA00) vs Vallejo Game Gold Yellow (#FDB318)
        // redgrimm reports Delta E ≈ 2.85
        double dE = DeltaE.FromRgb(0xFB, 0xBA, 0x00, 0xFD, 0xB3, 0x18);

        Assert.True(dE < 6, $"Expected Delta E < 6, got {dE}");
    }

    [Fact]
    public void FromRgb_ConvenienceMethod_MatchesTwoStepComputation()
    {
        double directResult = DeltaE.FromRgb(100, 150, 200, 110, 140, 210);

        var lab1 = CieLab.FromRgb(100, 150, 200);
        var lab2 = CieLab.FromRgb(110, 140, 210);
        double twoStepResult = DeltaE.Ciede2000(lab1, lab2);

        Assert.Equal(directResult, twoStepResult, 10);
    }

    [Fact]
    public void Ciede2000_NeutralGreys_OnlyLightnessDifference()
    {
        // Two greys differ only in lightness, not hue/chroma
        double dE = DeltaE.FromRgb(128, 128, 128, 160, 160, 160);

        // Should be a moderate difference (lightness only)
        Assert.True(dE > 0, "Expected non-zero Delta E for different greys");
        Assert.True(dE < 15, $"Expected Delta E < 15 for similar greys, got {dE}");
    }
}
