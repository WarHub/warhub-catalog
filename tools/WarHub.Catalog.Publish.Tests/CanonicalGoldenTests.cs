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

    private JsonElement PaintingHandle =>
        fx.Products.EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Citadel Painting Handle");

    [Fact]
    public void All_three_products_are_published()
    {
        Assert.Equal(3, fx.Result.Products);
    }

    [Fact]
    public void Null_game_system_product_publishes_with_gameSystem_omitted_and_no_partition()
    {
        // gameSystem is optional -- a system-less product (here, a painting tool; in the real
        // catalog also bases, gaming mats, dice, advent calendars, ...) publishes in the
        // consolidated catalog with its confirmed ean, but gameSystem itself is omitted (never
        // written as a literal null), same as every other optional field in this schema.
        Assert.False(PaintingHandle.TryGetProperty("gameSystems", out _));
        Assert.Equal("5011921194803", PaintingHandle.GetProperty("ean").GetString());
        Assert.Equal("confirmed", PaintingHandle.GetProperty("eanConfidence").GetString());

        string byStemDir = Path.Combine(fx.Dist, "products", "by-system");
        if (Directory.Exists(byStemDir))
        {
            foreach (string file in Directory.EnumerateFiles(byStemDir, "*.json"))
            {
                JsonElement partitionProducts = JsonDocument.Parse(File.ReadAllText(file))
                    .RootElement.GetProperty("products");
                Assert.DoesNotContain(partitionProducts.EnumerateArray(),
                    p => p.GetProperty("name").GetString() == "Citadel Painting Handle");
            }
        }
    }

    [Fact]
    public void Id_and_manufacturer_are_published_for_every_product()
    {
        // Phase 1 of the archival direction: an entity id + manufacturer are published so a
        // lineage link (supersededBy / supersedes) has a stable target. Both are required on
        // every product; the id is the resolver's `manufacturer/<code-or-slug>` entity id.
        foreach (JsonElement p in fx.Products.EnumerateArray())
        {
            Assert.False(string.IsNullOrEmpty(p.GetProperty("id").GetString()));
            Assert.Equal("games-workshop", p.GetProperty("manufacturer").GetString());
        }
        Assert.Equal("games-workshop/99120110052", Necrons.GetProperty("id").GetString());
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
    public void A_setting_resolves_to_its_label_and_is_omitted_where_there_is_none()
    {
        // Both kits derive their setting from their game; the painting handle belongs to no game
        // and no universe, and the property is omitted rather than published as null or [] --
        // the same treatment gameSystems gets.
        Assert.Equal(["Warhammer 40,000"], Necrons.GetProperty("settings").EnumerateArray().Select(v => v.GetString()!));
        Assert.Equal(["Warhammer 40,000"], DeathGuard.GetProperty("settings").EnumerateArray().Select(v => v.GetString()!));
        Assert.False(PaintingHandle.TryGetProperty("settings", out _));
    }

    [Fact]
    public void The_product_index_groups_its_partitions_by_setting()
    {
        JsonElement index = JsonDocument.Parse(File.ReadAllText(Path.Combine(fx.Dist, "products", "index.json"))).RootElement;
        JsonElement partition = index.GetProperty("partitions").EnumerateArray().Single();
        Assert.Equal("warhammer-40k", partition.GetProperty("setting").GetString());
        JsonElement setting = index.GetProperty("settings").EnumerateArray().Single();
        Assert.Equal("warhammer-40k", setting.GetProperty("key").GetString());
        Assert.Equal("Warhammer 40,000", setting.GetProperty("label").GetString());
    }

    [Fact]
    public void Game_system_label_resolves_for_both_products()
    {
        Assert.Equal(["Warhammer 40,000"], Necrons.GetProperty("gameSystems").EnumerateArray().Select(v => v.GetString()!));
        Assert.Equal(["Warhammer 40,000"], DeathGuard.GetProperty("gameSystems").EnumerateArray().Select(v => v.GetString()!));
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
        Assert.Equal("current", Necrons.GetProperty("status").GetString());
        Assert.Equal("in_stock", Necrons.GetProperty("availability").GetString());
    }

    [Fact]
    public void An_unstated_category_publishes_as_null_rather_than_as_miniatures()
    {
        // THE END-TO-END PROOF THAT THE FALLBACK IS GONE, and it took both stacks to remove: the
        // resolver used to write `miniatures` whenever no source spoke, and this publisher used to
        // write it a second time (`p.Category ?? "miniatures"`) for anything that arrived null. A
        // consumer therefore could not tell a stated category from a filled one on any product.
        //
        // Necrons: nothing in the fixture states a category, so the property is absent entirely --
        // the same treatment `gameSystem` already gets one test above, since the writer omits
        // nulls rather than emitting them.
        // Painting Handle: mfr-gw-algolia states `hobby-auxiliary`, so it survives untouched --
        // the point is that absence is published as absence, not that categories stopped flowing.
        Assert.False(Necrons.TryGetProperty("category", out _));
        Assert.Equal("hobby-auxiliary", PaintingHandle.GetProperty("category").GetString());
    }

    [Fact]
    public void Price_cad_flows_through_alongside_price_gbp_and_absent_price_cad_is_omitted()
    {
        // Necrons: priceGbp from the manufacturer observation, priceCad added alongside it
        // (Task 8) -- proves the new currency round-trips through canonical YAML into the
        // published product exactly like the pre-existing currencies.
        Assert.Equal(76.5m, Necrons.GetProperty("priceGbp").GetDecimal());
        Assert.Equal(129.99m, Necrons.GetProperty("priceCad").GetDecimal());
        // Boarding Patrol: no priceCad in the source data -> omitted, not published as null.
        Assert.False(DeathGuard.TryGetProperty("priceCad", out _));
    }
}
