using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace WarHub.Catalog.Publish.Tests;

public sealed class PublishTests(PublishFixture fx) : IClassFixture<PublishFixture>
{
    private JsonElement Doc(string relPath) => JsonDocument.Parse(fx.ReadDist(relPath)).RootElement;

    [Fact]
    public void Publishes_expected_counts()
    {
        Assert.Equal(3, fx.Result.Products);
        Assert.Equal(8, fx.Result.Paints);  // 7 + the weight-sold Weathering Powder
    }

    [Fact]
    public void Paint_image_url_is_published()
    {
        // 3,864 of the archive's paints carry an imageUrl and PaintSource has always parsed it,
        // but PaintRecord had no such property, so every one of them was dropped at publish.
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        JsonElement black = paints.Single(p => p.GetProperty("id").GetString() == "vallejo/black");
        JsonElement abaddon = paints.Single(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");

        Assert.Equal("https://img.example/vallejo-black.jpg", black.GetProperty("imageUrl").GetString());
        Assert.False(abaddon.TryGetProperty("imageUrl", out _));   // omitted, never null or ""
    }

    [Fact]
    public void Paint_prices_are_published_and_omitted_when_absent()
    {
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        JsonElement black = paints.Single(p => p.GetProperty("id").GetString() == "vallejo/black");
        JsonElement abaddon = paints.Single(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");

        Assert.Equal(2.75m, black.GetProperty("priceGbp").GetDecimal());
        Assert.Equal(3.99m, black.GetProperty("priceUsd").GetDecimal());
        Assert.Equal(3.20m, black.GetProperty("priceEur").GetDecimal());
        Assert.Equal(4.50m, black.GetProperty("priceCad").GetDecimal());
        foreach (string key in new[] { "priceGbp", "priceUsd", "priceEur", "priceCad" })
        {
            Assert.False(abaddon.TryGetProperty(key, out _));
        }
        // Availability deliberately does not follow price across from the trade evidence.
        Assert.Equal("unknown", black.GetProperty("availability").GetString());
    }

    [Fact]
    public void Paint_lineage_publishes_both_directions_as_ids()
    {
        // A reformulation keeps BOTH records: the retired Technical pot and the Contrast
        // replacement are separate identities (set is part of the identity key), linked rather
        // than folded, so a pot bought years ago still resolves and says what replaced it.
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        var ids = paints.Select(p => p.GetProperty("id").GetString()).ToHashSet();

        JsonElement contrast = paints.Single(p =>
            p.GetProperty("name").GetString() == "Hexwraith Flame" &&
            p.GetProperty("range").GetString() == "Contrast");
        JsonElement technical = paints.Single(p =>
            p.GetProperty("name").GetString() == "Hexwraith Flame" &&
            p.GetProperty("range").GetString() == "Technical");

        string contrastId = contrast.GetProperty("id").GetString()!;
        string technicalId = technical.GetProperty("id").GetString()!;
        Assert.NotEqual(contrastId, technicalId);

        Assert.Equal(contrastId, technical.GetProperty("supersededBy").GetString());
        Assert.Equal(technicalId, Assert.Single(contrast.GetProperty("supersedes")
            .EnumerateArray().Select(e => e.GetString())));
        Assert.Contains(technical.GetProperty("supersededBy").GetString(), ids);

        // The relation is NOT encoded in status: the retired record keeps whatever the evidence
        // says, so a consumer filtering on status is unaffected.
        Assert.Equal("discontinued", technical.GetProperty("status").GetString());
        Assert.False(technical.TryGetProperty("supersedes", out _));
        Assert.False(contrast.TryGetProperty("supersededBy", out _));
    }

    [Fact]
    public void Paint_lineage_that_resolves_to_nothing_is_not_published()
    {
        // An unresolvable upstream key must yield NO property rather than a dangling id: the
        // published values are paint ids and consumers dereference them.
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        JsonElement ghost = paints.Single(p => p.GetProperty("name").GetString() == "Ghost Ash");

        Assert.False(ghost.TryGetProperty("supersededBy", out _));
        Assert.False(ghost.TryGetProperty("supersedes", out _));
    }

    [Fact]
    public void Every_lineage_id_resolves_to_a_paint()
    {
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        var ids = paints.Select(p => p.GetProperty("id").GetString()).ToHashSet();
        foreach (JsonElement p in paints)
        {
            if (p.TryGetProperty("supersededBy", out JsonElement by))
                Assert.Contains(by.GetString(), ids);
            if (p.TryGetProperty("supersedes", out JsonElement prior))
                foreach (JsonElement e in prior.EnumerateArray())
                    Assert.Contains(e.GetString(), ids);
        }
    }

    [Fact]
    public void Product_ean_is_optional()
    {
        JsonElement products = Doc("products.json").GetProperty("products");
        JsonElement alpha = products.EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Alpha Box");
        JsonElement beta = products.EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Beta Box");

        Assert.Equal("5011921142361", alpha.GetProperty("ean").GetString());
        Assert.Equal("provisional", alpha.GetProperty("eanConfidence").GetString());
        Assert.False(beta.TryGetProperty("ean", out _));       // omitted when null
        Assert.Equal("SKUB", beta.GetProperty("productCode").GetString()); // falls back to sku
    }

    [Fact]
    public void Product_quantity_flows_from_data()
    {
        JsonElement products = Doc("products.json").GetProperty("products");
        JsonElement alpha = products.EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Alpha Box");
        JsonElement beta = products.EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Beta Box");

        Assert.Equal(2, alpha.GetProperty("quantity").GetInt32());
        Assert.Equal(1, beta.GetProperty("quantity").GetInt32()); // no quantity in source -> fallback to 1
    }

    [Fact]
    public void Product_surfaces_category_status_availability()
    {
        JsonElement products = Doc("products.json").GetProperty("products");
        JsonElement alpha = products.EnumerateArray().First(p => p.GetProperty("name").GetString() == "Alpha Box");
        JsonElement beta = products.EnumerateArray().First(p => p.GetProperty("name").GetString() == "Beta Box");
        Assert.Equal("miniatures", alpha.GetProperty("category").GetString());
        Assert.Equal("current", alpha.GetProperty("status").GetString());
        Assert.Equal("in_stock", alpha.GetProperty("availability").GetString());
        Assert.Equal("discontinued", beta.GetProperty("status").GetString());
        Assert.Equal("out_of_stock", beta.GetProperty("availability").GetString());
        // The role axis: present on the hobby supply that carries one, absent -- not null -- on a
        // miniature, and its archive-side basis never crosses into the published shape.
        JsonElement gamma = products.EnumerateArray().First(p => p.GetProperty("name").GetString() == "Gamma Powder (Pack of 6)");
        Assert.Equal("pigment", gamma.GetProperty("role").GetString());
        Assert.False(alpha.TryGetProperty("role", out _));
        Assert.False(gamma.TryGetProperty("roleBasis", out _));
    }

    [Fact]
    public void Paint_ids_and_range_map_from_set()
    {
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        JsonElement abaddon = paints.Single(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");
        Assert.Equal("Base", abaddon.GetProperty("range").GetString());
        Assert.Equal("#231f20", abaddon.GetProperty("hex").GetString());     // normalized lowercase
        Assert.Contains(paints, p => p.GetProperty("id").GetString() == "vallejo/black");
    }

    [Fact]
    public void Paint_without_colour_publishes_no_hex_property()
    {
        // Harvested additions can be colour-less until swatch extraction covers them; they
        // must publish with the hex property OMITTED (not "" — the schema pattern applies
        // whenever the property is present, and "" broke the 2026-07-24 release).
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        JsonElement oldCopper = paints.Single(p => p.GetProperty("id").GetString() == "vallejo/old-copper");
        Assert.False(oldCopper.TryGetProperty("hex", out _));
    }

    [Fact]
    public void Paint_role_is_published_right_after_category()
    {
        // `category` is the constant `paint` for everything a maker's chart lists, so `role` is
        // the key that tells a pigment jar from a colour. It reaches the publisher through
        // PaintSource.PaintYaml, whose deserializer ignores unmatched properties -- so a dropped
        // property would publish nothing and fail no other test, the hop weightG is guarded
        // against below.
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        JsonElement abaddon = paints.Single(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");
        JsonElement powder = paints.Single(p => p.GetProperty("id").GetString() == "citadel/weathering-powder-rust");
        Assert.Equal("colour", abaddon.GetProperty("role").GetString());
        Assert.Equal("pigment", powder.GetProperty("role").GetString());

        // Emitted right after `category`: the other half of the same question.
        string[] keys = [.. abaddon.EnumerateObject().Select(p => p.Name)];
        Assert.Equal(Array.IndexOf(keys, "category") + 1, Array.IndexOf(keys, "role"));
    }

    [Fact]
    public void Paint_surfaces_category_status_volume_container()
    {
        JsonElement paints = Doc("paints.json").GetProperty("paints");
        JsonElement abaddon = paints.EnumerateArray().First(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");
        Assert.Equal("paint", abaddon.GetProperty("category").GetString());
        Assert.Equal("current", abaddon.GetProperty("status").GetString());
        Assert.Equal("unknown", abaddon.GetProperty("availability").GetString());
        Assert.Equal(12, abaddon.GetProperty("volumeMl").GetInt32());
        Assert.Equal("pot", abaddon.GetProperty("container").GetString());
        // discontinued paints are still published (include-everything).
        Assert.Contains(paints.EnumerateArray(), p => p.GetProperty("status").GetString() == "discontinued");

        // A weight-sold paint publishes its MASS and no volume -- the hop most likely to lose it
        // silently. `PaintSource.PaintDetailsYaml` is read through a deserializer built with
        // `.IgnoreUnmatchedProperties()`, so deleting that one property would drop every
        // `weightG:` in the archive from the published catalogue with no error and no other
        // failing test. Before this assertion, the only `WeightG` in this whole test project was a
        // `null` that existed because a positional record gained a parameter.
        JsonElement powder = paints.EnumerateArray()
            .First(p => p.GetProperty("id").GetString() == "citadel/weathering-powder-rust");
        Assert.Equal(35, powder.GetProperty("weightG").GetInt32());
        Assert.Equal("jar", powder.GetProperty("container").GetString());
        Assert.False(powder.TryGetProperty("volumeMl", out _),
            "a weight-sold paint must not publish a volume it does not have");
    }

    [Fact]
    public void Equivalents_are_bidirectional()
    {
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        JsonElement abaddon = paints.Single(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");
        JsonElement black = paints.Single(p => p.GetProperty("id").GetString() == "vallejo/black");

        Assert.Contains(abaddon.GetProperty("equivalents").EnumerateArray(),
            e => e.GetProperty("id").GetString() == "vallejo/black" && e.GetProperty("deltaE").GetDouble() == 1.1);
        Assert.Contains(black.GetProperty("equivalents").EnumerateArray(),
            e => e.GetProperty("id").GetString() == "citadel/abaddon-black" && e.GetProperty("deltaE").GetDouble() == 1.1);
    }

    [Fact]
    public void Every_equivalent_id_resolves_to_a_paint()
    {
        var paints = Doc("paints.json").GetProperty("paints").EnumerateArray().ToList();
        var ids = paints.Select(p => p.GetProperty("id").GetString()).ToHashSet();
        foreach (JsonElement p in paints)
        {
            foreach (JsonElement e in p.GetProperty("equivalents").EnumerateArray())
            {
                Assert.Contains(e.GetProperty("id").GetString(), ids);
            }
        }
    }

    [Fact]
    public void Partitions_sum_to_consolidated()
    {
        JsonElement pIndex = Doc("products/index.json");
        int pSum = pIndex.GetProperty("partitions").EnumerateArray().Sum(e => e.GetProperty("records").GetInt32());
        Assert.Equal(3, pIndex.GetProperty("total").GetInt32());
        Assert.Equal(3, pSum);

        JsonElement xIndex = Doc("paints/index.json");
        int xSum = xIndex.GetProperty("partitions").EnumerateArray().Sum(e => e.GetProperty("records").GetInt32());
        Assert.Equal(8, xIndex.GetProperty("total").GetInt32());
        Assert.Equal(8, xSum);
    }

    [Fact]
    public void Manifest_files_match_disk()
    {
        JsonElement manifest = Doc("manifest.json");
        Assert.Equal("manifest", manifest.GetProperty("kind").GetString());
        Assert.Equal("v2026.7.4", manifest.GetProperty("source").GetProperty("release").GetProperty("tag").GetString());

        foreach (JsonElement f in manifest.GetProperty("files").EnumerateArray())
        {
            string relPath = f.GetProperty("path").GetString()!;
            byte[] bytes = File.ReadAllBytes(Path.Combine(fx.Dist, relPath.Replace('/', Path.DirectorySeparatorChar)));
            Assert.Equal(f.GetProperty("bytes").GetInt64(), bytes.Length);
            Assert.Equal(f.GetProperty("sha256").GetString(), Convert.ToHexStringLower(SHA256.HashData(bytes)));
        }
    }

    [Fact]
    public void Query_database_holds_one_row_per_record_of_each_json_document()
    {
        JsonElement barcodes = Doc("barcodes.json").GetProperty("barcodes");
        int barcodeLinks = barcodes.EnumerateObject().Sum(b => b.Value.GetArrayLength());

        using var db = OpenQueryDatabase();
        Assert.Equal(Doc("products.json").GetProperty("products").GetArrayLength(), Count(db, "SELECT count(*) FROM products"));
        Assert.Equal(Doc("paints.json").GetProperty("paints").GetArrayLength(), Count(db, "SELECT count(*) FROM paints"));
        Assert.Equal(barcodeLinks, Count(db, "SELECT count(*) FROM barcodes"));
        Assert.Equal(barcodes.EnumerateObject().Count(), Count(db, "SELECT count(DISTINCT barcode) FROM barcodes"));
        // The seam the barcode rows exist for: the fixture's two barcodes held by both catalogs.
        Assert.Equal(Doc("manifest.json").GetProperty("counts").GetProperty("crossCatalogBarcodes").GetInt32(),
            Count(db, "SELECT count(*) FROM (SELECT barcode FROM barcodes GROUP BY barcode HAVING count(DISTINCT catalog) = 2)"));
    }

    [Fact]
    public void Query_database_columns_carry_the_published_values()
    {
        // Arrays are stored as the JSON the documents carry, and read back through json_each.
        using var db = OpenQueryDatabase();
        using var cmd = db.CreateCommand();
        cmd.CommandText = """
            SELECT p.ean, p.quantity, j.value
            FROM products p, json_each(p.paintIds) j
            WHERE p.id = 'test-mfg/alpha'
            ORDER BY j.value
            """;
        using var reader = cmd.ExecuteReader();
        var paintIds = new List<string>();
        while (reader.Read())
        {
            Assert.Equal("5011921142361", reader.GetString(0));
            Assert.Equal(2, reader.GetInt32(1));
            paintIds.Add(reader.GetString(2));
        }
        Assert.Equal(["citadel/abaddon-black", "vallejo/black"], paintIds);
        // An absent JSON property is NULL, not an empty string.
        Assert.Equal(1, Count(db, "SELECT count(*) FROM products WHERE id = 'test-mfg/beta' AND ean IS NULL"));
    }

    [Fact]
    public void Query_database_is_listed_in_the_manifest_and_is_reproducible()
    {
        JsonElement entry = Doc("manifest.json").GetProperty("files").EnumerateArray()
            .Single(f => f.GetProperty("path").GetString() == "catalog.sqlite");
        Assert.Equal("sqlite", entry.GetProperty("kind").GetString());

        // A second publish of the same input into a fresh directory writes the same bytes, so the
        // manifest's sha256 names the content rather than the run.
        string again = Path.Combine(fx.Root, "dist-again");
        Publisher.Run(new PublishOptions(
            Path.Combine(fx.Root, "data", "catalog"), Path.Combine(fx.Root, "data", "paints"), again,
            Path.Combine(AppContext.BaseDirectory, "schema"), PublishFixture.Provenance));
        Assert.Equal(entry.GetProperty("sha256").GetString(),
            Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Path.Combine(again, "catalog.sqlite")))));
    }

    private SqliteConnection OpenQueryDatabase()
    {
        var db = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = Path.Combine(fx.Dist, "catalog.sqlite"),
            Mode = SqliteOpenMode.ReadOnly,
            Pooling = false,
        }.ToString());
        db.Open();
        return db;
    }

    private static int Count(SqliteConnection db, string sql)
    {
        using var cmd = db.CreateCommand();
        cmd.CommandText = sql;
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    [Fact]
    public void Partition_documents_carry_partition_metadata_and_page_url()
    {
        JsonElement doc = Doc("products/by-system/test-system.json");
        Assert.Equal("product-catalog-partition", doc.GetProperty("kind").GetString());
        Assert.Equal("test-system", doc.GetProperty("partition").GetProperty("key").GetString());
        Assert.Equal("Test System", doc.GetProperty("partition").GetProperty("label").GetString());
        Assert.Equal("https://warhub.github.io/warhub-catalog/products/by-system/test-system.json",
            doc.GetProperty("source").GetProperty("pageUrl").GetString());
    }

    [Fact]
    public void Schemas_are_published()
    {
        foreach (string name in new[]
                 { "manifest", "product-catalog", "paint-catalog", "index", "barcode-index", "set-contents" })
        {
            Assert.True(File.Exists(Path.Combine(fx.Dist, "schema", $"{name}.json")), $"schema/{name}.json missing");
        }
    }
}
