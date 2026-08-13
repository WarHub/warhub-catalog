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
    public void Apply_OverridesName_MovesTheIdentityBeforeReconciliation()
    {
        // The point of the field: a base-sourced record whose UPSTREAM NAME is misspelled could
        // not be corrected at all before this. `aliases:` alone cannot do it -- the base
        // re-asserts the misspelling every run, CatalogReconciler seeds `consumed` with it, and
        // the alias is refused (CatalogReconciler.cs:38-46, :83-86), so the run mints a duplicate.
        // Rewriting the name HERE vacates the old key, exactly as the productCode correction
        // above does, and the paired alias then stitches the rename to its existing record.
        string overridesYaml = """
            citadel-colour:
              "Mephiston Red|Base":
                name: "Mephiston Scarlet"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("Mephiston Scarlet", result[0].Name);
            Assert.Equal("Base", result[0].Set);          // untouched
            Assert.Equal("#9A0E05", result[0].Hex);       // the rename carries the colour
            Assert.Equal("Abaddon Black", result[1].Name);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Apply_OverridesSet_Applies()
    {
        string overridesYaml = """
            citadel-colour:
              "Mephiston Red|Base":
                set: "Base (2012)"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("Base (2012)", result[0].Set);
            Assert.Equal("Mephiston Red", result[0].Name);
            Assert.Equal("Base", result[1].Set);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Apply_KeyedOnTheNameTheBaseEmits_NotTheCorrectedOne()
    {
        // The trap this pins: the lookup key is `{Name}|{Set}` as the base supplies it, so a
        // renaming block MUST keep the misspelling as its own key. Tidying the key to the
        // corrected name makes the block match nothing -- a silent no-op that reads like a
        // completed correction.
        string overridesYaml = """
            citadel-colour:
              "Mephiston Scarlet|Base":
                name: "Mephiston Scarlet"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("Mephiston Red", result[0].Name);
        }
        finally
        {
            File.Delete(path);
        }
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

    /// <summary>
    /// `colourless: true` is an assertion with a CONSEQUENCE, and the consequence is the whole
    /// point: a varnish that keeps its #FFFFFF stand-in is still a node in the equivalence graph
    /// no matter what the flag says. That is what published a clear brush-on sealer as a deltaE 0
    /// match for five white paints across 310 rows. So the clearing is the behaviour under test,
    /// not the flag.
    ///
    /// Nothing else covers it. The two test edits that came with the field are both mechanical --
    /// a positional record ctor the compiler forced, and a name added to an ordered property list
    /// -- so reverting these four lines to `Hex = newHex, R = newR, ...` left the entire C# suite
    /// green, and the regression would not surface until the next regeneration quietly returned 94
    /// stand-in greys.
    /// </summary>
    [Fact]
    public void Apply_Colourless_ClearsTheColourAndOutranksAnExplicitHex()
    {
        string overridesYaml = """
            citadel-colour:
              "Mephiston Red|Base":
                colourless: true
              "Abaddon Black|Base":
                colourless: true
                hex: "#AA1100"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.True(result[0].Colourless);
            Assert.Equal("", result[0].Hex);
            Assert.Equal(0, result[0].R);
            Assert.Equal(0, result[0].G);
            Assert.Equal(0, result[0].B);

            // A `hex:` in the same block is a contradiction, and colourless wins it. Stated in the
            // applier's own comment; pinned here so the precedence cannot drift silently.
            Assert.True(result[1].Colourless);
            Assert.Equal("", result[1].Hex);
            Assert.Equal(0, result[1].R);
        }
        finally
        {
            File.Delete(path);
        }
    }

    /// <summary>
    /// The other half: an ordinary paint keeps its colour, and `Colourless` stays null rather than
    /// becoming a written `false`. Null means unstated -- nothing in the pipeline writes false --
    /// and an over-eager `Colourless = over.Colourless ?? false` would blank nothing but would
    /// publish the flag on all 8,354 records.
    /// </summary>
    [Fact]
    public void Apply_WithoutColourless_LeavesTheColourAndTheFlagAlone()
    {
        string overridesYaml = """
            citadel-colour:
              "Mephiston Red|Base":
                productCode: "22-02"
            """;
        string path = WriteTempOverrides(overridesYaml);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Null(result[0].Colourless);
            Assert.Equal("#9A0E05", result[0].Hex);
            Assert.Equal(154, result[0].R);
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

    [Fact]
    public void Apply_OverridesPrices_Applies()
    {
        string path = WriteTempOverrides("""
            citadel-colour:
              "Mephiston Red|Base":
                priceGbp: 3.10
                priceUsd: 5.20
                priceEur: 4.05
                priceCad: 6.75
            """);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal(3.10m, result[0].PriceGbp);
            Assert.Equal(5.20m, result[0].PriceUsd);
            Assert.Equal(4.05m, result[0].PriceEur);
            Assert.Equal(6.75m, result[0].PriceCad);
            Assert.Null(result[1].PriceGbp);
            // Availability deliberately does not travel with price.
            Assert.Null(result[0].SupersededBy);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Apply_RetractSection_DoesNotDisableFieldOverrides()
    {
        // `retract:` is a per-brand LIST, so it does not fit the brand-keyed override shape. A
        // single typed parse of the whole document threw on it and silently dropped EVERY field
        // override in the file; sections must bind independently.
        string path = WriteTempOverrides("""
            retract:
              citadel-colour:
                - "some|identity|key"
            citadel-colour:
              "Mephiston Red|Base":
                ean: "5011921153770"
            """);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("5011921153770", result[0].Ean);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void Apply_PreservesLeadingZeroScalars()
    {
        // Each section is bound from a re-emitted node, so a numeric-looking STRING has to survive
        // that round trip with its quoting intact -- an EAN or product code that came back as an
        // integer would silently lose its leading zeros.
        string path = WriteTempOverrides("""
            citadel-colour:
              "Mephiston Red|Base":
                ean: '0011921153770'
                productCode: '0605'
            """);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.Apply(SamplePaints, "citadel-colour", path);

            Assert.Equal("0011921153770", result[0].Ean);
            Assert.Equal("0605", result[0].ProductCode);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void AppendAdditions_MintsColourlessPaint()
    {
        string path = WriteTempOverrides("""
            additions:
              citadel-colour:
                - name: Hexwraith Flame
                  set: Contrast
                  productCode: '99189960060'
                  source: GW trade announcement
            """);

        try
        {
            IReadOnlyList<Paint> result = OverrideApplier.AppendAdditions(SamplePaints, "citadel-colour", path);

            Assert.Equal(SamplePaints.Count + 1, result.Count);
            Paint minted = result[^1];
            Assert.Equal("Hexwraith Flame", minted.Name);
            Assert.Equal("Contrast", minted.Set);
            Assert.Equal("99189960060", minted.ProductCode);
            Assert.Equal("", minted.Hex);   // colour-less until a swatch/override lands
            Assert.Equal(0, minted.R);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void AppendAdditions_IsIdempotentAndBrandScoped()
    {
        string path = WriteTempOverrides("""
            additions:
              citadel-colour:
                - name: Mephiston Red
                  set: Base
              vallejo:
                - name: Black
                  set: Model Color
            """);

        try
        {
            IReadOnlyList<Paint> once = OverrideApplier.AppendAdditions(SamplePaints, "citadel-colour", path);
            IReadOnlyList<Paint> twice = OverrideApplier.AppendAdditions(once, "citadel-colour", path);

            // Already present under the same {Name}|{Set}|{ProductCode}: not minted again, and the
            // other brand's addition never leaks in.
            Assert.Equal(SamplePaints.Count, once.Count);
            Assert.Equal(SamplePaints.Count, twice.Count);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void AppendAdditions_ThenApply_LetsFieldOverridesWin()
    {
        string path = WriteTempOverrides("""
            additions:
              citadel-colour:
                - name: Hexwraith Flame
                  set: Contrast
                  productCode: '99189960060'
            citadel-colour:
              "Hexwraith Flame|Contrast":
                hex: "#1E7A2C"
            """);

        try
        {
            IReadOnlyList<Paint> minted = OverrideApplier.AppendAdditions(SamplePaints, "citadel-colour", path);
            IReadOnlyList<Paint> result = OverrideApplier.Apply(minted, "citadel-colour", path);

            Paint contrast = result.Single(p => p.Set == "Contrast");
            Assert.Equal("#1E7A2C", contrast.Hex);
            Assert.Equal(0x1E, contrast.R);   // RGB recomputed from the overridden hex
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public void LinkSupersessions_DerivesTheReverseDirection()
    {
        var paints = new List<Paint>
        {
            new() { Name = "Hexwraith Flame", Set = "Technical", R = 41, G = 162, B = 54, Hex = "#29A236",
                    SupersededBy = "Hexwraith Flame|Contrast" },
            new() { Name = "Hexwraith Flame", Set = "Contrast", R = 0, G = 0, B = 0, Hex = "" },
        };

        IReadOnlyList<Paint> result = OverrideApplier.LinkSupersessions(paints);

        Paint technical = result.Single(p => p.Set == "Technical");
        Paint contrast = result.Single(p => p.Set == "Contrast");
        Assert.Equal("Hexwraith Flame|Contrast", technical.SupersededBy);
        Assert.Equal(["Hexwraith Flame|Technical"], contrast.Supersedes);
        Assert.Null(technical.Supersedes);
        Assert.Null(contrast.SupersededBy);
    }

    [Fact]
    public void LinkSupersessions_IgnoresDanglingAndSelfReferences()
    {
        var paints = new List<Paint>
        {
            new() { Name = "Ghost", Set = "Technical", R = 0, G = 0, B = 0, Hex = "#000000",
                    SupersededBy = "Nothing|Here" },
            new() { Name = "Loop", Set = "Base", R = 0, G = 0, B = 0, Hex = "#000000",
                    SupersededBy = "Loop|Base" },
        };

        IReadOnlyList<Paint> result = OverrideApplier.LinkSupersessions(paints);

        // The declaration is preserved as written; only the derived reverse link is withheld.
        Assert.Equal("Nothing|Here", result[0].SupersededBy);
        Assert.All(result, p => Assert.Null(p.Supersedes));
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

    [Fact]
    public void A_weight_assertion_retires_the_volume_and_container_the_table_wrote()
    {
        // The live case: `Foam Primer and Coat - Black 250gr|Primer` in data/paints/overrides.yaml.
        // By the time Apply runs, VolumeEnricher has already stamped Green Stuff World's brand-wide
        // 17 ml dropper onto the record (PaintCatalogApp.cs:223), so this is the only mechanism in
        // the pipeline that can withdraw a volume -- an override cannot write `volumeMl: null`,
        // because YamlDotNet cannot tell that from the key being absent.
        IReadOnlyList<Paint> stamped =
            [SamplePaints[0] with { VolumeMl = 17, Packaging = "dropper" }];
        string path = WriteTempOverrides("citadel-colour:\n  Mephiston Red|Base:\n    weightG: 250\n");

        try
        {
            Paint result = OverrideApplier.Apply(stamped, "citadel-colour", path).Single();

            Assert.Equal(250, result.WeightG);
            Assert.Null(result.VolumeMl);
            Assert.Null(result.Packaging);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void A_volume_assertion_still_behaves_exactly_as_it_did_before_weightG_existed()
    {
        // 63 `volumeMl:` lines in the committed overrides file depend on this, including the 15
        // Green Stuff World per-record figures the mixed sets need. A volume override replaces the
        // volume, keeps the container it says nothing about, and leaves no mass behind.
        IReadOnlyList<Paint> stamped =
            [SamplePaints[0] with { VolumeMl = 17, Packaging = "dropper" }];
        string path = WriteTempOverrides("citadel-colour:\n  Mephiston Red|Base:\n    volumeMl: 60\n");

        try
        {
            Paint result = OverrideApplier.Apply(stamped, "citadel-colour", path).Single();

            Assert.Equal(60, result.VolumeMl);
            Assert.Equal("dropper", result.Packaging);
            Assert.Null(result.WeightG);
        }
        finally
        {
            File.Delete(path);
        }
    }
}
