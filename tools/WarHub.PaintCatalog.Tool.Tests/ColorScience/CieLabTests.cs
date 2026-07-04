using WarHub.PaintCatalog.Tool.ColorScience;

namespace WarHub.PaintCatalog.Tool.Tests.ColorScience;

public class CieLabTests
{
    [Fact]
    public void FromRgb_Black_ReturnsZeroLightness()
    {
        var (l, a, b) = CieLab.FromRgb(0, 0, 0);

        Assert.Equal(0, l, 1);
        Assert.Equal(0, a, 1);
        Assert.Equal(0, b, 1);
    }

    [Fact]
    public void FromRgb_White_ReturnsMaxLightness()
    {
        var (l, a, b) = CieLab.FromRgb(255, 255, 255);

        Assert.Equal(100, l, 0.5);
        // a* and b* should be near zero for white
        Assert.InRange(a, -1, 1);
        Assert.InRange(b, -1, 1);
    }

    [Fact]
    public void FromRgb_PureRed_HasPositiveA()
    {
        var (l, a, b) = CieLab.FromRgb(255, 0, 0);

        // Red should have high positive a* (red-green axis)
        Assert.True(a > 50, $"Expected a* > 50 for pure red, got {a}");
        Assert.True(l > 40, $"Expected L* > 40 for pure red, got {l}");
    }

    [Fact]
    public void FromRgb_PureGreen_HasNegativeA()
    {
        var (l, a, b) = CieLab.FromRgb(0, 255, 0);

        // Green should have negative a* (red-green axis)
        Assert.True(a < -50, $"Expected a* < -50 for pure green, got {a}");
    }

    [Fact]
    public void FromRgb_PureBlue_HasNegativeB()
    {
        var (l, a, b) = CieLab.FromRgb(0, 0, 255);

        // Blue should have large negative b* (blue-yellow axis)
        Assert.True(b < -50, $"Expected b* < -50 for pure blue, got {b}");
    }

    [Fact]
    public void FromRgb_PureYellow_HasPositiveB()
    {
        var (l, a, b) = CieLab.FromRgb(255, 255, 0);

        // Yellow should have large positive b*
        Assert.True(b > 70, $"Expected b* > 70 for pure yellow, got {b}");
    }

    [Fact]
    public void FromRgb_MidGrey_HasZeroChroma()
    {
        var (l, a, b) = CieLab.FromRgb(128, 128, 128);

        // Grey should have near-zero a* and b*
        Assert.InRange(a, -1, 1);
        Assert.InRange(b, -1, 1);
        // L* should be around 53 for 50% grey
        Assert.InRange(l, 50, 56);
    }

    [Fact]
    public void FromRgb_KnownConversion_MatchesExpected()
    {
        // sRGB (154, 14, 5) = Mephiston Red
        // Expected CIELAB approximately: L*≈32, a*≈42-48, b*≈32-40
        var (l, a, b) = CieLab.FromRgb(154, 14, 5);

        Assert.InRange(l, 28, 36);
        Assert.InRange(a, 38, 56);
        Assert.InRange(b, 28, 46);
    }

    [Fact]
    public void FromRgb_Symmetric_SameColorSameResult()
    {
        var result1 = CieLab.FromRgb(100, 150, 200);
        var result2 = CieLab.FromRgb(100, 150, 200);

        Assert.Equal(result1.L, result2.L);
        Assert.Equal(result1.A, result2.A);
        Assert.Equal(result1.B, result2.B);
    }
}
