using System.Text.Json;
using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// The published boxed-set relation, read back off the real dist/ tree the fixture builds.
/// </summary>
public sealed class SetContentsTests(PublishFixture fx) : IClassFixture<PublishFixture>
{
    private JsonElement Doc => JsonDocument.Parse(fx.ReadDist("set-contents.json")).RootElement;

    private JsonElement Set(string productId) => Doc.GetProperty("sets").GetProperty(productId);

    [Fact]
    public void Set_contents_carries_the_same_self_describing_envelope_as_every_other_document()
    {
        JsonElement doc = Doc;
        Assert.Equal("1.1", doc.GetProperty("schemaVersion").GetString());
        Assert.Equal("set-contents", doc.GetProperty("kind").GetString());
        Assert.Equal("2026.7.4", doc.GetProperty("version").GetString());
        Assert.Equal("2026-07-04T00:00:00Z", doc.GetProperty("generatedAt").GetString());
        Assert.Equal("deadbeef", doc.GetProperty("gitCommit").GetString());

        JsonElement source = doc.GetProperty("source");
        Assert.Equal("WarHub/warhub-catalog", source.GetProperty("repo").GetString());
        Assert.Equal(
            "https://warhub.github.io/warhub-catalog/set-contents.json",
            source.GetProperty("pageUrl").GetString());
    }

    [Fact]
    public void Every_set_is_keyed_by_its_product_id_verbatim()
    {
        string[] keys = [.. Doc.GetProperty("sets").EnumerateObject().Select(p => p.Name)];

        // Keys are product ids exactly as products.json publishes them -- manufacturer casing
        // intact, not camelCased by the serializer's property policy.
        Assert.Equal(["test-mfg/alpha", "test-mfg/beta", "test-mfg/gamma"], keys);
    }

    [Fact]
    public void Member_names_the_paint_by_its_published_id_and_the_source_code_verbatim()
    {
        JsonElement first = Set("test-mfg/alpha").GetProperty("members")[0];

        // The whole point of publishing this from the publisher rather than upstream: the paint
        // id exists only here, and it resolves in paints.json.
        Assert.Equal("citadel/abaddon-black", first.GetProperty("paintId").GetString());

        // And the source's own code survives, unnormalized -- it is the link back to contentSkus.
        Assert.Equal("0C1", first.GetProperty("ref").GetString());

        string paints = fx.ReadDist("paints.json");
        Assert.Contains("\"id\":\"citadel/abaddon-black\"", paints);
    }

    [Fact]
    public void Members_keep_the_order_the_source_listed_them_in()
    {
        string[] refs = [.. Set("test-mfg/alpha").GetProperty("members")
            .EnumerateArray().Select(m => m.GetProperty("ref").GetString()!)];

        // Not sorted -- for a `stated` set this is the manufacturer's own array order, which is
        // its statement about its own box.
        Assert.Equal(["0C1", "V1", "C2"], refs);
    }

    [Fact]
    public void All_three_contents_claims_survive_publication_separately()
    {
        Assert.Equal("stated", Set("test-mfg/alpha").GetProperty("contentSkusFrom").GetString());
        Assert.Equal("description", Set("test-mfg/beta").GetProperty("contentSkusFrom").GetString());
        Assert.Equal("sku", Set("test-mfg/gamma").GetProperty("contentSkusFrom").GetString());
    }

    [Fact]
    public void A_sku_set_has_exactly_one_member_and_says_nothing_about_multiplicity()
    {
        JsonElement gamma = Set("test-mfg/gamma");
        JsonElement member = Assert.Single(gamma.GetProperty("members").EnumerateArray());

        Assert.Equal("citadel/weathering-powder-rust", member.GetProperty("paintId").GetString());
        // The pack size lives in the name, where the store put it -- never in `quantity`, which
        // would be an invented count.
        Assert.False(member.TryGetProperty("quantity", out _));
        Assert.Contains("Pack of 6", gamma.GetProperty("name").GetString());
    }

    [Fact]
    public void Quantity_is_carried_when_stated_and_absent_when_not()
    {
        JsonElement[] members = [.. Set("test-mfg/alpha").GetProperty("members").EnumerateArray()];

        Assert.Equal(2, members[0].GetProperty("quantity").GetInt32());
        // Absence must stay distinct from 1: no source said how many of these the box holds.
        Assert.False(members[1].TryGetProperty("quantity", out _));
    }

