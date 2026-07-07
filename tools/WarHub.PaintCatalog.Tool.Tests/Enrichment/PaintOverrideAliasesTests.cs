using WarHub.PaintCatalog.Tool.Enrichment;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class PaintOverrideAliasesTests
{
    private static string Temp(string content)
    {
        string p = Path.Combine(Path.GetTempPath(), $"pov-{Guid.NewGuid():N}.yaml");
        File.WriteAllText(p, content);
        return p;
    }

    [Fact]
    public void Load_NullPath_ReturnsEmpty()
    {
        var (aliases, retracted) = PaintOverrideAliases.Load(null, "citadel-colour");
        Assert.Empty(aliases);
        Assert.Empty(retracted);
    }

    [Fact]
    public void Load_MissingPath_ReturnsEmpty()
    {
        string missing = Path.Combine(Path.GetTempPath(), $"pov-missing-{Guid.NewGuid():N}.yaml");
        var (aliases, retracted) = PaintOverrideAliases.Load(missing, "citadel-colour");
        Assert.Empty(aliases);
        Assert.Empty(retracted);
    }

    [Fact]
    public void Load_AliasesAndRetract_AreNormalizedAndScopedToBrand()
    {
        string file = Temp("""
            aliases:
              citadel-colour:
                'base|new name|c1|#000000': 'base|old name|c1|#000000'
            retract:
              citadel-colour:
                - 'base|bad paint|x|#ffffff'
            """);
        try
        {
            var (aliases, retracted) = PaintOverrideAliases.Load(file, "citadel-colour");
            Assert.Equal("base|old name|c1|#000000", aliases["base|new name|c1|#000000"]);
            Assert.Contains("base|bad paint|x|#ffffff", retracted);
        }
        finally { File.Delete(file); }
    }

    [Fact]
    public void Load_DifferentBrandSlug_IsNotApplied()
    {
        string file = Temp("""
            aliases:
              citadel-colour:
                'base|new name|c1|#000000': 'base|old name|c1|#000000'
            retract:
              citadel-colour:
                - 'base|bad paint|x|#ffffff'
            """);
        try
        {
            var (aliases, retracted) = PaintOverrideAliases.Load(file, "vallejo-model-color");
            Assert.Empty(aliases);
            Assert.Empty(retracted);
        }
        finally { File.Delete(file); }
    }

    [Fact]
    public void Load_MixedCaseAuthoredKey_NormalizesToMatchIdentityKey()
    {
        string file = Temp("""
            aliases:
              citadel-colour:
                'Base|New Name|C1|#000000': 'Base|Old Name|C1|#000000'
            retract:
              citadel-colour:
                - 'Base|Bad Paint|X|#FFFFFF'
            """);
        try
        {
            var (aliases, retracted) = PaintOverrideAliases.Load(file, "citadel-colour");
            // NameNormalizer.Normalize lowercases the whole composite key, so a
            // mixed-case authored entry still matches an already-normalized
            // identity key produced by PaintRecordAdapter.
            Assert.Equal("base|old name|c1|#000000", aliases["base|new name|c1|#000000"]);
            Assert.Contains("base|bad paint|x|#ffffff", retracted);
        }
        finally { File.Delete(file); }
    }
}
