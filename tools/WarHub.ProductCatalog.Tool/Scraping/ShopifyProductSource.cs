using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Generic product source for Shopify-based stores.
/// Uses the public /products.json endpoint which doesn't require authentication.
/// Works for Warlord Games, Wyrd Games, and any other Shopify-based miniature store.
/// </summary>
public sealed partial class ShopifyProductSource : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly string _baseUrl;
    private readonly string _manufacturer;
    private readonly Func<ShopifyProduct, string?> _gameSystemExtractor;
    private readonly Func<ShopifyProduct, string, string?> _factionExtractor;
    private readonly Func<ShopifyProduct, string?> _productTypeClassifier;
    private readonly string _defaultGameSystem;
    private readonly string? _defaultCurrency;
    private readonly bool _verbose;
    private readonly TimeSpan _requestDelay;
    private DateTime _lastRequest = DateTime.MinValue;

    public ShopifyProductSource(
        string baseUrl,
        string manufacturer,
        string defaultGameSystem,
        Func<ShopifyProduct, string?>? gameSystemExtractor = null,
        Func<ShopifyProduct, string, string?>? factionExtractor = null,
        Func<ShopifyProduct, string?>? productTypeClassifier = null,
        string? defaultCurrency = null,
        TimeSpan? requestDelay = null,
        bool verbose = false)
    {
        _baseUrl = baseUrl.TrimEnd('/');
        _manufacturer = manufacturer;
        _defaultGameSystem = defaultGameSystem;
        _gameSystemExtractor = gameSystemExtractor ?? (_ => null);
        _factionExtractor = factionExtractor ?? ((_, _) => null);
        _productTypeClassifier = productTypeClassifier ?? (_ => null);
        _defaultCurrency = defaultCurrency;
        _requestDelay = requestDelay ?? TimeSpan.FromMilliseconds(500);
        _verbose = verbose;

        _httpClient = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        });
        _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd(
            "WarHub-ProductCatalog/1.0 (+https://github.com/WarHub/warhub-ai-experimental)");
        _httpClient.DefaultRequestHeaders.Accept.ParseAdd("application/json");
    }

    /// <summary>
    /// Fetches all products from the Shopify store, paginating through all pages.
    /// </summary>
    public async Task<IReadOnlyList<RawProduct>> FetchAllProductsAsync(
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        var allProducts = new List<RawProduct>();
        int page = 1;
        const int perPage = 250; // Shopify max

        while (true)
        {
            await RateLimitAsync(ct);

            string url = $"{_baseUrl}/products.json?limit={perPage}&page={page}";
            if (_verbose) Console.WriteLine($"    Fetching: {url}");

            try
            {
                ShopifyProductsResponse? response =
                    await _httpClient.GetFromJsonAsync<ShopifyProductsResponse>(url, JsonOptions, ct);

                if (response?.Products is null || response.Products.Count == 0)
                    break;

                foreach (ShopifyProduct product in response.Products)
                {
                    RawProduct? rawProduct = MapToRawProduct(product);
                    if (rawProduct is not null)
                    {
                        allProducts.Add(rawProduct);
                    }
                }

                if (_verbose) Console.WriteLine($"      Page {page}: {response.Products.Count} products (total: {allProducts.Count})");

                if (maxProducts > 0 && allProducts.Count >= maxProducts)
                {
                    allProducts = allProducts.Take(maxProducts).ToList();
                    break;
                }

                if (response.Products.Count < perPage)
                    break;

                page++;
            }
            catch (HttpRequestException ex)
            {
                if (_verbose) Console.WriteLine($"      Error: {ex.Message}");
                break;
            }
        }

        return allProducts;
    }

    internal RawProduct? MapToRawProduct(ShopifyProduct product)
    {
        if (string.IsNullOrWhiteSpace(product.Title))
            return null;

        string name = WebUtility.HtmlDecode(product.Title);

        // Determine game system and faction
        string gameSystem = _gameSystemExtractor(product) ?? _defaultGameSystem;
        string? faction = _factionExtractor(product, gameSystem);

        // Get first variant for price, SKU, and EAN barcode
        ShopifyVariant? firstVariant = product.Variants?.FirstOrDefault();
        decimal? price = ParsePrice(firstVariant?.Price);
        string? sku = firstVariant?.Sku;
        string? ean = NormalizeBarcode(firstVariant?.Barcode);

        // Get first image
        string? imageUrl = product.Images?.FirstOrDefault()?.Src;

        // Clean description
        string? description = HtmlCleaner.ToMarkdown(product.BodyHtml);

        // Determine status
        string status = DetermineStatus(product);

        // Classify product type
        string? productType = _productTypeClassifier(product);

        // Build URL
        string? url = !string.IsNullOrWhiteSpace(product.Handle)
            ? $"{_baseUrl}/products/{product.Handle}"
            : null;

        // Assign price to correct currency field
        decimal? priceGbp = null;
        decimal? priceUsd = null;
        decimal? priceEur = null;

        switch (_defaultCurrency?.ToUpperInvariant())
        {
            case "GBP":
                priceGbp = price;
                break;
            case "EUR":
                priceEur = price;
                break;
            default:
                priceUsd = price;
                break;
        }

        return new RawProduct
        {
            Name = name,
            Sku = sku,
            Ean = ean,
            PriceGbp = priceGbp,
            PriceUsd = priceUsd,
            PriceEur = priceEur,
            Url = url,
            ImageUrl = imageUrl,
            Description = description,
            Manufacturer = _manufacturer,
            GameSystem = gameSystem,
            Faction = faction,
            Status = status,
            ProductType = productType,
        };
    }

    internal static decimal? ParsePrice(string? priceStr)
    {
        if (string.IsNullOrWhiteSpace(priceStr))
            return null;

        if (decimal.TryParse(priceStr, System.Globalization.NumberStyles.Number,
            System.Globalization.CultureInfo.InvariantCulture, out decimal price))
        {
            return price;
        }

        return null;
    }

    /// <summary>
    /// Validates and normalizes a barcode string to a standard EAN-13 or UPC-A format.
    /// Returns null for empty, placeholder, or non-numeric values.
    /// </summary>
    internal static string? NormalizeBarcode(string? barcode)
    {
        if (string.IsNullOrWhiteSpace(barcode))
            return null;

        string trimmed = barcode.Trim();

        // Filter out common placeholders
        if (trimmed is "0" or "000000000000" or "0000000000000")
            return null;

        // EAN-13 = 13 digits, UPC-A = 12 digits, EAN-8 = 8 digits
        if (trimmed.Length is >= 8 and <= 14 && trimmed.All(char.IsDigit))
            return trimmed;

        return null;
    }

    internal static string DetermineStatus(ShopifyProduct product)
    {
        bool hasPreorderTag = product.Tags?.Any(t =>
            t.Contains("preorder", StringComparison.OrdinalIgnoreCase) ||
            t.Contains("pre-order", StringComparison.OrdinalIgnoreCase)) ?? false;
        if (hasPreorderTag)
            return "pre_order";

        // Check if any variant is available
        bool anyAvailable = product.Variants?.Any(v => v.Available) ?? false;
        if (!anyAvailable)
            return "out_of_stock";

        return "current";
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

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };
}

