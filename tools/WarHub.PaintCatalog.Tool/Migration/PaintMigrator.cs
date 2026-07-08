using WarHub.CatalogStore;
using WarHub.CatalogStore.Ledger;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Output;
using WarHub.PaintCatalog.Tool.Reconcile;

namespace WarHub.PaintCatalog.Tool.Migration;

/// <summary>
/// One-time, idempotent migration of legacy <c>data/paints/brands/*.yaml</c> files
/// (flat color/physical fields, exploded <c>generatedAt</c>, <c>paintCount</c>,
/// <c>isDiscontinued</c>, <c>packaging</c>) into the new archival <see cref="PaintRecord"/>
/// shape, and seeds the <c>_liveness.yaml</c> ledger. Backfills <c>firstSeen</c> only when
/// absent and, for paints that are already migrated, reconstructs the record verbatim from
/// the new fields (never re-deriving status/availability from <c>isDiscontinued</c>), so a
/// second run over its own output is a byte-for-byte no-op.
/// </summary>
public static class PaintMigrator
{
    private static readonly PaintRecordAdapter Adapter = new();

    // Legacy shape tolerant of both the old flat fields and the new fields, so a re-run
    // over already-migrated output reads its own output instead of re-deriving values.
    private sealed record LegacyBrand
    {
        public string Brand { get; init; } = "";
        public string BrandSlug { get; init; } = "";
        public string Source { get; init; } = "Arcturus5404/miniature-paints";
        public string License { get; init; } = "MIT";
        public List<LegacyPaint> Paints { get; init; } = new();
    }

    private sealed record LegacyPaint
    {
        public string Name { get; init; } = "";
        public string? ProductCode { get; init; }
        public string? Ean { get; init; }
        public string? ImageUrl { get; init; }

        // Flat legacy color/physical fields.
        public string? Set { get; init; }
        public int R { get; init; }
        public int G { get; init; }
        public int B { get; init; }
        public string? Hex { get; init; }
        public int? VolumeMl { get; init; }
        public string? Packaging { get; init; }
        public bool IsDiscontinued { get; init; }
        public string? Type { get; init; }
        public string? Finish { get; init; }

        // New-shape fields, present only once a paint has already been migrated.
        public string? Category { get; init; }
        public string? Status { get; init; }
        public string? Availability { get; init; }
        public string? FirstSeen { get; init; }
        public LegacyDetails? Details { get; init; }
    }

    private sealed record LegacyDetails
    {
        public string? Set { get; init; }
        public int R { get; init; }
        public int G { get; init; }
        public int B { get; init; }
        public string? Hex { get; init; }
        public int? VolumeMl { get; init; }
        public string? Container { get; init; }
        public string? Type { get; init; }
        public string? Finish { get; init; }
    }

    public static async Task<int> MigrateAsync(string dataDir, string migrationDate, CancellationToken ct)
    {
        string brandsDir = Path.Combine(dataDir, "brands");
        if (!Directory.Exists(brandsDir))
            return 0;

        var deserializer = CatalogSerializer.CreateDeserializer();
        string ledgerPath = Path.Combine(dataDir, "_liveness.yaml");
        LivenessLedger ledger = await LedgerStore.LoadAsync(ledgerPath, ct);

        foreach (string file in Directory.GetFiles(brandsDir, "*.yaml").OrderBy(f => f, StringComparer.Ordinal))
        {
            ct.ThrowIfCancellationRequested();
            LegacyBrand? legacy = deserializer.Deserialize<LegacyBrand>(await File.ReadAllTextAsync(file, ct));
            if (legacy is null)
                continue;

            var records = legacy.Paints
                .Select(lp => ToRecord(lp, migrationDate))
                .OrderBy(r => Adapter.IdentityKey(r), StringComparer.Ordinal)
                .ToList();

            foreach (PaintRecord record in records)
            {
                string ledgerKey = $"{legacy.BrandSlug}/{Adapter.IdentityKey(record)}";
                if (!ledger.Records.ContainsKey(ledgerKey))
                    ledger.Records[ledgerKey] = new LedgerRecord { LastSeen = migrationDate, MissStreak = 0 };
            }

            var archive = new BrandArchive
            {
                Brand = legacy.Brand,
                BrandSlug = legacy.BrandSlug,
                Source = legacy.Source,
                License = legacy.License,
                Paints = records,
            };

            await BrandArchiveWriter.WriteAsync(archive, dataDir, ct);
        }

        await LedgerStore.SaveAsync(ledgerPath, ledger, ct);
        return 0;
    }

    private static PaintRecord ToRecord(LegacyPaint lp, string migrationDate)
    {
        // Legacy flat paints never carried firstSeen, so this only ever backfills the
        // not-yet-migrated case; already-migrated paints keep their existing date.
        string firstSeen = string.IsNullOrWhiteSpace(lp.FirstSeen) ? migrationDate : lp.FirstSeen!;

        // Already migrated: reconstruct verbatim from the new fields, preserving any
        // human/ledger lifecycle edit (never re-derive status/availability from isDiscontinued).
        if (lp.Details is not null)
        {
            return new PaintRecord
            {
                Name = lp.Name,
                Category = lp.Category ?? "paint",
                Status = lp.Status ?? "current",
                Availability = lp.Availability ?? "unknown",
                FirstSeen = firstSeen,
                ProductCode = lp.ProductCode,
                Ean = lp.Ean,
                ImageUrl = lp.ImageUrl,
                Details = new PaintDetails
                {
                    Set = lp.Details.Set ?? "",
                    R = lp.Details.R,
                    G = lp.Details.G,
                    B = lp.Details.B,
                    Hex = lp.Details.Hex ?? "",
                    VolumeMl = lp.Details.VolumeMl,
                    Container = lp.Details.Container,
                    Type = lp.Details.Type,
                    Finish = lp.Details.Finish,
                },
            };
        }

        // Not yet migrated: map exactly as PaintRecordMapper.ToRecord would, then backfill firstSeen.
        return new PaintRecord
        {
            Name = lp.Name,
            Category = "paint",
            Status = lp.IsDiscontinued ? "discontinued" : "current",
            Availability = lp.IsDiscontinued ? "out_of_stock" : "unknown",
            FirstSeen = firstSeen,
            ProductCode = lp.ProductCode,
            Ean = lp.Ean,
            ImageUrl = lp.ImageUrl,
            Details = new PaintDetails
            {
                Set = lp.Set ?? "",
                R = lp.R,
                G = lp.G,
                B = lp.B,
                Hex = lp.Hex ?? "",
                VolumeMl = lp.VolumeMl,
                Container = lp.Packaging,
                Type = lp.Type,
                Finish = lp.Finish,
            },
        };
    }
}
