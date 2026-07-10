using WarHub.CatalogStore;
using WarHub.CatalogStore.Ledger;
using WarHub.PaintCatalog.Tool.Migration;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Output;

namespace WarHub.PaintCatalog.Tool.Tests.Migration;

public class PaintMigratorTests
{
    private static string NewTempDir() =>
        Path.Combine(Path.GetTempPath(), "warhub-paint-migrate", Guid.NewGuid().ToString("N"));

    private const string LegacyBrandYaml = """
        brand: Test Brand
        brandSlug: test-brand
        source: Arcturus5404/miniature-paints
        license: MIT
        generatedAt:
          dateTime: 2026-04-14T01:02:31.9464550
          utcDateTime: 2026-04-14T01:02:31.9464550Z
          year: 2026
        paintCount: 1
        paints:
        - name: Retributor Armour
          set: Base
          r: 138
          g: 110
          b: 62
          hex: '#8A6E3E'
          volumeMl: 12
          packaging: pot
          ean: '5011921027330'
          isDiscontinued: true
        """;

    private const string AlreadyMigratedBrandYaml = """
        brand: Test Brand
        brandSlug: test-brand
        source: Arcturus5404/miniature-paints
        license: MIT
        paints:
        - name: Abaddon Black
          category: paint
          status: current
          availability: unknown
          firstSeen: '2020-01-01'
          productCode: '0605'
          ean: '5011921027330'
          details:
            set: Base
            r: 0
            g: 0
            b: 0
            hex: '#000000'
            volumeMl: 12
            container: pot
            type: Base
            finish: Matte
        """;

    private static void SeedBrandFile(string dir, string yaml)
    {
        string brandsDir = Path.Combine(dir, "brands");
        Directory.CreateDirectory(brandsDir);
        File.WriteAllText(Path.Combine(brandsDir, "test-brand.yaml"), yaml);
    }

    [Fact]
    public async Task Migrate_MapsLegacyPaint_ToNewShape()
    {
        string dir = NewTempDir();
        try
        {
            SeedBrandFile(dir, LegacyBrandYaml);

            int result = await PaintMigrator.MigrateAsync(dir, "2026-07-06", default);

            Assert.Equal(0, result);
            string filePath = Path.Combine(dir, "brands", "test-brand.yaml");
            string yaml = await File.ReadAllTextAsync(filePath);

            Assert.DoesNotContain("generatedAt", yaml);
            Assert.DoesNotContain("paintCount", yaml);

            IReadOnlyList<PaintRecord> loaded = await BrandArchiveWriter.LoadAsync(filePath, default);
            PaintRecord record = Assert.Single(loaded);
            Assert.Equal("paint", record.Category);
            Assert.Equal("discontinued", record.Status);
            Assert.Equal("out_of_stock", record.Availability);
            Assert.Equal("pot", record.Details.Container);
            Assert.Equal("2026-07-06", record.FirstSeen);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task Migrate_IsIdempotent()
    {
        string dir = NewTempDir();
        try
        {
            SeedBrandFile(dir, LegacyBrandYaml);

            await PaintMigrator.MigrateAsync(dir, "2026-07-06", default);
            string filePath = Path.Combine(dir, "brands", "test-brand.yaml");
            string livenessPath = Path.Combine(dir, "_liveness.yaml");
            byte[] firstBytes = await File.ReadAllBytesAsync(filePath);
            byte[] firstLiveness = await File.ReadAllBytesAsync(livenessPath);

            // Different migrationDate on the second run must NOT change anything already stamped.
            await PaintMigrator.MigrateAsync(dir, "2099-01-01", default);
            byte[] secondBytes = await File.ReadAllBytesAsync(filePath);
            byte[] secondLiveness = await File.ReadAllBytesAsync(livenessPath);

            Assert.Equal(firstBytes, secondBytes);
            Assert.Equal(firstLiveness, secondLiveness);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task Migrate_SeedsLedger_OnlyIfAbsent()
    {
        string dir = NewTempDir();
        try
        {
            SeedBrandFile(dir, LegacyBrandYaml);

            // Pre-seed the ledger with the record's key, already flagged with a miss streak.
            string ledgerKey = "test-brand/base|retributor armour||#8a6e3e";
            var preseededLedger = new LivenessLedger();
            preseededLedger.Records[ledgerKey] = new LedgerRecord { LastSeen = "2020-01-01", MissStreak = 5 };
            string livenessPath = Path.Combine(dir, "_liveness.yaml");
            await LedgerStore.SaveAsync(livenessPath, preseededLedger, default);

            await PaintMigrator.MigrateAsync(dir, "2026-07-06", default);

            LivenessLedger ledger = await LedgerStore.LoadAsync(livenessPath, default);
            Assert.True(ledger.Records.TryGetValue(ledgerKey, out LedgerRecord? record));
            Assert.Equal(5, record!.MissStreak);
            Assert.Equal("2020-01-01", record.LastSeen);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task Migrate_BackfillsFirstSeen_OnlyWhenAbsent()
    {
        string dir = NewTempDir();
        try
        {
            SeedBrandFile(dir, AlreadyMigratedBrandYaml);

            await PaintMigrator.MigrateAsync(dir, "2026-07-06", default);

            string filePath = Path.Combine(dir, "brands", "test-brand.yaml");
            IReadOnlyList<PaintRecord> loaded = await BrandArchiveWriter.LoadAsync(filePath, default);
            PaintRecord record = Assert.Single(loaded);

            Assert.Equal("2020-01-01", record.FirstSeen);
            Assert.Equal("current", record.Status);
            Assert.Equal("unknown", record.Availability);
            Assert.Equal("pot", record.Details.Container);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }
}
