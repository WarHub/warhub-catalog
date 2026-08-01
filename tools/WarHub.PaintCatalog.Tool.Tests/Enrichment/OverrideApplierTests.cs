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

    [Fact]
    public void Override_can_retire_a_paint_the_source_still_lists()
    {
        // Discontinuation is an ABSENCE -- the upstream source just stops listing a paint and the
        // manufacturer bridge is built from trade rows that no longer contain it -- so nothing in
        // the pipeline can assert it. A researched decision recorded here is the only route.
        string path = WriteTempOverrides("citadel-colour:\n  Mephiston Red|Base:\n    isDiscontinued: true\n");

        IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

        Assert.True(result.Single(p => p.Name == "Mephiston Red").IsDiscontinued);
        Assert.False(result.Single(p => p.Name == "Abaddon Black").IsDiscontinued);
    }

    [Fact]
    public void Override_can_also_contradict_a_retirement_the_source_asserted()
    {
        // Authoritative both ways. `bool?` distinguishes an absent key from an explicit `false`,
        // so writing `false` is a deliberate claim that the source is wrong -- the same contract
        // every other overridable field has.
        IReadOnlyList<Paint> retired = [SamplePaints[0] with { IsDiscontinued = true }];
        string path = WriteTempOverrides("citadel-colour:\n  Mephiston Red|Base:\n    isDiscontinued: false\n");

        Assert.False(OverrideApplier.Apply(retired, "citadel-colour", path).Single().IsDiscontinued);
    }
}
