using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class SwatchApplierTests
{
    private static readonly IReadOnlyList<Paint> SamplePaints =
    [
        // Two same-name TMM variants, both colour-less (the case the 3-part key exists for).
        new Paint { Name = "Sterling Silver", Set = "True Metallic Metal", ProductCode = "77.101", R = 0, G = 0, B = 0, Hex = "" },
        new Paint { Name = "Sterling Silver", Set = "True Metallic Metal", ProductCode = "77.141", R = 0, G = 0, B = 0, Hex = "" },
        // Already has a colour: must never be touched.
        new Paint { Name = "Dead White", Set = "Game Color", ProductCode = "72.001", R = 255, G = 255, B = 255, Hex = "#FFFFFF" },
    ];

    private static string WriteSwatchDir(string yaml)
    {
        string dir = Path.Combine(Path.GetTempPath(), $"swatches-{Guid.NewGuid():N}");
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "vallejo.yaml"), yaml);
        return dir;
    }

    [Fact]
    public void Apply_FillsEmptyHexPerCodedVariant_AndRecomputesRgb()
    {
        string dir = WriteSwatchDir("""
            vallejo:
              "Sterling Silver|True Metallic Metal|77.101":
                hex: "#8A8D91"
                code: "77.101"
                method: pdf-chart
                confidence: medium
              "Sterling Silver|True Metallic Metal|77.141":
                hex: "#3D3D3E"
                code: "77.141"
                method: pdf-chart
                confidence: medium
              "Dead White|Game Color|72.001":
                hex: "#EEEEEE"
                code: "72.001"
            """);
        try
        {
            var swatches = SwatchApplier.Load(dir);
            IReadOnlyList<Paint> result = SwatchApplier.Apply(SamplePaints, "vallejo", swatches);

            Paint baseVariant = result.Single(p => p.ProductCode == "77.101");
            Assert.Equal("#8A8D91", baseVariant.Hex);
            Assert.Equal((138, 141, 145), (baseVariant.R, baseVariant.G, baseVariant.B));

            Paint darkVariant = result.Single(p => p.ProductCode == "77.141");
            Assert.Equal("#3D3D3E", darkVariant.Hex); // each variant got ITS chart colour

            Paint deadWhite = result.Single(p => p.Name == "Dead White");
            Assert.Equal("#FFFFFF", deadWhite.Hex); // non-empty hex untouched
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public void Apply_NoBrandEntries_ReturnsOriginal()
    {
        Assert.Same(
            SamplePaints,
            SwatchApplier.Apply(
                SamplePaints, "vallejo",
                new Dictionary<string, IReadOnlyDictionary<string, SwatchApplier.SwatchEntry>>()));
    }

    [Fact]
    public void Load_MalformedFile_IsSkippedNotFatal()
    {
        string dir = WriteSwatchDir(": not [ yaml");
        try
        {
            Assert.Empty(SwatchApplier.Load(dir));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Theory]
    [InlineData("#8A8D91", true, 138, 141, 145)]
    [InlineData("8A8D91", true, 138, 141, 145)]
    [InlineData("", false, 0, 0, 0)]
    [InlineData("#FFF", false, 0, 0, 0)]
    [InlineData("#GGGGGG", false, 0, 0, 0)]
    public void TryParseHex_Cases(string hex, bool ok, int r, int g, int b)
    {
        Assert.Equal(ok, SwatchApplier.TryParseHex(hex, out int pr, out int pg, out int pb));
        if (ok)
            Assert.Equal((r, g, b), (pr, pg, pb));
    }
}
