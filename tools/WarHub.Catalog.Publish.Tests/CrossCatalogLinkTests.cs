using System.Text.Json;
using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// The seam between the two catalogs one publish emits. A Citadel pot is a SKU in the product
/// catalog and a colour in the paint catalog, joined only by the barcode printed on it; these
/// cover the published join (<c>barcodes.json</c>) and the links stamped onto the records.
/// </summary>
public sealed class CrossCatalogLinkTests(PublishFixture fx) : IClassFixture<PublishFixture>
{
    private JsonElement Doc(string relPath) => JsonDocument.Parse(fx.ReadDist(relPath)).RootElement;

    private JsonElement Product(string name) =>
        Doc("products.json").GetProperty("products").EnumerateArray()
            .Single(p => p.GetProperty("name").GetString() == name);

    private JsonElement Paint(string id) =>
        Doc("paints.json").GetProperty("paints").EnumerateArray()
            .Single(p => p.GetProperty("id").GetString() == id);

    private static string[] Strings(JsonElement array) =>
        [.. array.EnumerateArray().Select(e => e.GetString()!)];

    [Fact]
    public void Barcode_index_carries_the_same_self_describing_envelope_as_every_other_document()
    {
        JsonElement doc = Doc("barcodes.json");

        Assert.Equal("1.1", doc.GetProperty("schemaVersion").GetString());
        Assert.Equal("barcode-index", doc.GetProperty("kind").GetString());
        Assert.Equal("2026.7.4", doc.GetProperty("version").GetString());
        Assert.Equal("2026-07-04T00:00:00Z", doc.GetProperty("generatedAt").GetString());
        Assert.Equal("deadbeef", doc.GetProperty("gitCommit").GetString());
        Assert.Equal("WarHub/warhub-catalog", doc.GetProperty("source").GetProperty("repo").GetString());
        Assert.Equal("https://warhub.github.io/warhub-catalog/barcodes.json",
            doc.GetProperty("source").GetProperty("pageUrl").GetString());
    }

    [Fact]
    public void Barcode_index_maps_every_barcode_in_either_catalog_to_the_records_carrying_it()
    {
        JsonElement barcodes = Doc("barcodes.json").GetProperty("barcodes");

        // Three distinct barcodes across both catalogs; the key is the barcode string itself,
        // verbatim -- no camelCasing, no normalization.
        Assert.Equal(3, barcodes.EnumerateObject().Count());

        static (string Catalog, string Id)[] Refs(JsonElement entry) =>
            [.. entry.EnumerateArray()
                .Select(r => (r.GetProperty("catalog").GetString()!, r.GetProperty("id").GetString()!))];

        Assert.Equal(
            [("paint", "citadel/abaddon-black"), ("product", "test-mfg/alpha")],
            Refs(barcodes.GetProperty("5011921142361")));
        // reached via the product's additionalEans, not its primary ean
        Assert.Equal(
            [("paint", "vallejo/black"), ("product", "test-mfg/alpha")],
            Refs(barcodes.GetProperty("8429551724838")));
        // paint-only barcode: still indexed, but with a single holder
        Assert.Equal(
            [("paint", "citadel/mephiston-red")],
            Refs(barcodes.GetProperty("5011921142378")));
    }

    [Fact]
    public void Barcode_index_counts_how_many_barcodes_are_held_by_both_catalogs()
    {
        // The whole point of the document: before it, nothing in the pipeline detected the overlap.
        JsonElement counts = Doc("barcodes.json").GetProperty("counts");

        Assert.Equal(3, counts.GetProperty("barcodes").GetInt32());
        Assert.Equal(2, counts.GetProperty("productBarcodes").GetInt32());
        Assert.Equal(3, counts.GetProperty("paintBarcodes").GetInt32());
        Assert.Equal(2, counts.GetProperty("crossCatalog").GetInt32());
        Assert.Equal(5, counts.GetProperty("references").GetInt32());

        Assert.Equal(3, fx.Result.Barcodes);
        Assert.Equal(2, fx.Result.CrossCatalogBarcodes);
    }

