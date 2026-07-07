using WarHub.CatalogStore;
using WarHub.CatalogStore.Reconcile;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Reconcile;

/// <summary>Adapts <see cref="PaintRecord"/> to the generic reconciler.</summary>
public sealed class PaintRecordAdapter : ICatalogRecordAdapter<PaintRecord>
{
    public string IdentityKey(PaintRecord r) => string.Join('|',
        NameNormalizer.Normalize(r.Details.Set),
        NameNormalizer.Normalize(r.Name),
        NameNormalizer.Normalize(r.ProductCode ?? ""),
        NameNormalizer.Normalize(r.Details.Hex));

    // Composite key is strong; product codes / image URLs are non-unique/empty in paint data,
    // so URL-based rename detection is disabled. Genuine renames use aliases: overrides.
    public string? Url(PaintRecord r) => null;

    public PaintRecord Merge(PaintRecord existing, PaintRecord fresh) => existing with
    {
        // Name, FirstSeen, Category, and the identity components (Set/Hex/ProductCode) are immutable.
        Status = fresh.Status is "discontinued" or "delisted" ? fresh.Status : existing.Status,
        Availability = Pick(fresh.Availability, existing.Availability) ?? "unknown",
        Ean = Pick(fresh.Ean, existing.Ean),
        ImageUrl = Pick(fresh.ImageUrl, existing.ImageUrl),
        Details = existing.Details with
        {
            VolumeMl = fresh.Details.VolumeMl ?? existing.Details.VolumeMl,
            Container = Pick(fresh.Details.Container, existing.Details.Container),
            Type = Pick(fresh.Details.Type, existing.Details.Type),
            Finish = Pick(fresh.Details.Finish, existing.Details.Finish),
        },
    };

    public PaintRecord WithFirstSeen(PaintRecord r, string isoDate) => r with { FirstSeen = isoDate };

    public bool HasFirstSeen(PaintRecord r) => !string.IsNullOrWhiteSpace(r.FirstSeen);

    public PaintRecord ApplyRename(PaintRecord existing, PaintRecord fresh) =>
        Merge(existing, fresh) with { Name = fresh.Name };

    private static string? Pick(string? fresh, string? existing) =>
        string.IsNullOrWhiteSpace(fresh) ? existing : fresh;
}
