namespace WarHub.PaintCatalog.Tool.Configuration;

/// <summary>
/// Registry of paint brands available from web scraping sources (not Arcturus5404).
/// These brands require active scraping from manufacturer or retailer websites.
/// </summary>
public static class ScrapedBrandRegistry
{
    /// <summary>
    /// Brands scraped from Scalemates.com color database.
    /// Key: brand slug, Value: Scalemates brand path and metadata.
    /// </summary>
    public static readonly IReadOnlyDictionary<string, ScrapedBrandInfo> ScalematesBrands =
        new Dictionary<string, ScrapedBrandInfo>(StringComparer.OrdinalIgnoreCase)
        {
            ["two-thin-coats"] = new(
                DisplayName: "Two Thin Coats",
                Slug: "two-thin-coats",
                ScalematesPath: "two-thin-coats--1055",
                DefaultVolumeMl: 15,
                DefaultPackaging: "dropper"),
        };

    /// <summary>
    /// Shopify stores used for LIVE paint data enrichment each scrape run. Deliberately empty
    /// since 2026-07-24: storefront metadata (EANs, swatch images) now flows from the COMMITTED
    /// harvest files instead (data/paints/harvest/*.yaml via --harvest; produced on demand by
    /// the acquire pipeline's shopify-paints sources + gen_paint_harvest.py). That covers more
    /// ranges than the two collections this registry reached, needs no network in the weekly
    /// job, and stops the per-run ProductCode overwrite from store SKUs that re-keyed paint
    /// identities (store SKUs are recorded in the harvest files for audit instead). The
    /// registry and mechanism stay for a store that ever genuinely needs live enrichment.
    /// </summary>
    public static readonly IReadOnlyDictionary<string, ShopifyPaintStoreInfo> ShopifyStores =
        new Dictionary<string, ShopifyPaintStoreInfo>(StringComparer.OrdinalIgnoreCase);
}

/// <summary>
/// Configuration for a brand scraped from Scalemates.com.
/// </summary>
public record ScrapedBrandInfo(
    string DisplayName,
    string Slug,
    string ScalematesPath,
    int DefaultVolumeMl,
    string DefaultPackaging);

/// <summary>
/// Configuration for enriching paint data from a Shopify store.
/// </summary>
public record ShopifyPaintStoreInfo(
    string BrandSlug,
    string BaseUrl,
    IReadOnlyList<string> Collections);