    [Fact]
    public void A_resolution_the_printed_code_did_not_reach_on_its_own_says_so()
    {
        JsonElement member = Set("test-mfg/alpha").GetProperty("members")[2];

        Assert.Equal("statedName", member.GetProperty("resolvedBy").GetString());
        Assert.Equal("MEPHISTON RED", member.GetProperty("statedName").GetString());

        // And the ordinary case carries neither, rather than carrying a "resolved by code" value:
        // absence is the norm and would be noise on 2,211 of 2,214 real members.
        JsonElement plain = Set("test-mfg/alpha").GetProperty("members")[1];
        Assert.False(plain.TryGetProperty("resolvedBy", out _));
        Assert.False(plain.TryGetProperty("statedName", out _));
    }

    [Fact]
    public void Refused_refs_are_published_with_their_reason_not_dropped()
    {
        JsonElement unresolved = Assert.Single(Set("test-mfg/alpha").GetProperty("unresolved").EnumerateArray());

        Assert.Equal("NOSUCH", unresolved.GetProperty("ref").GetString());
        Assert.Contains("no paint", unresolved.GetProperty("reason").GetString());

        // A set that resolved everything omits the key entirely rather than publishing [].
        Assert.False(Set("test-mfg/gamma").TryGetProperty("unresolved", out _));
        Assert.DoesNotContain("\"unresolved\":[]", fx.ReadDist("set-contents.json"));
    }

    [Fact]
    public void Counts_reconcile_refs_to_members_plus_unresolved()
    {
        JsonElement counts = Doc.GetProperty("counts");

        Assert.Equal(3, counts.GetProperty("sets").GetInt32());
        Assert.Equal(7, counts.GetProperty("refs").GetInt32());
        Assert.Equal(5, counts.GetProperty("members").GetInt32());
        Assert.Equal(5, counts.GetProperty("paints").GetInt32());
        Assert.Equal(2, counts.GetProperty("unresolved").GetInt32());
        // Nothing upstream resolved was lost on the way through this build.
        Assert.Equal(0, counts.GetProperty("unresolvedAtPublish").GetInt32());

        Assert.Equal(
            counts.GetProperty("refs").GetInt32(),
            counts.GetProperty("members").GetInt32() + counts.GetProperty("unresolved").GetInt32());

        Assert.Equal(3, fx.Result.Sets);
        Assert.Equal(5, fx.Result.SetMembers);
    }

    [Fact]
    public void Every_published_paint_id_resolves_in_the_paint_catalog()
    {
        var published = JsonDocument.Parse(fx.ReadDist("paints.json"))
            .RootElement.GetProperty("paints")
            .EnumerateArray()
            .Select(p => p.GetProperty("id").GetString())
            .ToHashSet(StringComparer.Ordinal);

        string[] referenced = [.. Doc.GetProperty("sets").EnumerateObject()
            .SelectMany(s => s.Value.GetProperty("members").EnumerateArray())
            .Select(m => m.GetProperty("paintId").GetString()!)];

        Assert.NotEmpty(referenced);
        Assert.All(referenced, id => Assert.Contains(id, published));
    }

    [Fact]
    public void Every_set_key_resolves_in_the_product_catalog()
    {
        var published = JsonDocument.Parse(fx.ReadDist("products.json"))
            .RootElement.GetProperty("products")
            .EnumerateArray()
            .Select(p => p.GetProperty("id").GetString())
            .ToHashSet(StringComparer.Ordinal);

        Assert.All(
            Doc.GetProperty("sets").EnumerateObject().Select(p => p.Name),
            id => Assert.Contains(id, published));
    }