    [Fact]
    public void Barcode_index_is_manifested_and_validated_like_every_other_document()
    {
        JsonElement manifest = Doc("manifest.json");
        JsonElement entry = manifest.GetProperty("files").EnumerateArray()
            .Single(f => f.GetProperty("path").GetString() == "barcodes.json");

        Assert.Equal("barcode-index", entry.GetProperty("kind").GetString());
        Assert.Equal(3, entry.GetProperty("records").GetInt32());
        Assert.Equal(3, manifest.GetProperty("counts").GetProperty("barcodes").GetInt32());
        Assert.Equal(2, manifest.GetProperty("counts").GetProperty("crossCatalogBarcodes").GetInt32());
        Assert.True(File.Exists(Path.Combine(fx.Dist, "schema", "barcode-index.json")));
    }

    [Fact]
    public void Barcode_shared_by_both_catalogs_links_both_records_to_each_other()
    {
        // alpha shares 5011921142361 with abaddon-black and 8429551724838 with vallejo/black,
        // so it names BOTH paints -- one SKU, two colours, which is why the field is plural.
        Assert.Equal(
            ["citadel/abaddon-black", "vallejo/black"],
            Strings(Product("Alpha Box").GetProperty("paintIds")));

        // ...and both paints name it back.
        Assert.Equal(["test-mfg/alpha"], Strings(Paint("citadel/abaddon-black").GetProperty("productIds")));
        Assert.Equal(["test-mfg/alpha"], Strings(Paint("vallejo/black").GetProperty("productIds")));
    }

    [Fact]
    public void Single_catalog_barcode_produces_no_cross_link()
    {
        // mephiston-red has a barcode, it is in the index, and no product carries it -- so the
        // record gets no productIds at all. A barcode is not evidence of a link by itself.
        JsonElement mephiston = Paint("citadel/mephiston-red");
        Assert.Equal("5011921142378", mephiston.GetProperty("ean").GetString());
        Assert.False(mephiston.TryGetProperty("productIds", out _));
    }

    [Fact]
    public void Link_fields_are_omitted_not_empty_arrays()
    {
        // Same contract as additionalEans / supersedes: null -> omitted, never published as [].
        Assert.False(Product("Beta Box").TryGetProperty("paintIds", out _));  // carries no barcode at all
        Assert.False(Paint("vallejo/old-copper").TryGetProperty("productIds", out _));
        Assert.False(Paint("citadel/mephiston-red").TryGetProperty("productIds", out _));

        // and the raw JSON never contains an empty link array anywhere
        Assert.DoesNotContain("\"paintIds\":[]", fx.ReadDist("products.json"), StringComparison.Ordinal);
        Assert.DoesNotContain("\"productIds\":[]", fx.ReadDist("paints.json"), StringComparison.Ordinal);
    }

    [Fact]
    public void Links_are_identical_in_the_consolidated_document_and_in_the_partitions()
    {
        // The link pass runs before anything is written, so no document can hold a stale,
        // unlinked copy of a record that another document shows linked.
        JsonElement partitioned = Doc("products/by-system/test-system.json").GetProperty("products")
            .EnumerateArray().Single(p => p.GetProperty("name").GetString() == "Alpha Box");
        Assert.Equal(
            Strings(Product("Alpha Box").GetProperty("paintIds")),
            Strings(partitioned.GetProperty("paintIds")));

        JsonElement brandPartitioned = Doc("paints/by-brand/citadel.json").GetProperty("paints")
            .EnumerateArray().Single(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");
        Assert.Equal(
            Strings(Paint("citadel/abaddon-black").GetProperty("productIds")),
            Strings(brandPartitioned.GetProperty("productIds")));
    }
}

/// <summary>
/// Direct coverage of the join itself, on hand-built records -- the cases real data has only a
/// couple of instances of, or none yet.
/// </summary>
public sealed class BarcodeIndexTests
{
    private static ProductRecord Product(string id, string? ean, params string[] additional) => new()
    {
        Id = id,
        Manufacturer = id.Split('/')[0],
        Name = id,
        Category = "miniatures",
        Status = "current",
        Availability = "unknown",
        Ean = ean,
        AdditionalEans = additional.Length > 0 ? additional : null,
    };

