using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class RoleInvariantTests
{
    private static PaintRecord R(string name, string? role, bool? colourless = null, string? code = "C1") => new()
    {
        Name = name, Category = "paint", Status = "current", Availability = "unknown",
        Colourless = colourless, Role = role, ProductCode = code,
        Details = new PaintDetails { Set = "Technical", R = 0, G = 0, B = 0, Hex = colourless == true ? "" : "#FFFFFF" },
    };

    [Fact]
    public void AConsistentBrandHasNoViolations()
    {
        IReadOnlyList<string> violations = RoleInvariant.Violations("citadel-colour",
        [
            R("Abaddon Black", "colour"),
            R("'Ardcoat", "varnish", colourless: true),
            R("Lahmian Medium", "medium", colourless: true),
            R("Airbrush Cleaner", "cleaner", colourless: true),
            // A primer may be clear (Mission Models' Clear Primer) or not (Chaos Black): both fine.
            R("Clear Primer (Transparent)", "primer", colourless: true),
            R("Chaos Black", "primer"),
            R("Stirland Mud", "texture"),
            R("Desert Dust", "pigment"),
        ]);

        Assert.Empty(violations);
    }

    [Fact]
    public void AVarnishMediumOrCleanerWithoutTheFlagIsAViolation()
    {
        IReadOnlyList<string> violations = RoleInvariant.Violations("mr-hobby",
        [
            R("Super Smooth Clear", "varnish", code: "GX114"),
            R("Flat Base", "medium", code: "30"),
            R("Tool Cleaner", "cleaner", code: "T-113"),
            R("Clear", "varnish", colourless: true),   // fine
        ]);

        Assert.Equal(3, violations.Count);
        // Names the brand, the record and its code, and says what to do -- this is what a failed
        // CI run prints, and the reader has to be able to act on it without opening the tool.
        Assert.Contains(violations, v => v.Contains("mr-hobby: 'Super Smooth Clear' [Technical] GX114")
            && v.Contains("role varnish requires `colourless: true`") && v.Contains("overrides.yaml"));
        Assert.Contains(violations, v => v.Contains("'Flat Base'") && v.Contains("role medium"));
        Assert.Contains(violations, v => v.Contains("'Tool Cleaner'") && v.Contains("role cleaner"));
    }

    [Fact]
    public void AFlaggedRecordThatIsAColourIsAViolation()
    {
        // The reverse direction: the hand flag stands while the classifier has gone quiet on the
        // record (a varnish renamed upstream, a rule that regressed).
        IReadOnlyList<string> violations = RoleInvariant.Violations("vallejo",
            [R("Gloss Varnsh", "colour", colourless: true, code: "70.510")]);

        string only = Assert.Single(violations);
        Assert.Contains("vallejo: 'Gloss Varnsh' [Technical] 70.510", only);
        Assert.Contains("`colourless: true` but role colour", only);
    }

    [Fact]
    public void AMissingOrUnknownRoleIsAViolation()
    {
        IReadOnlyList<string> violations = RoleInvariant.Violations("reaper",
        [
            R("Black Wash", null, code: null),
            R("Brush-on Sealer", "  ", colourless: true),
            R("Blue Flame", "paint"),
        ]);

        Assert.Equal(3, violations.Count);
        Assert.Contains(violations, v => v == "reaper: 'Black Wash' [Technical]: no role");
        Assert.Contains(violations, v => v.Contains("'Brush-on Sealer'") && v.EndsWith(": no role"));
        Assert.Contains(violations, v => v.Contains("role 'paint' is not in the vocabulary") && v.Contains("colour, primer, varnish"));
    }
}
