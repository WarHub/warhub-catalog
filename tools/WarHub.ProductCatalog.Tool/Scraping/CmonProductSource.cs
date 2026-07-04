using System.Net;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Microsoft.Playwright;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Fetches product data from CMON's WordPress REST API using Playwright
/// to bypass Cloudflare JS challenge. Products are fetched from the
/// 'products' custom post type and filtered to ASOIAF TMG items.
/// </summary>
public sealed partial class CmonProductSource : IAsyncDisposable
{
    private const string BaseUrl = "https://www.cmon.com";

    // ASOIAF TMG faction prefixes that appear in product titles
    private static readonly string[] AsoiafFactionPrefixes =
    [
        "Stark", "Lannister", "Night's Watch", "Nights Watch",
        "Free Folk", "Baratheon", "Targaryen",
        "Greyjoy", "Martell", "Bolton", "Neutral",
    ];

    // Product title patterns that indicate ASOIAF TMG products
    private static readonly string[] AsoiafKeywords =
    [
        "A Song of Ice",
        "Tabletop Miniatures Game",
    ];

    private readonly bool _verbose;
    private readonly TimeSpan _requestDelay;
    private DateTime _lastRequest = DateTime.MinValue;
    private IPlaywright? _playwright;
    private IBrowser? _browser;
    private IBrowserContext? _context;

    public CmonProductSource(bool verbose = false, TimeSpan? requestDelay = null)
    {
        _verbose = verbose;
        _requestDelay = requestDelay ?? TimeSpan.FromSeconds(2);
    }

    private async Task<IBrowserContext> GetBrowserContextAsync()
    {
        if (_context is not null)
            return _context;

        _playwright = await Playwright.CreateAsync();
        _browser = await _playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
        {
            Headless = true,
        });
        _context = await _browser.NewContextAsync(new BrowserNewContextOptions
        {
            UserAgent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        });

        // Navigate to the main site first to solve Cloudflare JS challenge
        IPage setupPage = await _context.NewPageAsync();
        try
        {
            if (_verbose) Console.WriteLine("    Solving Cloudflare challenge...");
            await setupPage.GotoAsync($"{BaseUrl}/", new PageGotoOptions
            {
                WaitUntil = WaitUntilState.NetworkIdle,
                Timeout = 30000,
            });
            // Wait for cf_clearance cookie to be set
            await setupPage.WaitForTimeoutAsync(3000);
        }
        finally
        {
            await setupPage.CloseAsync();
        }