    private static PaintRecord Paint(string id, string? ean, params string[] additional) => new(
        Id: id,
        Brand: id.Split('/')[0],
        Category: "paint",
        Range: null,
        Name: id,
        Hex: null,
        Type: null,
        Finish: null,
        VolumeMl: null,
        WeightG: null,
        Container: null,
        ProductCode: null,
        Ean: ean,
        AdditionalEans: additional.Length > 0 ? additional : null,
        ImageUrl: null,
        PriceGbp: null,
        PriceUsd: null,
        PriceEur: null,
        PriceCad: null,
        Status: "current",
        Availability: "unknown",
        Supersedes: null,
        SupersededBy: null,
        Equivalents: []);

    [Fact]
    public void Two_records_in_the_same_catalog_sharing_a_barcode_are_both_reported_not_adjudicated()
    {
        // Measured on real data: 2 barcodes are held by two records of the SAME catalog (one
        // product pair, one paint pair). Deduplicating them is the resolver's job upstream; the
        // index reports what is published and must not choke on it.
        BarcodeIndex index = BarcodeIndex.Build(
            [Product("warlord-games/402215810", "5011921171835"), Product("games-workshop/99070117012", "5011921171835")],
            [Paint("vallejo/viking-grey", "8429551724838"), Paint("vallejo/viking-grey-2", "8429551724838")]);

        Assert.Equal(2, index.Total);
        Assert.Equal(0, index.CrossCatalog);      // neither barcode crosses the seam
        Assert.Equal(4, index.References);
        Assert.Equal(
            [("product", "games-workshop/99070117012"), ("product", "warlord-games/402215810")],
            index.Barcodes["5011921171835"].Select(r => (r.Catalog, r.Id)));
        Assert.Empty(index.PaintIdsByProductId);
        Assert.Empty(index.ProductIdsByPaintId);
    }

    [Fact]
    public void A_barcode_on_many_records_of_both_catalogs_fans_out_to_every_counterpart()
    {
        BarcodeIndex index = BarcodeIndex.Build(
            [Product("mfg/one", "5011921000001"), Product("mfg/two", "5011921000001")],
            [Paint("brand/red", "5011921000001"), Paint("brand/red-2", "5011921000001")]);

        Assert.Equal(1, index.CrossCatalog);
        Assert.Equal(["brand/red", "brand/red-2"], index.PaintIdsByProductId["mfg/one"]);
        Assert.Equal(["brand/red", "brand/red-2"], index.PaintIdsByProductId["mfg/two"]);
        Assert.Equal(["mfg/one", "mfg/two"], index.ProductIdsByPaintId["brand/red"]);
        Assert.Equal(["mfg/one", "mfg/two"], index.ProductIdsByPaintId["brand/red-2"]);
    }

    [Fact]
    public void A_record_repeating_its_own_barcode_is_one_holder_not_two()
    {
        BarcodeIndex index = BarcodeIndex.Build(
            [Product("mfg/one", "5011921000001", "5011921000001", "5011921000002")],
            [Paint("brand/red", "5011921000001")]);

        Assert.Equal(2, index.Total);
        Assert.Equal(3, index.References);   // 000001 -> product + paint, 000002 -> product
        Assert.Single(index.Barcodes["5011921000001"], r => r.Catalog == "product");
    }

    [Fact]
    public void Blank_barcodes_are_not_indexed()
    {
        BarcodeIndex index = BarcodeIndex.Build(
            [Product("mfg/none", null), Product("mfg/blank", "  ")],
            [Paint("brand/none", null)]);

        Assert.Equal(0, index.Total);
        Assert.Equal(0, index.CrossCatalog);
    }

    [Fact]
    public void Barcodes_are_matched_verbatim_with_no_invented_normalization()
    {
        // A 12-digit UPC and its 13-digit zero-padded EAN are DIFFERENT keys here. The pipeline
        // does not normalize between them anywhere else, so neither does this -- a mismatch is a
        // data bug to fix upstream, not one to paper over at publish time.
        BarcodeIndex index = BarcodeIndex.Build(
            [Product("mfg/one", "011921000001")],
            [Paint("brand/red", "0011921000001")]);

        Assert.Equal(2, index.Total);
        Assert.Equal(0, index.CrossCatalog);
    }
}