    [Theory]
    // An unknown contents claim. The enum is the point of the field: a fourth value would be a
    // claim of unstated strength, and a consumer branching on the three would silently mis-handle it.
    [InlineData(
        """{"schemaVersion":"1.1","kind":"set-contents","version":"1","generatedAt":"t","counts":{},"source":{"repo":"r"},"sets":{"m/A":{"name":"n","contentSkusFrom":"guessed","members":[]}}}""",
        "contentSkusFrom")]
    // A member with no paint id — the one field that makes this document worth publishing.
    [InlineData(
        """{"schemaVersion":"1.1","kind":"set-contents","version":"1","generatedAt":"t","counts":{},"source":{"repo":"r"},"sets":{"m/A":{"name":"n","contentSkusFrom":"stated","members":[{"ref":"R1"}]}}}""",
        "paintId")]
    // A refusal with no reason: an unresolved ref that does not say why is the silence this
    // document exists to prevent.
    [InlineData(
        """{"schemaVersion":"1.1","kind":"set-contents","version":"1","generatedAt":"t","counts":{},"source":{"repo":"r"},"sets":{"m/A":{"name":"n","contentSkusFrom":"stated","members":[],"unresolved":[{"ref":"R1"}]}}}""",
        "reason")]
    // A key that is not a product id, so the document could not be looked up by one.
    [InlineData(
        """{"schemaVersion":"1.1","kind":"set-contents","version":"1","generatedAt":"t","counts":{},"source":{"repo":"r"},"sets":{"Not An Id":{"name":"n","contentSkusFrom":"stated","members":[]}}}""",
        "sets")]
    public void Schema_rejects_a_malformed_set_contents_document(string json, string expected)
    {
        SchemaValidator validator = SchemaValidator.LoadFrom(Path.Combine(AppContext.BaseDirectory, "schema"));

        InvalidOperationException ex = Assert.Throws<InvalidOperationException>(
            () => validator.Validate("set-contents", json, "set-contents.json"));

        Assert.Contains("set-contents.json", ex.Message, StringComparison.Ordinal);
        Assert.Contains(expected, ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Every_property_the_document_emits_is_declared_in_the_schema()
    {
        // The parity guard SchemaParityTests makes for PaintRecord, applied to the two record
        // types this document introduces: no schema here sets additionalProperties:false, so an
        // added-but-undeclared property would ship silently, exactly as soldSeparately once did.
        using JsonDocument schema = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(AppContext.BaseDirectory, "schema", "set-contents.json")));
        JsonElement defs = schema.RootElement.GetProperty("$defs");
        JsonNamingPolicy policy = JsonConfig.Options.PropertyNamingPolicy!;

        foreach ((string def, Type type) in new (string, Type)[]
                 { ("set", typeof(SetRecord)), ("member", typeof(SetMemberRecord)), ("unresolved", typeof(UnresolvedRef)) })
        {
            JsonElement declared = defs.GetProperty(def).GetProperty("properties");
            string[] emitted = [.. type.GetProperties().Select(p => policy.ConvertName(p.Name))];

            Assert.Equal([], emitted.Where(n => !declared.TryGetProperty(n, out _)).Order(StringComparer.Ordinal));
            Assert.Equal([], declared.EnumerateObject().Select(p => p.Name)
                .Where(n => !emitted.Contains(n, StringComparer.Ordinal)).Order(StringComparer.Ordinal));
        }
    }

    [Fact]
    public void Set_contents_is_manifested_and_validated_like_every_other_document()
    {
        JsonElement manifest = JsonDocument.Parse(fx.ReadDist("manifest.json")).RootElement;

        JsonElement entry = manifest.GetProperty("files").EnumerateArray()
            .Single(f => f.GetProperty("path").GetString() == "set-contents.json");
        Assert.Equal("set-contents", entry.GetProperty("kind").GetString());
        Assert.Equal(3, entry.GetProperty("records").GetInt32());

        Assert.Equal(3, manifest.GetProperty("counts").GetProperty("sets").GetInt32());
        Assert.Equal(5, manifest.GetProperty("counts").GetProperty("setMembers").GetInt32());

        Assert.True(File.Exists(Path.Combine(fx.Dist, "schema", "set-contents.json")));
    }
}

/// <summary>
/// The builder on its own, over hand-built records — the paths the fixture cannot reach because
/// they need a catalog that disagrees with its own relation.
/// </summary>
public sealed class SetContentsBuilderTests
{
    private static ProductRecord Product(string id) => new()
    {
        Id = id,
        Manufacturer = "test-mfg",
        Name = id,
        Category = "miniatures",
        Status = "current",
        Availability = "in_stock",
    };

    private static PaintRecord Paint(string id, string name, string? range, string? code, string? hex = "#000000") =>
        new(id, "Test", "paint", "colour", range, name, hex, null, null, null, null, null, code, null, null, null,
            null, null, null, null, "current", "unknown", null, null, null, null, []);

    private static CanonicalSet Set(string from, params CanonicalSetMember[] members) => new()
    {
        Name = "A Box",
        From = from,
        Members = [.. members],
    };

    private static CanonicalSetMember Member(string re, string brand, string paint, string? code) =>
        new() { Ref = re, Brand = brand, Paint = paint, ProductCode = code };

    private static Dictionary<string, CanonicalSetContentsFile> File(
        params (string ProductId, CanonicalSet Set)[] sets) =>
        new(StringComparer.Ordinal)
        {
            ["test-mfg"] = new CanonicalSetContentsFile
            {
                Sets = sets.ToDictionary(s => s.ProductId, s => s.Set, StringComparer.Ordinal),
            },
        };

