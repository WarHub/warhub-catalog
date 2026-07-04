using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class OverrideApplierTests
{
    private static readonly IReadOnlyList<Paint> SamplePaints =
    [
        new Paint
        {
            Name = "Mephiston Red",
            Set = "Base",
            R = 154, G = 14, B = 5,
            Hex = "#9A0E05"
        },
        new Paint
        {
            Name = "Abaddon Black",
            Set = "Base",
            R = 0, G = 0, B = 0,
            Hex = "#000000"
        }
    ];

    [Fact]
    public void Apply_NoOverridesFile_ReturnsOriginal()
    {
        IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", null);

        Assert.Equal(SamplePaints.Count, result.Count);
        Assert.Equal(SamplePaints[0].Name, result[0].Name);
    }

    [Fact]
    public void Apply_NonExistentFile_ReturnsOriginal()
    {
        IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", "/nonexistent/path.yaml");

        Assert.Equal(SamplePaints.Count, result.Count);
    }

    [Fact]
    public void Apply_OverridesProductCode_Applies()
    {
        string overridesYaml = """
            citadel-colour:
              "Mephiston Red|Base":
                productCode: "99189950005"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("99189950005", result[0].ProductCode);
            Assert.Null(result[1].ProductCode); // Abaddon Black not overridden
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Apply_OverridesHex_Applies()
    {
        string overridesYaml = """
            citadel-colour:
              "Mephiston Red|Base":
                hex: "#AA1100"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("#AA1100", result[0].Hex);
            // RGB must be recomputed to stay in sync with the overridden hex
            Assert.Equal(0xAA, result[0].R);
            Assert.Equal(0x11, result[0].G);
            Assert.Equal(0x00, result[0].B);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Apply_OverridesEan_Applies()
    {
        string overridesYaml = """
            citadel-colour:
              "Mephiston Red|Base":
                ean: "5011921153770"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("5011921153770", result[0].Ean);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Apply_DifferentBrand_DoesNotAffect()
    {
        string overridesYaml = """
            vallejo:
              "Black|Model Color":
                ean: "8429551709507"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            // No overrides for citadel-colour, so no changes
            Assert.Null(result[0].Ean);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Apply_EmptyOverrides_ReturnsOriginal()
    {
        string overridesYaml = "{}";
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal(SamplePaints.Count, result.Count);
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static string WriteTempOverrides(string yaml)
    {
        string path = Path.GetTempFileName();
        File.WriteAllText(path, yaml);
        return path;
    }
}
