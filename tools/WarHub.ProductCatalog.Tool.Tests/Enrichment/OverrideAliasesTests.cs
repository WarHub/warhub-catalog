using WarHub.ProductCatalog.Tool.Enrichment;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class OverrideAliasesTests
{
    private static string Temp(string content)
    {
        string p = Path.Combine(Path.GetTempPath(), $"ov-{Guid.NewGuid():N}.yaml");
        File.WriteAllText(p, content);
        return p;
    }

    [Fact]
    public void Load_NullPath_ReturnsEmpty()
    {
        var (aliases, retracted) = OverrideAliases.Load(null, "cmon", "asoiaf", "baratheon");
        Assert.Empty(aliases);
        Assert.Empty(retracted);
    }

    [Fact]
    public void Load_AliasesAndRetract_AreNormalizedAndScoped()
    {
        string file = Temp("""
            aliases:
              cmon/asoiaf/baratheon:
                "New Name": "Old Name"
            retract:
              cmon/asoiaf/baratheon:
                - "Bad Product"
            """);
        try
        {
            var (aliases, retracted) = OverrideAliases.Load(file, "cmon", "asoiaf", "baratheon");
            Assert.Equal("old name", aliases["new name"]);
            Assert.Contains("bad product", retracted);
        }
        finally { File.Delete(file); }
    }

    [Fact]
    public void Load_DifferentFaction_IsNotApplied()
    {
        string file = Temp("""
            retract:
              cmon/asoiaf/lannister:
                - "Bad Product"
            """);
        try
        {
            var (_, retracted) = OverrideAliases.Load(file, "cmon", "asoiaf", "baratheon");
            Assert.Empty(retracted);
        }
        finally { File.Delete(file); }
    }
}
