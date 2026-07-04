using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Fetches product data from Para Bellum's WooCommerce store at eshop.para-bellum.com.
/// Uses the public WooCommerce Store API which doesn't require authentication.
/// </summary>
public sealed class WooCommerceProductSource : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly string _baseUrl;
    private readonly string _manufacturer;
    private readonly string _gameSystem;
    private readonly Func<List<WooCommerceCategory>?, string?>? _customFactionExtractor;
    private readonly bool _verbose;
    private readonly TimeSpan _requestDelay;
    private DateTime _lastRequest = DateTime.MinValue;

    public WooCommerceProductSource(
        string baseUrl,
        string manufacturer,
        string gameSystem,
        Func<List<WooCommerceCategory>?, string?>? factionExtractor = null,
        TimeSpan? requestDelay = null,
        bool verbose = false)
    {
        _baseUrl = baseUrl.TrimEnd('/');
        _manufacturer = manufacturer;
        _gameSystem = gameSystem;
        _customFactionExtractor = factionExtractor;
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
    /// Fetches all products from the WooCommerce store, paginating through all pages.
    /// </summary>
    public async Task<IReadOnlyList<RawProduct>> FetchAllProductsAsync(
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        var allProducts = new List<RawProduct>();
        int page = 1;
        const int perPage = 100;

        while (true)
        {
            await RateLimitAsync(ct);

            string url = $"{_baseUrl}/wp-json/wc/store/products?per_page={perPage}&page={page}";
            if (_verbose) Console.WriteLine($"    Fetching: {url}");

            try
            {
                List<WooCommerceProduct>? products =
                    await _httpClient.GetFromJsonAsync<List<WooCommerceProduct>>(url, JsonOptions, ct);

                if (products is null || products.Count == 0)
                    break;

                foreach (WooCommerceProduct wooProduct in products)
                {
                    RawProduct? rawProduct = MapToRawProduct(wooProduct, _manufacturer, _gameSystem, _customFactionExtractor);
                    if (rawProduct is not null)
                    {
                        allProducts.Add(rawProduct);
                    }
                }

                if (_verbose) Console.WriteLine($"      Page {page}: {products.Count} products (total: {allProducts.Count})");

                if (maxProducts > 0 && allProducts.Count >= maxProducts)
                {
                    allProducts = allProducts.Take(maxProducts).ToList();
                    break;
                }

                if (products.Count < perPage)
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

    internal static RawProduct? MapToRawProduct(
        WooCommerceProduct wooProduct,
        string manufacturer,
        string gameSystem,
        Func<List<WooCommerceCategory>?, string?>? customFactionExtractor = null)
    {
        if (string.IsNullOrWhiteSpace(wooProduct.Name))
            return null;

        // Decode HTML entities in name
        string name = WebUtility.HtmlDecode(wooProduct.Name);

        // Extract faction from categories
        string? faction = customFactionExtractor is not null
            ? customFactionExtractor(wooProduct.Categories)
            : ExtractFaction(wooProduct.Categories);

        // Parse price (WooCommerce Store API returns price in minor units as string)
        decimal? priceUsd = ParseWooCommercePrice(wooProduct.Prices);

        // Get first image URL
        string? imageUrl = wooProduct.Images is { Count: > 0 }
            ? wooProduct.Images[0].Src
            : null;

        // Get clean description
        string? description = HtmlCleaner.ToMarkdown(wooProduct.ShortDescription);

        // Determine status
        string status = DetermineStatus(wooProduct);

        return new RawProduct
        {
            Name = name,
            Sku = wooProduct.Sku,
            PriceUsd = priceUsd,
            Url = wooProduct.Permalink,
            ImageUrl = imageUrl,
            Description = description,
            Manufacturer = manufacturer,
            GameSystem = gameSystem,
            Faction = faction,
            Status = status,
        };
    }

    internal static decimal? ParseWooCommercePrice(WooCommercePrice? prices)
    {
        if (prices is null)
            return null;

        // WooCommerce Store API returns price in minor units as a string
        string? priceStr = prices.Price;
        if (string.IsNullOrWhiteSpace(priceStr))
            return null;

        if (decimal.TryParse(priceStr, NumberStyles.Number, CultureInfo.InvariantCulture, out decimal price))
        {
            // Convert from minor units (cents) to major units (dollars)
            int decimals = prices.CurrencyMinorUnit;
            if (decimals > 0)
            {
                price /= (decimal)Math.Pow(10, decimals);
            }
            return price;
        }

        return null;
    }

    internal static string? ExtractFaction(List<WooCommerceCategory>? categories)
    {
        if (categories is null || categories.Count == 0)
            return null;

        // Known faction category names for Para Bellum Conquest
        string[] factionNames =
        [
            "Hundred Kingdoms", "Spires", "Dweghom", "Nords",
            "Old Dominion", "W'adrhŭn", "City States",
            "Sorcerer Kings", "Yoroni", "Weaver Courts",
        ];

        foreach (WooCommerceCategory category in categories)
        {
            string catName = WebUtility.HtmlDecode(category.Name ?? "");
            string? match = factionNames.FirstOrDefault(f =>
                catName.Contains(f, StringComparison.OrdinalIgnoreCase));
            if (match is not null)
                return match;
        }

        return null;
    }

    internal static string DetermineStatus(WooCommerceProduct product)
    {
        bool isPreOrder = product.Categories?.Any(c =>
            c.Name?.Contains("Pre-Order", StringComparison.OrdinalIgnoreCase) == true) ?? false;
        if (isPreOrder)
            return "pre_order";

        if (!product.IsPurchasable)
            return "discontinued";

        if (!product.IsInStock)
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
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };
}

// WooCommerce Store API response models

internal sealed class WooCommerceProduct
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("sku")]
    public string? Sku { get; set; }

    [JsonPropertyName("permalink")]
    public string? Permalink { get; set; }

    [JsonPropertyName("short_description")]
    public string? ShortDescription { get; set; }

    [JsonPropertyName("description")]
    public string? Description { get; set; }

    [JsonPropertyName("prices")]
    public WooCommercePrice? Prices { get; set; }

    [JsonPropertyName("images")]
    public List<WooCommerceImage>? Images { get; set; }

    [JsonPropertyName("categories")]
    public List<WooCommerceCategory>? Categories { get; set; }

    [JsonPropertyName("is_purchasable")]
    public bool IsPurchasable { get; set; } = true;

    [JsonPropertyName("is_in_stock")]
    public bool IsInStock { get; set; } = true;
}

internal sealed class WooCommercePrice
{
    [JsonPropertyName("price")]
    public string? Price { get; set; }

    [JsonPropertyName("regular_price")]
    public string? RegularPrice { get; set; }

    [JsonPropertyName("sale_price")]
    public string? SalePrice { get; set; }

    [JsonPropertyName("currency_code")]
    public string? CurrencyCode { get; set; }

    [JsonPropertyName("currency_minor_unit")]
    public int CurrencyMinorUnit { get; set; } = 2;
}

internal sealed class WooCommerceImage
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("src")]
    public string? Src { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("alt")]
    public string? Alt { get; set; }
}

public sealed class WooCommerceCategory
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("slug")]
    public string? Slug { get; set; }
}