        return _context;
    }

    public async Task<IReadOnlyList<RawProduct>> FetchAllProductsAsync(
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        var allProducts = new List<RawProduct>();
        int page = 1;
        const int perPage = 100;

        IBrowserContext context = await GetBrowserContextAsync();
        IPage browserPage = await context.NewPageAsync();

        try
        {
            while (true)
            {
                await RateLimitAsync(ct);

                string url = $"{BaseUrl}/wp-json/wp/v2/products?per_page={perPage}&page={page}&_fields=id,title,slug,link,acf";

                if (_verbose) Console.WriteLine($"    Fetching (browser): {url}");

                try
                {
                    IResponse? response = await browserPage.GotoAsync(url, new PageGotoOptions
                    {
                        WaitUntil = WaitUntilState.NetworkIdle,
                        Timeout = 30000,
                    });

                    if (response is null || !response.Ok)
                    {
                        if (_verbose) Console.WriteLine($"      Error: HTTP {response?.Status}");
                        break;
                    }

                    string json = await browserPage.InnerTextAsync("body");

                    List<CmonProduct>? products = JsonSerializer.Deserialize<List<CmonProduct>>(json, JsonOptions);

                    if (products is null || products.Count == 0)
                        break;

                    foreach (CmonProduct product in products)
                    {
                        if (!IsAsoiafProduct(product))
                            continue;

                        RawProduct? rawProduct = MapToRawProduct(product);
                        if (rawProduct is not null)
                            allProducts.Add(rawProduct);
                    }

                    if (_verbose)
                        Console.WriteLine($"      Page {page}: {products.Count} products, {allProducts.Count} ASOIAF matched");

                    if (maxProducts > 0 && allProducts.Count >= maxProducts)
                    {
                        allProducts = allProducts.Take(maxProducts).ToList();
                        break;
                    }

                    if (products.Count < perPage)
                        break;

                    page++;
                }
                catch (PlaywrightException ex)
                {
                    if (_verbose) Console.WriteLine($"      Browser error: {ex.Message}");
                    break;
                }
            }
        }
        finally
        {
            await browserPage.CloseAsync();
        }

        // Enrich products with SKUs from Shopify retailers (CMON API has empty SKUs)
        if (allProducts.Count > 0)
        {
            if (_verbose) Console.WriteLine("  Enriching SKUs from retailers...");
            await EnrichSkusFromRetailersAsync(allProducts, _verbose, ct);
        }

        return allProducts;
    }

    internal static bool IsAsoiafProduct(CmonProduct product)
    {
        string? title = product.Title?.Rendered;
        if (string.IsNullOrWhiteSpace(title))
            return false;

        string decoded = WebUtility.HtmlDecode(title);

        // Check if title starts with a known ASOIAF faction name
        foreach (string faction in AsoiafFactionPrefixes)
        {
            if (decoded.StartsWith(faction, StringComparison.OrdinalIgnoreCase))
                return true;
        }

        // Check for ASOIAF keywords in title
        foreach (string keyword in AsoiafKeywords)
        {
            if (decoded.Contains(keyword, StringComparison.OrdinalIgnoreCase))
                return true;
        }

        // Check slug for asoiaf patterns
        string? slug = product.Slug;
        if (slug is not null && (slug.Contains("asoiaf") || slug.Contains("song-of-ice")))
            return true;

        return false;
    }

    internal static RawProduct? MapToRawProduct(CmonProduct product)
    {
        string? title = product.Title?.Rendered;
        if (string.IsNullOrWhiteSpace(title))
            return null;

        string name = WebUtility.HtmlDecode(title);
        string? faction = ExtractFaction(name);
        string? description = HtmlCleaner.ToMarkdown(product.Acf?.HeaderProduct?.InformationBox?.SubTitle);

        // Extract SKU from ACF custom fields
        string? sku = product.Acf?.ProductSku;
        if (string.IsNullOrWhiteSpace(sku))
            sku = product.Acf?.AlternateProductSku;

        // Extract USD price from ACF information box
        decimal? priceUsd = ParseCmonPrice(product.Acf?.HeaderProduct?.InformationBox?.Price);

        // Extract image URL from ACF grid card image
        string? imageUrl = ExtractImageUrl(product.Acf?.HeaderProduct?.GridCardImage)
            ?? ExtractImageUrl(product.Acf?.HeaderProduct?.CardImage)
            ?? ExtractImageUrl(product.Acf?.HeaderProduct?.LargeImg);

        return new RawProduct
        {
            Name = name,
            Sku = sku,
            PriceUsd = priceUsd,
            Url = product.Link,
            ImageUrl = imageUrl,
            Description = description,
            Manufacturer = "CMON",
            GameSystem = "A Song of Ice and Fire",
            Faction = faction,
            Status = "current",
        };
    }

    internal static string? ExtractFaction(string name)
    {
        // CMON ASOIAF products follow "Faction: Product Name" pattern
        // e.g., "Stark: Heroes 1", "Baratheon: Crownland Scouts"
        foreach (string faction in AsoiafFactionPrefixes)
        {
            if (name.StartsWith(faction + ":", StringComparison.OrdinalIgnoreCase) ||
                name.StartsWith(faction + " ", StringComparison.OrdinalIgnoreCase))
            {
                // Normalize Night's Watch variants
                return faction switch
                {
                    "Nights Watch" => "Night's Watch",
                    _ => faction,
                };
            }
        }

        // Check for ASOIAF Starter Set or similar generic products
        if (name.Contains("Starter Set", StringComparison.OrdinalIgnoreCase) ||
            name.Contains("Tabletop Miniatures Game", StringComparison.OrdinalIgnoreCase))
        {
            return "Neutral";
        }

        return null;
    }

    /// <summary>
    /// Parses a price from a CMON ACF field. The field can be a string like "$39.99",
    /// a number, or an empty/boolean value.
    /// </summary>
    internal static decimal? ParseCmonPrice(JsonElement? priceElement)
    {
        if (priceElement is not { } el)
            return null;

        // Use GetRawText() for numbers to avoid floating-point→decimal artifacts
        // (e.g., JSON 37.99 → GetDecimal() → 37.990000000000001989519660128)
        string? priceStr = el.ValueKind switch
        {
            JsonValueKind.String => el.GetString(),
            JsonValueKind.Number => el.GetRawText(),
            _ => null,
        };

        if (string.IsNullOrWhiteSpace(priceStr))
            return null;

        // Strip currency symbols and whitespace
        string cleaned = priceStr.Trim().TrimStart('$', '€', '£').Trim();

        if (decimal.TryParse(cleaned, System.Globalization.NumberStyles.Number,
            System.Globalization.CultureInfo.InvariantCulture, out decimal price) && price > 0)
        {
            return Math.Round(price, 2);
        }

        return null;
    }

    /// <summary>
    /// Extracts an image URL from a CMON ACF image field.
    /// ACF image fields can be a string URL, or an object with "url" or "sizes.medium"/"sizes.large".
    /// </summary>
    internal static string? ExtractImageUrl(object? imageField)
    {
        if (imageField is null)
            return null;

        if (imageField is JsonElement element)
        {
            // If it's a string, return directly
            if (element.ValueKind == JsonValueKind.String)
            {
                string? url = element.GetString();
                return string.IsNullOrWhiteSpace(url) ? null : url;
            }

            // If it's an object, try common ACF image field structures
            if (element.ValueKind == JsonValueKind.Object)
            {
                // Try "url" property first
                if (element.TryGetProperty("url", out JsonElement urlProp) &&
                    urlProp.ValueKind == JsonValueKind.String)
                {
                    return urlProp.GetString();
                }

                // Try "sizes.large" or "sizes.medium"
                if (element.TryGetProperty("sizes", out JsonElement sizes) &&
                    sizes.ValueKind == JsonValueKind.Object)
                {
                    if (sizes.TryGetProperty("large", out JsonElement large) &&
                        large.ValueKind == JsonValueKind.String)
                        return large.GetString();
                    if (sizes.TryGetProperty("medium", out JsonElement medium) &&
                        medium.ValueKind == JsonValueKind.String)
                        return medium.GetString();
                }
            }
        }

        // If it's a plain string
        if (imageField is string str && !string.IsNullOrWhiteSpace(str))
            return str;

        return null;
    }

    private async Task RateLimitAsync(CancellationToken ct)
    {
        TimeSpan elapsed = DateTime.UtcNow - _lastRequest;
        if (elapsed < _requestDelay)
            await Task.Delay(_requestDelay - elapsed, ct);
        _lastRequest = DateTime.UtcNow;
    }

    // --- SKU enrichment from Shopify retailers ---

    /// <summary>
    /// Shopify stores that carry CMON ASOIAF products with proper SKUs.
    /// Used to assign SKUs to products scraped from CMON's API (which has empty SKU fields).
    /// </summary>
    private static readonly (string BaseUrl, string Collection)[] SkuReferenceStores =
    [
        ("https://athenagames.com", "a-song-of-ice-fire-tabletop-miniatures-game"),
    ];

    /// <summary>
    /// Enriches scraped CMON products with SKUs from Shopify retailers.
    /// CMON's WordPress API doesn't provide SKU data, so we fetch from retailers
    /// that carry CMON products and match by normalized product name.
    /// </summary>
    public static async Task<int> EnrichSkusFromRetailersAsync(
        IList<RawProduct> products,
        bool verbose = false,
        CancellationToken ct = default)
    {
        // Build a lookup of products needing SKUs, keyed by normalized name
        var needingSku = new Dictionary<string, List<RawProduct>>(StringComparer.OrdinalIgnoreCase);
        foreach (RawProduct product in products)
        {
            if (!string.IsNullOrWhiteSpace(product.Sku))
                continue;

            string normalized = NormalizeProductName(product.Name);
            if (string.IsNullOrEmpty(normalized))
                continue;

            if (!needingSku.TryGetValue(normalized, out List<RawProduct>? list))
            {
                list = [];
                needingSku[normalized] = list;
            }
            list.Add(product);
        }

        if (needingSku.Count == 0)
            return 0;

        if (verbose)
            Console.WriteLine($"    {needingSku.Count} products need SKUs, checking retailers...");

        int enriched = 0;
        using var httpClient = new HttpClient();
        httpClient.DefaultRequestHeaders.Add("Accept", "application/json");
        httpClient.DefaultRequestHeaders.Add("User-Agent", "WarHub-ProductCatalog/1.0");
        httpClient.Timeout = TimeSpan.FromSeconds(30);

        foreach ((string baseUrl, string collection) in SkuReferenceStores)
        {
            if (ct.IsCancellationRequested)
                break;

            try
            {
                IReadOnlyList<ShopifySkuEntry> entries = await FetchShopifySkusAsync(
                    httpClient, baseUrl, collection, verbose, ct);

                foreach (ShopifySkuEntry entry in entries)
                {
                    if (string.IsNullOrWhiteSpace(entry.Sku))
                        continue;

                    string normalized = NormalizeProductName(entry.Title);
                    if (string.IsNullOrEmpty(normalized))
                        continue;

                    if (!needingSku.TryGetValue(normalized, out List<RawProduct>? matches))
                        continue;

                    // Strip CMN prefix from retailer SKU
                    string sku = entry.Sku;
                    if (sku.StartsWith("CMN", StringComparison.OrdinalIgnoreCase) && sku.Length > 3)
                        sku = sku[3..];

                    foreach (RawProduct product in matches)
                    {
                        if (!string.IsNullOrWhiteSpace(product.Sku))
                            continue;

                        // RawProduct is a record — create a copy with SKU set
                        // Since we're modifying via IList, replace in-place
                        int idx = products.IndexOf(product);
                        if (idx >= 0)
                        {
                            products[idx] = product with { Sku = sku };
                            enriched++;
                            if (verbose)
                                Console.WriteLine($"      SKU {sku} → {product.Name}");
                        }
                    }

                    needingSku.Remove(normalized);
                }
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
            {
                if (verbose)
                    Console.WriteLine($"    Warning: failed to fetch SKUs from {baseUrl}: {ex.Message}");
            }
        }

        if (verbose)
            Console.WriteLine($"    Enriched {enriched} SKUs from retailers ({needingSku.Count} still missing)");

        return enriched;
    }

    private static async Task<IReadOnlyList<ShopifySkuEntry>> FetchShopifySkusAsync(
        HttpClient httpClient,
        string baseUrl,
        string collection,
        bool verbose,
        CancellationToken ct)
    {
        var results = new List<ShopifySkuEntry>();
        int page = 1;
        const int limit = 250;

        while (true)
        {
            string url = $"{baseUrl}/collections/{collection}/products.json?limit={limit}&page={page}";
            if (verbose)
                Console.WriteLine($"      Fetching SKUs: {url}");

            string json = await httpClient.GetStringAsync(url, ct);
            using JsonDocument doc = JsonDocument.Parse(json);

            if (!doc.RootElement.TryGetProperty("products", out JsonElement productsEl))
                break;

            int count = 0;
            foreach (JsonElement p in productsEl.EnumerateArray())
            {
                count++;
                string? title = p.GetProperty("title").GetString();
                string? sku = null;

                if (p.TryGetProperty("variants", out JsonElement variants))
                {
                    foreach (JsonElement v in variants.EnumerateArray())
                    {
                        if (v.TryGetProperty("sku", out JsonElement skuEl))
                        {
                            sku = skuEl.GetString();
                            if (!string.IsNullOrWhiteSpace(sku))
                                break;
                        }
                    }
                }

                if (!string.IsNullOrWhiteSpace(title) && !string.IsNullOrWhiteSpace(sku))
                    results.Add(new ShopifySkuEntry(title, sku));
            }

            if (count < limit)
                break;

            page++;
        }

        if (verbose)
            Console.WriteLine($"      Found {results.Count} products with SKUs");

        return results;
    }

    /// <summary>
    /// Normalizes a CMON ASOIAF product name for matching between our catalog and retailers.
    /// Strips prefixes, punctuation, and normalizes whitespace.
    /// </summary>
    internal static string NormalizeProductName(string name)
    {
        // Decode HTML entities
        name = WebUtility.HtmlDecode(name);

        // Strip common ASOIAF prefixes from retailer names
        name = Regex.Replace(name, @"^A Song of Ice (&|and) Fire:\s*", "", RegexOptions.IgnoreCase);
        name = Regex.Replace(name, @"\s*[-–—]\s*(A Song of Ice (&|and) Fire|ASOIAF).*$", "", RegexOptions.IgnoreCase);
        name = Regex.Replace(name, @"\s*[-–—]\s*Song of Ice (&|and) Fire.*$", "", RegexOptions.IgnoreCase);
        name = Regex.Replace(name, @"\s*[-–—]\s*Tabletop Miniatures Game.*$", "", RegexOptions.IgnoreCase);

        // Normalize faction prefix format: "Faction: Name" and "Faction Name" → "faction name"
        name = name.Replace(":", "");

        // Remove apostrophes and special characters, normalize to lowercase
        name = Regex.Replace(name, @"[''`\u2019]", ""); // smart quotes and apostrophes
        name = name.ToLowerInvariant();

        // Collapse whitespace
        name = Regex.Replace(name, @"\s+", " ").Trim();

        return name;
    }

    private record ShopifySkuEntry(string Title, string Sku);

    public async ValueTask DisposeAsync()
    {
        if (_context is not null) await _context.DisposeAsync();
        if (_browser is not null) await _browser.DisposeAsync();
        _playwright?.Dispose();
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };
}

