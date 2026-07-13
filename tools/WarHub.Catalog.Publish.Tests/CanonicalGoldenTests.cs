using System.Text.Json;
using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// Publishes the committed cross-stack golden fixture (fixtures/canonical-golden/) through the
/// real pipeline (<see cref="YamlSource"/> -> <see cref="ProductBuilder"/>). That fixture is the
/// literal, byte-for-byte output of the Python resolver -- see
/// tools/acquisition/tests/test_golden_fixture.py, which regenerates it and fails CI on drift.
/// Running the SAME files through both stacks and asserting the same values here is the proof
/// that the two writers agree.
/// </summary>
public sealed class CanonicalGoldenFixture : IDisposable
{
    public string Root { get; }
    public string Dist { get; }
    internal PublishResult Result { get; }

    public CanonicalGoldenFixture()
    {
        Root = Path.Combine(Path.GetTempPath(), "warhub-catalog-golden-tests", Guid.NewGuid().ToString("N"));
        Dist = Path.Combine(Root, "dist");
        string catalogDir = Path.Combine(AppContext.BaseDirectory, "fixtures", "canonical-golden");
        string paintsDir = Path.Combine(Root, "paints"); // deliberately never created: zero paints

        var prov = new Provenance
        {
            Version = "golden-test",
            GeneratedAt = "2026-07-12T00:00:00Z",
            GitCommit = "cafefeed",
            Repo = "WarHub/warhub-catalog",
        };

        string schemaDir = Path.Combine(AppContext.BaseDirectory, "schema");
        Result = Publisher.Run(new PublishOptions(catalogDir, paintsDir, Dist, schemaDir, prov));
    }

    public JsonElement Products =>
        JsonDocument.Parse(File.ReadAllText(Path.Combine(Dist, "products.json"))).RootElement.GetProperty("products");

    public void Dispose()
    {
        try { Directory.Delete(Root, recursive: true); } catch { /* best effort */ }
    }
}

public sealed class CanonicalGoldenTests(CanonicalGoldenFixture fx) : IClassFixture<CanonicalGoldenFixture>
{
    private JsonElement Necrons =>
        fx.Products.EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Combat Patrol: Necrons");

    private JsonElement DeathGuard =>
        fx.Products.EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Boarding Patrol: Death Guard");

    [Fact]
    public void Both_products_are_published()
    {
        Assert.Equal(2, fx.Result.Products);
    }

    [Fact]
    public void Confirmed_ean_from_curated_assertion_flows_through()
    {
        JsonElement p = Necrons;
        Assert.Equal("5011921194506", p.GetProperty("ean").GetString());
        Assert.Equal("confirmed", p.GetProperty("eanConfidence").GetString());
    }

    [Fact]
    public void Provisional_ean_from_lone_retailer_assertion_flows_through()
    {
        JsonElement p = DeathGuard;
        Assert.Equal("5011921194605", p.GetProperty("ean").GetString());
        Assert.Equal("provisional", p.GetProperty("eanConfidence").GetString());
    }

    [Fact]
    public void Quantity_present_flows_through_and_absent_defaults_to_one()
    {
        Assert.Equal(3, Necrons.GetProperty("quantity").GetInt32());
        Assert.Equal(1, DeathGuard.GetProperty("quantity").GetInt32()); // no quantity in source -> fallback to 1
    }

    [Fact]
    public void Faction_present_resolves_to_its_label_and_absent_faction_is_omitted()
    {
        Assert.Equal("Necrons", Necrons.GetProperty("faction").GetString());
        Assert.False(DeathGuard.TryGetProperty("faction", out _)); // null faction -> omitted, not published as null
    }

    [Fact]
    public void Game_system_label_resolves_for_both_products()
    {
        Assert.Equal("Warhammer 40,000", Necrons.GetProperty("gameSystem").GetString());
        Assert.Equal("Warhammer 40,000", DeathGuard.GetProperty("gameSystem").GetString());
    }

    [Fact]
    public void Product_code_is_present_when_resolved_and_falls_back_to_sku_otherwise()
    {
        // Necrons: manufacturer sku matched the codePattern, so productCode is the code itself.
        Assert.Equal("99120110052", Necrons.GetProperty("productCode").GetString());
        // Boarding Patrol: neither source's sku matched the codePattern (the two observations
        // only merged via a forced name-join), so the resolver never populated productCode --
        // the publisher falls back to the raw sku.
        Assert.Equal("BOARD-DG", DeathGuard.GetProperty("productCode").GetString());
    }

    [Fact]
    public void Category_status_and_availability_surface_as_resolved()
    {
        Assert.Equal("miniatures", Necrons.GetProperty("category").GetString());
        Assert.Equal("current", Necrons.GetProperty("status").GetString());
        Assert.Equal("in_stock", Necrons.GetProperty("availability").GetString());
    }
}
