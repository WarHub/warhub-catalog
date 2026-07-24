using System.Security.Cryptography;
using System.Text.Json;

namespace WarHub.Catalog.Publish.Tests;

public sealed class PublishTests(PublishFixture fx) : IClassFixture<PublishFixture>
{
    private JsonElement Doc(string relPath) => JsonDocument.Parse(fx.ReadDist(relPath)).RootElement;

    [Fact]
    public void Publishes_expected_counts()
    {
        Assert.Equal(2, fx.Result.Products);
        Assert.Equal(4, fx.Result.Paints);
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
        Assert.Equal(2, pIndex.GetProperty("total").GetInt32());
        Assert.Equal(2, pSum);

        JsonElement xIndex = Doc("paints/index.json");
        int xSum = xIndex.GetProperty("partitions").EnumerateArray().Sum(e => e.GetProperty("records").GetInt32());
        Assert.Equal(4, xIndex.GetProperty("total").GetInt32());
        Assert.Equal(4, xSum);
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
        foreach (string name in new[] { "manifest", "product-catalog", "paint-catalog", "index" })
        {
            Assert.True(File.Exists(Path.Combine(fx.Dist, "schema", $"{name}.json")), $"schema/{name}.json missing");
        }
    }
}
