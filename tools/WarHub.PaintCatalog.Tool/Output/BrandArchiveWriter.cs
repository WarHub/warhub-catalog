using WarHub.CatalogStore;
using WarHub.CatalogStore.Reconcile;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Reconcile;

namespace WarHub.PaintCatalog.Tool.Output;

/// <summary>Writes/loads per-brand archival YAML files with the shared deterministic serializer.</summary>
public static class BrandArchiveWriter
{
    private static readonly PaintRecordAdapter Adapter = new();

    public static async Task WriteAsync(BrandArchive archive, string outputDir, CancellationToken ct = default)
    {
        string brandsDir = Path.Combine(outputDir, "brands");
        Directory.CreateDirectory(brandsDir);

        var sorted = archive with
        {
            Paints = archive.Paints
                .OrderBy(p => Adapter.IdentityKey(p), StringComparer.Ordinal)
                .ToList(),
        };

        string yaml = CatalogSerializer.CreateSerializer().Serialize(sorted);
        await File.WriteAllTextAsync(Path.Combine(brandsDir, $"{archive.BrandSlug}.yaml"), yaml, ct);
    }

    public static async Task<IReadOnlyList<PaintRecord>> LoadAsync(string filePath, CancellationToken ct = default) =>
        (await LoadArchiveAsync(filePath, ct))?.Paints ?? [];

    /// <summary>
    /// The whole envelope, brand display name included -- what a run needs to classify the
    /// records of a brand it did not produce (PaintCatalogApp's archive-only pass). Null when
    /// the file is absent.
    /// </summary>
    public static async Task<BrandArchive?> LoadArchiveAsync(string filePath, CancellationToken ct = default)
    {
        if (!File.Exists(filePath))
            return null;
        string yaml = await File.ReadAllTextAsync(filePath, ct);
        return CatalogSerializer.CreateDeserializer().Deserialize<BrandArchive>(yaml);
    }
}