// WordPress REST API response models for CMON

internal sealed class CmonProduct
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("title")]
    public CmonRendered? Title { get; set; }

    [JsonPropertyName("slug")]
    public string? Slug { get; set; }

    [JsonPropertyName("link")]
    public string? Link { get; set; }

    [JsonPropertyName("acf")]
    public CmonAcf? Acf { get; set; }
}

internal sealed class CmonRendered
{
    [JsonPropertyName("rendered")]
    public string? Rendered { get; set; }
}

internal sealed class CmonAcf
{
    [JsonPropertyName("header_product")]
    public CmonHeaderProduct? HeaderProduct { get; set; }

    [JsonPropertyName("product_sku")]
    public string? ProductSku { get; set; }

    [JsonPropertyName("alternate_product_sku")]
    public string? AlternateProductSku { get; set; }
}

internal sealed class CmonHeaderProduct
{
    [JsonPropertyName("information_box")]
    public CmonInformationBox? InformationBox { get; set; }

    [JsonPropertyName("grid_card_image")]
    public object? GridCardImage { get; set; }

    [JsonPropertyName("card_image")]
    public object? CardImage { get; set; }

    [JsonPropertyName("large_img")]
    public object? LargeImg { get; set; }
}

internal sealed class CmonInformationBox
{
    [JsonPropertyName("title")]
    public string? Title { get; set; }

    [JsonPropertyName("sub_title")]
    public string? SubTitle { get; set; }

    [JsonPropertyName("price")]
    public JsonElement? Price { get; set; }
}
