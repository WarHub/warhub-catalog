using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// Paint ids must depend only on the paint they name. The previous scheme sorted a name-collision
/// group and appended -2/-3 by INDEX, so an id was really a statement about the group's membership:
/// inserting one paint renumbered its siblings, and a name legitimately ending in a digit could
/// collide with another name's positional suffix and silently drop a record.
/// </summary>
public sealed class PaintIdTests
{
    private static PaintYaml Paint(string name, string set, string hex, string? code = null) => new()
    {
        Name = name,
        ProductCode = code,
        Category = "paint",
        Status = "current",
        Availability = "unknown",
        Details = new PaintDetailsYaml { Set = set, Hex = hex },
    };

    private static List<string> Ids(string slug, string brand, params PaintYaml[] paints)
    {
        string dist = Path.Combine(Path.GetTempPath(), "warhub-paint-ids", Guid.NewGuid().ToString("N"));
        var writer = new CatalogWriter(dist, SchemaValidator.LoadFrom(Path.Combine(AppContext.BaseDirectory, "schema")));
        var prov = new Provenance { Version = "id-test", GeneratedAt = "2026-08-04T00:00:00Z", Repo = "WarHub/warhub-catalog" };
        PaintBuilder.Build([new BrandFile { BrandSlug = slug, Brand = brand, Paints = [.. paints] }], null, prov, writer);
        string json = File.ReadAllText(Path.Combine(dist, "paints.json"));
        using var doc = System.Text.Json.JsonDocument.Parse(json);
        return [.. doc.RootElement.GetProperty("paints").EnumerateArray().Select(p => p.GetProperty("id").GetString()!)];
    }

    [Fact]
    public void Colliding_names_are_qualified_by_set_and_nobody_keeps_the_bare_id()
    {
        // A consumer holding the old bare id should get a clean 404, never silently another colour.
        List<string> ids = Ids("citadel-colour", "Citadel Colour",
            Paint("Hexwraith Flame", "Technical", "#29A236"),
            Paint("Hexwraith Flame", "Contrast", "#2AA337"));

        Assert.Contains("citadel-colour/hexwraith-flame-technical", ids);
        Assert.Contains("citadel-colour/hexwraith-flame-contrast", ids);
        Assert.DoesNotContain("citadel-colour/hexwraith-flame", ids);
    }

    [Fact]
    public void An_uncollided_name_keeps_its_bare_id()
    {
        Assert.Equal(["citadel-colour/mephiston-red"],
            Ids("citadel-colour", "Citadel Colour", Paint("Mephiston Red", "Base", "#9A0E05")));
    }

    [Fact]
    public void Qualification_escalates_to_hex_when_set_and_code_are_both_equal()
    {
        // The reformulation case: same name, set and product code, different colour. Vallejo's
        // Viking Grey is exactly this, and qualifying on set alone silently dropped one of them.
        List<string> ids = Ids("vallejo", "Vallejo",
            Paint("Viking Grey", "Xpress Color Intense", "#374855", "72.483"),
            Paint("Viking Grey", "Xpress Color Intense", "#45515D", "72.483"));

        Assert.Equal(2, ids.Count);
        Assert.All(ids, id => Assert.StartsWith("vallejo/viking-grey-xpress-color-intense-72-483-", id));
    }

    [Fact]
    public void A_name_ending_in_a_digit_no_longer_collides_with_a_positional_suffix()
    {
        // Under the old scheme "Blue" + "Blue 2" could both want `brand/blue-2` and the dictionary
        // write silently kept one. Measured: 6 real records were lost this way.
        List<string> ids = Ids("tamiya", "Tamiya",
            Paint("Blue", "Spray", "#0000FF"),
            Paint("Blue", "Aircraft Spray", "#0000EE"),
            Paint("Blue 2", "Spray", "#0000DD"));

        Assert.Equal(3, ids.Count);
        Assert.Contains("tamiya/blue-2", ids);
    }
}
