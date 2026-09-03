using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Output;

namespace WarHub.PaintCatalog.Tool.Tests.Output;

public class BrandArchiveWriterTests
{
    private static PaintRecord R(string name, string set = "Base", string? code = "0605",
        string hex = "#000000", string? ean = "5011921027330", string? firstSeen = "2026-07-07") => new()
    {
        Name = name, Category = "paint", Status = "current", Availability = "unknown",
        FirstSeen = firstSeen, ProductCode = code, Ean = ean, ImageUrl = null,
        Details = new PaintDetails
        {
            Set = set, R = 0, G = 0, B = 0, Hex = hex,
            VolumeMl = 12, Container = "pot", Type = "Base", Finish = "Matte",
        },
    };

    private static string NewTempDir() =>
        Path.Combine(Path.GetTempPath(), "warhub-paint-test", Guid.NewGuid().ToString("N"));

    [Fact]
    public async Task Write_QuotesNumericEanAndProductCode()
    {
        var archive = new BrandArchive
        {
            Brand = "Citadel",
            BrandSlug = "citadel-colour",
            Paints = [R("Abaddon Black")],
        };
        string dir = NewTempDir();
        try
        {
            await BrandArchiveWriter.WriteAsync(archive, dir, default);
            string yaml = await File.ReadAllTextAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));
            Assert.Contains("ean: '5011921027330'", yaml);
            Assert.Contains("productCode: '0605'", yaml);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task WriteThenLoad_RoundTrips()
    {
        var archive = new BrandArchive
        {
            Brand = "Citadel",
            BrandSlug = "citadel-colour",
            Paints = [R("Abaddon Black"), R("Mephiston Red", hex: "#7d1719", code: "0606", ean: "5011921027331")],
        };
        string dir = NewTempDir();
        try
        {
            await BrandArchiveWriter.WriteAsync(archive, dir, default);
            string filePath = Path.Combine(dir, "brands", "citadel-colour.yaml");

            IReadOnlyList<PaintRecord> loaded = await BrandArchiveWriter.LoadAsync(filePath, default);

            Assert.Equal(2, loaded.Count);
            Assert.Contains(loaded, p => p.Name == "Abaddon Black" && p.Ean == "5011921027330");
            Assert.Contains(loaded, p => p.Name == "Mephiston Red" && p.Ean == "5011921027331");
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    /// <summary>
    /// `role` is a scalar, so the IReadOnlyList trap below cannot bite it -- but every new
    /// top-level property still has to be proven to come back through LoadAsync, in its place
    /// beside `colourless`, before the regeneration stamps it on 8,521 records.
    /// </summary>
    [Fact]
    public async Task WriteThenLoad_RoundTripsRoleBesideColourless()
    {
        var archive = new BrandArchive
        {
            Brand = "Citadel",
            BrandSlug = "citadel-colour",
            Paints =
            [
                R("Abaddon Black") with { Role = "colour" },
                R("'Ardcoat", hex: "", code: "0607", ean: "5011921027332") with { Colourless = true, Role = "varnish" },
            ],
        };
        string dir = NewTempDir();
        try
        {
            await BrandArchiveWriter.WriteAsync(archive, dir, default);
            string filePath = Path.Combine(dir, "brands", "citadel-colour.yaml");
            string yaml = (await File.ReadAllTextAsync(filePath)).Replace("\r\n", "\n");
            Assert.Contains("  colourless: true\n  role: varnish\n  firstSeen:", yaml);
            Assert.Contains("  availability: unknown\n  role: colour\n  firstSeen:", yaml);

            IReadOnlyList<PaintRecord> loaded = await BrandArchiveWriter.LoadAsync(filePath, default);

            Assert.Equal("colour", loaded.Single(p => p.Name == "Abaddon Black").Role);
            PaintRecord varnish = loaded.Single(p => p.Name == "'Ardcoat");
            Assert.Equal("varnish", varnish.Role);
            Assert.True(varnish.Colourless);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task WriteThenLoad_RoundTripsListFields()
    {
        // The archive is read back on the NEXT run by the same serializer that wrote it. A list
        // property typed as IReadOnlyList<string> serializes fine and then makes LoadAsync throw
        // ("no node deserializer was able to deserialize the node into type IReadOnlyList<String>"),
        // i.e. the tool writes a file it can never read again. That bug was latent while no archive
        // carried a list; it fires the first run after one does.
        PaintRecord source = R("Hexwraith Flame", set: "Contrast", code: "99189960060", ean: null) with
        {
            AdditionalEans = ["5011921175291", "5011921175383"],
            Supersedes = ["Hexwraith Flame|Technical"],
            SupersededBy = null,
            PriceGbp = 3.30m,
            PriceCad = 7.25m,
        };
        var archive = new BrandArchive
        {
            Brand = "Citadel",
            BrandSlug = "citadel-colour",
            Paints = [source, R("Old Pot", set: "Technical", code: null) with { SupersededBy = "Hexwraith Flame|Contrast" }],
        };
        string dir = NewTempDir();
        try
        {
            await BrandArchiveWriter.WriteAsync(archive, dir, default);
            IReadOnlyList<PaintRecord> loaded =
                await BrandArchiveWriter.LoadAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"), default);

            PaintRecord back = loaded.Single(p => p.Name == "Hexwraith Flame");
            Assert.Equal(["5011921175291", "5011921175383"], back.AdditionalEans);
            Assert.Equal(["Hexwraith Flame|Technical"], back.Supersedes);
            Assert.Equal(3.30m, back.PriceGbp);
            Assert.Equal(7.25m, back.PriceCad);
            Assert.Null(back.PriceUsd);
            Assert.Equal("Hexwraith Flame|Contrast", loaded.Single(p => p.Name == "Old Pot").SupersededBy);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task WriteThenLoad_RoundTripsWeightG()
    {
        // Round-trip, not just write. `AdditionalEans` (see the docstring on PaintRecord) is the
        // standing reminder that this archive has shipped a shape it could not read back: the file
        // serialized fine and then blew up on the next LoadAsync, invisibly until a record actually
        // gained the key. `weightG` gains its first two records the next time the paint tool runs,
        // so it is proved here before that happens rather than after.
        //
        // Three claims at once: the value survives; a weight-sold record writes NO `volumeMl` and
        // NO `container` key at all (the shared serializer omits nulls, so absence is how the
        // archive says "not measured that way"); and an absent `weightG` still reads back null
        // rather than 0, which is what keeps the other 8,545 records byte-identical.
        PaintRecord tub = R("Foam Primer and Coat - Black 250gr", set: "Primer", code: "5723",
            hex: "", ean: "8435646530833") with
        {
            Details = new PaintDetails
            {
                Set = "Primer", R = 0, G = 0, B = 0, Hex = "",
                VolumeMl = null, WeightG = 250, Container = null, Type = "Standard", Finish = "Matte",
            },
        };
        var archive = new BrandArchive
        {
            Brand = "Green Stuff World",
            BrandSlug = "green-stuff-world",
            Paints = [tub, R("Matt Black Primer 60ml", set: "Primer", code: "1742", ean: "8436574501018")],
        };
        string dir = NewTempDir();
        try
        {
            await BrandArchiveWriter.WriteAsync(archive, dir, default);
            string filePath = Path.Combine(dir, "brands", "green-stuff-world.yaml");
            string yaml = await File.ReadAllTextAsync(filePath);

            Assert.Contains("weightG: 250", yaml);

            IReadOnlyList<PaintRecord> loaded = await BrandArchiveWriter.LoadAsync(filePath, default);

            PaintRecord back = loaded.Single(p => p.Name.StartsWith("Foam Primer"));
            Assert.Equal(250, back.Details.WeightG);
            Assert.Null(back.Details.VolumeMl);
            Assert.Null(back.Details.Container);

            PaintRecord bottle = loaded.Single(p => p.Name == "Matt Black Primer 60ml");
            Assert.Null(bottle.Details.WeightG);
            Assert.Equal(12, bottle.Details.VolumeMl);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task Load_MissingFile_ReturnsEmpty()
    {
        string dir = NewTempDir();
        try
        {
            string filePath = Path.Combine(dir, "brands", "does-not-exist.yaml");
            IReadOnlyList<PaintRecord> loaded = await BrandArchiveWriter.LoadAsync(filePath, default);
            Assert.Empty(loaded);
        }
        finally
        {
            if (Directory.Exists(dir))
            {
                Directory.Delete(dir, recursive: true);
            }
        }
    }

    [Fact]
    public async Task Write_SortsByIdentityKey()
    {
        // Inserted out of identity order: "Zandri Dust" sorts before "Abaddon Black" only by name,
        // but identity key is set|name|code|hex, so pick names that are clearly out of order.
        var archive = new BrandArchive
        {
            Brand = "Citadel",
            BrandSlug = "citadel-colour",
            Paints =
            [
                R("Zandri Dust", set: "Base", code: "0602", hex: "#7d6b4f", ean: "5011921027332"),
                R("Abaddon Black", set: "Base", code: "0605", hex: "#000000", ean: "5011921027330"),
            ],
        };
        string dir = NewTempDir();
        try
        {
            await BrandArchiveWriter.WriteAsync(archive, dir, default);
            string filePath = Path.Combine(dir, "brands", "citadel-colour.yaml");

            IReadOnlyList<PaintRecord> loaded = await BrandArchiveWriter.LoadAsync(filePath, default);

            Assert.Equal(2, loaded.Count);
            Assert.Equal("Abaddon Black", loaded[0].Name);
            Assert.Equal("Zandri Dust", loaded[1].Name);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }
}
