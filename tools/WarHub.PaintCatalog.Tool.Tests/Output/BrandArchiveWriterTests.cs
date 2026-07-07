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
