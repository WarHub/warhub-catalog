using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using WarHub.ProductCatalog.Tool.Configuration;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Legacy HTML scraper for Games Workshop / Warhammer website.
/// 
/// NOTE: As of 2025, games-workshop.com is a Next.js SPA behind AWS WAF.
/// Product data is loaded client-side, so traditional HTML scraping gets
/// empty pages. The primary data source is now <see cref="AlgoliaProductSource"/>
/// which queries GW's Algolia product search index directly.
/// 
/// This scraper is retained for JSON-LD parsing as a fallback if GW
/// re-enables server-side rendering or for other sites that serve HTML.
/// </summary>
public sealed partial class GamesWorkshopScraper : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly TimeSpan _requestDelay;
    private readonly bool _verbose;
    private DateTime _lastRequest = DateTime.MinValue;

    public GamesWorkshopScraper(TimeSpan? requestDelay = null, bool verbose = false)
    {
        _requestDelay = requestDelay ?? TimeSpan.FromMilliseconds(1500);
        _verbose = verbose;
        _httpClient = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        });
        _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36");
        _httpClient.DefaultRequestHeaders.Accept.ParseAdd("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
        _httpClient.DefaultRequestHeaders.AcceptLanguage.ParseAdd("en-GB,en;q=0.9");
    }

    /// <summary>
    /// Scrapes product listings from the GW website for a given game system and faction.
    /// Returns raw product data that needs enrichment.
    /// </summary>
    public async Task<IReadOnlyList<RawProduct>> ScrapeAsync(
        string gameSystem,
        string? faction = null,
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        var products = new List<RawProduct>();

        string url = BuildListingUrl(gameSystem, faction);
        if (_verbose) Console.WriteLine($"  Fetching: {url}");

        await RateLimitAsync(ct);

        try
        {
            string html = await _httpClient.GetStringAsync(url, ct);
            IReadOnlyList<RawProduct> parsed = ParseProductListing(html, gameSystem, faction);
            products.AddRange(parsed);
        }
        catch (HttpRequestException ex)
        {
            if (_verbose) Console.WriteLine($"  Warning: Failed to fetch {url}: {ex.Message}");
        }

        if (maxProducts > 0 && products.Count > maxProducts)
        {
            products = products.Take(maxProducts).ToList();
        }

        return products;
    }

    /// <summary>
    /// Parses a product listing page HTML to extract product data.
    /// GW pages typically contain structured product data in JSON-LD or data attributes.
    /// </summary>
    internal static IReadOnlyList<RawProduct> ParseProductListing(
        string html, string gameSystem, string? faction)
    {
        var products = new List<RawProduct>();

        // Try to extract JSON-LD structured data
        MatchCollection jsonLdMatches = JsonLdRegex().Matches(html);
        foreach (Match match in jsonLdMatches)
        {
            string jsonLd = match.Groups[1].Value;
            try
            {
                JsonDocument doc = JsonDocument.Parse(jsonLd);
                JsonElement root = doc.RootElement;

                if (root.ValueKind == JsonValueKind.Object &&
                    root.TryGetProperty("@type", out JsonElement typeEl) &&
                    typeEl.GetString() is "Product" or "ProductGroup")
                {
                    RawProduct? product = ParseJsonLdProduct(root, gameSystem, faction);
                    if (product is not null)
                    {
                        products.Add(product);
                    }
                }
                else if (root.ValueKind == JsonValueKind.Array)
                {
                    foreach (JsonElement item in root.EnumerateArray())
                    {
                        if (item.TryGetProperty("@type", out JsonElement itemType) &&
                            itemType.GetString() is "Product" or "ProductGroup")
                        {
                            RawProduct? product = ParseJsonLdProduct(item, gameSystem, faction);
                            if (product is not null)
                            {
                                products.Add(product);
                            }
                        }
                    }
                }
            }
            catch (JsonException)
            {
                // Skip invalid JSON-LD blocks
            }
        }

        // If no JSON-LD found, try to parse product cards from HTML
        if (products.Count == 0)
        {
            products.AddRange(ParseProductCards(html, gameSystem, faction));
        }

        return products;
    }

    private static RawProduct? ParseJsonLdProduct(JsonElement element, string gameSystem, string? faction)
    {
        string? name = element.TryGetProperty("name", out JsonElement nameEl) ? nameEl.GetString() : null;
        if (string.IsNullOrWhiteSpace(name))
            return null;

        string? sku = element.TryGetProperty("sku", out JsonElement skuEl) ? skuEl.GetString() : null;
        string? url = element.TryGetProperty("url", out JsonElement urlEl) ? urlEl.GetString() : null;
        string? imageUrl = element.TryGetProperty("image", out JsonElement imgEl) ? GetImageUrl(imgEl) : null;
        string? description = element.TryGetProperty("description", out JsonElement descEl) ? descEl.GetString() : null;

        decimal? priceGbp = null;
        if (element.TryGetProperty("offers", out JsonElement offersEl))
        {
            priceGbp = ParsePrice(offersEl);
        }

        string? gtin = element.TryGetProperty("gtin13", out JsonElement gtinEl) ? gtinEl.GetString() : null;
        gtin ??= element.TryGetProperty("gtin", out JsonElement gtin2El) ? gtin2El.GetString() : null;

        return new RawProduct
        {
            Name = name,
            Sku = sku,
            Ean = gtin,
            Url = url,
            ImageUrl = imageUrl,
            PriceGbp = priceGbp,
            Description = description,
            Manufacturer = "Games Workshop",
            GameSystem = gameSystem,
            Faction = faction,
            Status = "current",
        };
    }

    private static string? GetImageUrl(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.String)
            return element.GetString();
        if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement item in element.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                    return item.GetString();
            }
        }
        return null;
    }

    private static decimal? ParsePrice(JsonElement offersEl)
    {
        if (offersEl.ValueKind == JsonValueKind.Object &&
            offersEl.TryGetProperty("price", out JsonElement priceEl))
        {
            if (priceEl.ValueKind == JsonValueKind.Number)
                return priceEl.GetDecimal();
            if (priceEl.ValueKind == JsonValueKind.String &&
                decimal.TryParse(priceEl.GetString(), NumberStyles.Number, CultureInfo.InvariantCulture, out decimal price))
                return price;
        }

        if (offersEl.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement offer in offersEl.EnumerateArray())
            {
                decimal? price = ParsePrice(offer);
                if (price.HasValue) return price;
            }
        }

        return null;
    }

    /// <summary>
    /// Parses product cards from HTML when JSON-LD is not available.
    /// Looks for common GW product card patterns.
    /// </summary>
    internal static IReadOnlyList<RawProduct> ParseProductCards(
        string html, string gameSystem, string? faction)
    {
        var products = new List<RawProduct>();

        MatchCollection productMatches = ProductCardRegex().Matches(html);
        foreach (Match match in productMatches)
        {
            string productHtml = match.Value;

            string? name = ExtractText(productHtml, ProductNameRegex());
            if (string.IsNullOrWhiteSpace(name)) continue;

            string? url = ExtractAttribute(productHtml, ProductLinkRegex());
            string? imageUrl = ExtractAttribute(productHtml, ProductImageRegex());
            string? priceText = ExtractText(productHtml, ProductPriceRegex());

            decimal? priceGbp = null;
            if (priceText is not null)
            {
                string cleanPrice = PriceCleanRegex().Replace(priceText, "");
                if (decimal.TryParse(cleanPrice, NumberStyles.Number, CultureInfo.InvariantCulture, out decimal parsed))
                    priceGbp = parsed;
            }

            products.Add(new RawProduct
            {
                Name = name.Trim(),
                Url = url,
                ImageUrl = imageUrl,
                PriceGbp = priceGbp,
                Manufacturer = "Games Workshop",
                GameSystem = gameSystem,
                Faction = faction,
                Status = "current",
            });
        }

        return products;
    }

    private static string? ExtractText(string html, Regex regex)
    {
        Match match = regex.Match(html);
        return match.Success ? match.Groups[1].Value.Trim() : null;
    }

    private static string? ExtractAttribute(string html, Regex regex)
    {
        Match match = regex.Match(html);
        return match.Success ? match.Groups[1].Value.Trim() : null;
    }

    private static string BuildListingUrl(string gameSystem, string? faction)
    {
        string slug = ManufacturerRegistry.Slugify(gameSystem);
        string baseUrl = $"https://www.games-workshop.com/en-GB/{slug}";
        if (!string.IsNullOrWhiteSpace(faction))
        {
            baseUrl += $"/{ManufacturerRegistry.Slugify(faction)}";
        }
        return baseUrl;
    }

    private async Task RateLimitAsync(CancellationToken ct)
    {
        TimeSpan elapsed = DateTime.UtcNow - _lastRequest;
        if (elapsed < _requestDelay)
        {
            await Task.Delay(_requestDelay - elapsed, ct);
        }
        _lastRequest = DateTime.UtcNow;
    }

    public void Dispose()
    {
        _httpClient.Dispose();
    }

    // Regex patterns for parsing GW HTML

    [GeneratedRegex(@"<script[^>]*type=[""']application/ld\+json[""'][^>]*>(.*?)</script>", RegexOptions.Singleline)]
    private static partial Regex JsonLdRegex();

    [GeneratedRegex(@"<div[^>]*class=""[^""]*product-item[^""]*""[^>]*>.*?</div>\s*</div>", RegexOptions.Singleline)]
    private static partial Regex ProductCardRegex();

    [GeneratedRegex(@"<(?:h[1-6]|span|a)[^>]*class=""[^""]*product-item__name[^""]*""[^>]*>(.*?)</(?:h[1-6]|span|a)>", RegexOptions.Singleline)]
    private static partial Regex ProductNameRegex();

    [GeneratedRegex(@"<a[^>]*href=""([^""]+)""[^>]*class=""[^""]*product-item", RegexOptions.Singleline)]
    private static partial Regex ProductLinkRegex();

    [GeneratedRegex(@"<img[^>]*src=""([^""]+)""[^>]*class=""[^""]*product-item", RegexOptions.Singleline)]
    private static partial Regex ProductImageRegex();

    [GeneratedRegex(@"<span[^>]*class=""[^""]*price[^""]*""[^>]*>(.*?)</span>", RegexOptions.Singleline)]
    private static partial Regex ProductPriceRegex();

    [GeneratedRegex(@"[£$€,\s]")]
    private static partial Regex PriceCleanRegex();
}
