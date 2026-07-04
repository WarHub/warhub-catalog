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
    /// Shopify stores used for paint data enrichment (swatch images, SKUs).
    /// Key: brand slug, Value: Shopify store configuration.
    /// </summary>
    public static readonly IReadOnlyDictionary<string, ShopifyPaintStoreInfo> ShopifyStores =
        new Dictionary<string, ShopifyPaintStoreInfo>(StringComparer.OrdinalIgnoreCase)
        {
            ["army-painter"] = new(
                BrandSlug: "army-painter",
                BaseUrl: "https://thearmypainter.com",
                Collections: ["warpaints-fanatic", "speedpaint"]),
        };
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