    [Fact]
    public void A_member_naming_a_paint_this_release_does_not_publish_is_refused_not_dropped()
    {
        SetContents contents = SetContents.Build(
            File(("test-mfg/a", Set("stated", Member("R1", "test", "Gone|Range", "G1")))),
            [Product("test-mfg/a")],
            [Paint("test/kept", "Kept", "Range", "K1")]);

        Assert.Equal(0, contents.Members);
        Assert.Equal(1, contents.UnresolvedAtPublish);
        // The ref still reaches the consumer, with a reason naming this stage rather than upstream.
        UnresolvedRef refused = Assert.Single(contents.Sets["test-mfg/a"].Unresolved!);
        Assert.Equal("R1", refused.Ref);
        Assert.Contains("publishes no paint with that identity", refused.Reason);
        // The invariant a consumer relies on holds even here.
        Assert.Equal(contents.Refs, contents.Members + contents.UnresolvedUpstream + contents.UnresolvedAtPublish);
    }

    [Fact]
    public void An_identity_naming_two_paints_is_refused_rather_than_resolved_to_either()
    {
        // Same brand, name, range and code; different colours. PaintBuilder keeps both because hex
        // is part of a paint's natural key -- but hex is not in this relation, so the ref cannot
        // choose between them.
        SetContents contents = SetContents.Build(
            File(("test-mfg/a", Set("stated", Member("R1", "test", "Twin|Range", "T1")))),
            [Product("test-mfg/a")],
            [Paint("test/twin-a", "Twin", "Range", "T1", "#111111"),
             Paint("test/twin-b", "Twin", "Range", "T1", "#222222")]);

        Assert.Equal(0, contents.Members);
        Assert.Equal(1, contents.UnresolvedAtPublish);
        Assert.Contains("names more than one published paint", contents.Sets["test-mfg/a"].Unresolved![0].Reason);
    }

    [Fact]
    public void A_set_whose_product_is_not_published_is_left_out_rather_than_dangling()
    {
        SetContents contents = SetContents.Build(
            File(
                ("test-mfg/a", Set("stated", Member("R1", "test", "Kept|Range", "K1"))),
                ("test-mfg/ghost", Set("stated", Member("R2", "test", "Kept|Range", "K1")))),
            [Product("test-mfg/a")],
            [Paint("test/kept", "Kept", "Range", "K1")]);

        Assert.Equal(["test-mfg/a"], contents.Sets.Keys);
        Assert.Equal(1, contents.SetsWithoutProduct);
        // Its refs leave with it: they were never about a product this release publishes.
        Assert.Equal(1, contents.Members);
    }

    [Fact]
    public void A_generated_file_disagreeing_with_its_own_counts_fails_the_build()
    {
        var files = new Dictionary<string, CanonicalSetContentsFile>(StringComparer.Ordinal)
        {
            ["test-mfg"] = new CanonicalSetContentsFile
            {
                Counts = new CanonicalSetCounts { Sets = 1, Refs = 9, Members = 9, Unresolved = 0 },
                Sets = new Dictionary<string, CanonicalSet>(StringComparer.Ordinal)
                {
                    ["test-mfg/a"] = Set("stated", Member("R1", "test", "Kept|Range", "K1")),
                },
            },
        };

        InvalidOperationException ex = Assert.Throws<InvalidOperationException>(() => SetContents.Build(
            files, [Product("test-mfg/a")], [Paint("test/kept", "Kept", "Range", "K1")]));

        Assert.Contains("set-contents/test-mfg", ex.Message);
        Assert.Contains("counts.members says 9 but the file holds 1", ex.Message);
    }

    [Fact]
    public void Sets_are_keyed_in_ordinal_order_regardless_of_the_order_they_were_read_in()
    {
        SetContents contents = SetContents.Build(
            File(
                ("test-mfg/zulu", Set("stated", Member("R1", "test", "Kept|Range", "K1"))),
                ("test-mfg/alpha", Set("stated", Member("R2", "test", "Kept|Range", "K1")))),
            [Product("test-mfg/zulu"), Product("test-mfg/alpha")],
            [Paint("test/kept", "Kept", "Range", "K1")]);

        Assert.Equal(["test-mfg/alpha", "test-mfg/zulu"], contents.Sets.Keys);
    }

    [Fact]
    public void A_paint_whose_range_is_blank_is_matched_by_the_empty_set_half_of_the_key()
    {
        // PaintBuilder publishes Range as null when the archive's `set` is blank, and the upstream
        // relation writes "{Name}|" for the same paint. The two must still meet.
        SetContents contents = SetContents.Build(
            File(("test-mfg/a", Set("stated", Member("R1", "test", "Loose|", "L1")))),
            [Product("test-mfg/a")],
            [Paint("test/loose", "Loose", null, "L1")]);

        Assert.Equal(1, contents.Members);
        Assert.Equal("test/loose", contents.Sets["test-mfg/a"].Members[0].PaintId);
    }
}