// Shopify JSON API response models

public sealed class ShopifyProductsResponse
{
    [JsonPropertyName("products")]
    public List<ShopifyProduct>? Products { get; set; }
}

public sealed class ShopifyProduct
{
    [JsonPropertyName("id")]
    public long Id { get; set; }

    [JsonPropertyName("title")]
    public string? Title { get; set; }

    [JsonPropertyName("handle")]
    public string? Handle { get; set; }

    [JsonPropertyName("body_html")]
    public string? BodyHtml { get; set; }

    [JsonPropertyName("vendor")]
    public string? Vendor { get; set; }

    [JsonPropertyName("product_type")]
    public string? ProductType { get; set; }

    [JsonPropertyName("tags")]
    public List<string>? Tags { get; set; }

    [JsonPropertyName("variants")]
    public List<ShopifyVariant>? Variants { get; set; }

    [JsonPropertyName("images")]
    public List<ShopifyImage>? Images { get; set; }

    [JsonPropertyName("published_at")]
    public string? PublishedAt { get; set; }

    [JsonPropertyName("created_at")]
    public string? CreatedAt { get; set; }

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; set; }
}

public sealed class ShopifyVariant
{
    [JsonPropertyName("id")]
    public long Id { get; set; }

    [JsonPropertyName("title")]
    public string? Title { get; set; }

    [JsonPropertyName("sku")]
    public string? Sku { get; set; }

    [JsonPropertyName("price")]
    public string? Price { get; set; }

    [JsonPropertyName("compare_at_price")]
    public string? CompareAtPrice { get; set; }

    [JsonPropertyName("available")]
    public bool Available { get; set; }

    [JsonPropertyName("grams")]
    public int Grams { get; set; }

    [JsonPropertyName("barcode")]
    public string? Barcode { get; set; }
}

public sealed class ShopifyImage
{
    [JsonPropertyName("id")]
    public long Id { get; set; }

    [JsonPropertyName("src")]
    public string? Src { get; set; }

    [JsonPropertyName("width")]
    public int? Width { get; set; }

    [JsonPropertyName("height")]
    public int? Height { get; set; }
}
