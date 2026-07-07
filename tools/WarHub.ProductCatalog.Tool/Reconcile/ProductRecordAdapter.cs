using WarHub.CatalogStore;
using WarHub.CatalogStore.Reconcile;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Reconcile;

/// <summary>Adapts <see cref="Product"/> to the generic reconciler.</summary>
public sealed class ProductRecordAdapter : ICatalogRecordAdapter<Product>
{
    public string IdentityKey(Product record) => NameNormalizer.Normalize(record.Name);

    public string? Url(Product record) => string.IsNullOrWhiteSpace(record.Url) ? null : record.Url;

    public Product Merge(Product existing, Product fresh) => existing with
    {
        // Identity, firstSeen, and category are immutable across merges.
        Ean = Pick(fresh.Ean, existing.Ean),
        EanSource = Pick(fresh.EanSource, existing.EanSource),
        Sku = Pick(fresh.Sku, existing.Sku),
        ProductCode = Pick(fresh.ProductCode, existing.ProductCode),
        Packaging = string.IsNullOrWhiteSpace(fresh.Packaging) ? existing.Packaging : fresh.Packaging,
        // Scrape never drives lifecycle (enricher only ever emits "current"); a fresh
        // discontinued/delisted can only come from an override, so it wins. Otherwise the
        // archived lifecycle is sticky (ledger transitions + overrides are the only mutators).
        Status = fresh.Status is "discontinued" or "delisted" ? fresh.Status : existing.Status,
        Availability = Pick(fresh.Availability, existing.Availability)!,
        PriceGbp = fresh.PriceGbp ?? existing.PriceGbp,
        PriceUsd = fresh.PriceUsd ?? existing.PriceUsd,
        PriceEur = fresh.PriceEur ?? existing.PriceEur,
        Url = Pick(fresh.Url, existing.Url),
        ImageUrl = Pick(fresh.ImageUrl, existing.ImageUrl),
        ReleaseDate = Pick(fresh.ReleaseDate, existing.ReleaseDate),
        Description = Pick(fresh.Description, existing.Description),
        Contents = fresh.Contents is { Count: > 0 } ? fresh.Contents : existing.Contents,
    };

    public Product WithFirstSeen(Product record, string isoDate) => record with { FirstSeen = isoDate };

    public bool HasFirstSeen(Product record) => !string.IsNullOrWhiteSpace(record.FirstSeen);

    public Product ApplyRename(Product existing, Product fresh) =>
        Merge(existing, fresh) with { Name = fresh.Name };

    private static string? Pick(string? fresh, string? existing) =>
        string.IsNullOrWhiteSpace(fresh) ? existing : fresh;
}
