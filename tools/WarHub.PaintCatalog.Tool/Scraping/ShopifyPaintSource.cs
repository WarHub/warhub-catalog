using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Scraping;

/// <summary>
/// Enriches paint data from Shopify-based paint manufacturer stores.
/// Primary use: extracting swatch image URLs and product codes from
/// Army Painter (thearmypainter.com) and similar Shopify stores.
/// </summary>
public sealed partial class ShopifyPaintSource : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly string _baseUrl;
    private readonly TimeSpan _requestDelay;
    private readonly bool _verbose;
    private DateTime _lastRequest = DateTime.MinValue;

    public ShopifyPaintSource(string baseUrl, TimeSpan? requestDelay = null, bool verbose = false)
    {
        _baseUrl = baseUrl.TrimEnd('/');
        _requestDelay = requestDelay ?? TimeSpan.FromMilliseconds(500);
        _verbose = verbose;

        _httpClient = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        });
        _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd(
            "WarHub-PaintCatalog/1.0 (+https://github.com/WarHub/warhub-ai-experimental)");
        _httpClient.DefaultRequestHeaders.Accept.ParseAdd("application/json");
    }

    /// <summary>
    /// Fetches paint product data from a Shopify collection.
    /// Returns enrichment data (image URLs, SKUs, EANs) keyed by normalized paint name.
    /// </summary>
    public async Task<IReadOnlyDictionary<string, PaintEnrichmentData>> FetchPaintEnrichmentAsync(
        string collectionSlug,
        CancellationToken ct = default)
    {
        var enrichment = new Dictionary<string, PaintEnrichmentData>(StringComparer.OrdinalIgnoreCase);
        int page = 1;
        const int perPage = 250;

        while (true)
        {
            await RateLimitAsync(ct);

            string url = $"{_baseUrl}/collections/{collectionSlug}/products.json?limit={perPage}&page={page}";
            if (_verbose) Console.WriteLine($"    Fetching: {url}");

            try
            {
                var response = await _httpClient.GetFromJsonAsync<ShopifyPaintsResponse>(url, JsonOptions, ct);
                if (response?.Products is null || response.Products.Count == 0)
                    break;

                foreach (ShopifyPaintProduct product in response.Products)
                {
                    PaintEnrichmentData? data = MapToEnrichment(product);
                    if (data is not null && !enrichment.ContainsKey(data.NormalizedName))
                    {
                        enrichment[data.NormalizedName] = data;
                    }
                }

                if (_verbose) Console.WriteLine($"      Page {page}: {response.Products.Count} products (total enrichment: {enrichment.Count})");

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

        return enrichment;
    }

    internal static PaintEnrichmentData? MapToEnrichment(ShopifyPaintProduct product)
    {
        if (string.IsNullOrWhiteSpace(product.Title))
            return null;

        // Only process individual paint products (not sets/bundles)
        if (product.ProductType?.Equals("Paint", StringComparison.OrdinalIgnoreCase) != true)
        {
            // Also accept products with paint-related tags
            bool hasPaintTag = product.Tags?.Any(t =>
                t.Contains("tap-shop-paints", StringComparison.OrdinalIgnoreCase)) ?? false;
            if (!hasPaintTag)
                return null;
        }

        string title = WebUtility.HtmlDecode(product.Title);

        // Extract paint name from title (e.g., "Warpaints Fanatic: Matt White" → "Matt White")
        string paintName = ExtractPaintName(title);
        string normalizedName = NormalizePaintName(paintName);

        if (string.IsNullOrWhiteSpace(normalizedName))
            return null;

        // Get first variant for SKU and barcode
        var firstVariant = product.Variants?.FirstOrDefault();
        string? sku = firstVariant?.Sku;
        string? barcode = NormalizeBarcode(firstVariant?.Barcode);

        // Get swatch image URL (first image is typically the product/swatch image)
        string? imageUrl = product.Images?.FirstOrDefault()?.Src;

        // Extract paint line from tags
        string? paintLine = ExtractPaintLine(product.Tags);

        // Extract practical color name from description
        string? practicalName = ExtractPracticalColorName(product.BodyHtml);

        return new PaintEnrichmentData
        {
            NormalizedName = normalizedName,
            OriginalTitle = title,
            PaintName = paintName,
            Sku = sku,
            Barcode = barcode,
            ImageUrl = imageUrl,
            PaintLine = paintLine,
            PracticalColorName = practicalName,
        };
    }

    /// <summary>
    /// Extracts the paint name from a Shopify product title.
    /// E.g., "Warpaints Fanatic: Matt White" → "Matt White"
    ///        "Speedpaint: Grim Black" → "Grim Black"
    /// </summary>
    internal static string ExtractPaintName(string title)
    {
        // Common patterns: "Range: Paint Name" or "Range Name"
        int colonIndex = title.LastIndexOf(':');
        if (colonIndex >= 0 && colonIndex < title.Length - 1)
        {
            return title[(colonIndex + 1)..].Trim();
        }

        return title;
    }

    internal static string NormalizePaintName(string name)
    {
        // Remove common prefixes and normalize whitespace
        return name.Trim();
    }

    internal static string? ExtractPaintLine(IReadOnlyList<string>? tags)
    {
        if (tags is null) return null;

        // Army Painter tags encode the paint line
        foreach (string tag in tags)
        {
            if (tag.Equals("WARPAINTS FANATIC", StringComparison.OrdinalIgnoreCase))
                return "Warpaints Fanatic";
            if (tag.Equals("SPEEDPAINT", StringComparison.OrdinalIgnoreCase))
                return "Speedpaint";
            if (tag.Contains("WASHES", StringComparison.OrdinalIgnoreCase))
                return "Washes";
        }

        return null;
    }

    /// <summary>
    /// Extracts the "Practical Colour Name" from Army Painter product descriptions.
    /// E.g., "<strong>Practical Colour Name: </strong>White" → "White"
    /// </summary>
    internal static string? ExtractPracticalColorName(string? bodyHtml)
    {
        if (string.IsNullOrWhiteSpace(bodyHtml)) return null;

        Match match = PracticalColorPattern().Match(bodyHtml);
        if (match.Success)
        {
            string value = WebUtility.HtmlDecode(match.Groups["name"].Value.Trim());
            // Strip any remaining HTML tags
            value = HtmlTagPattern().Replace(value, "").Trim();
            return string.IsNullOrWhiteSpace(value) ? null : value;
        }

        return null;
    }

    internal static string? NormalizeBarcode(string? barcode)
    {
        if (string.IsNullOrWhiteSpace(barcode))
            return null;

        string trimmed = barcode.Trim();
        if (trimmed is "0" or "000000000000" or "0000000000000")
            return null;

        if (trimmed.Length is >= 8 and <= 14 && trimmed.All(char.IsDigit))
            return trimmed;

        return null;
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

    [GeneratedRegex(@"Practical\s+Colou?r\s+Name\s*:\s*</\w+>\s*(?<name>[^<\n]+)", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex PracticalColorPattern();

    [GeneratedRegex(@"<[^>]+>", RegexOptions.Compiled)]
    private static partial Regex HtmlTagPattern();
}

/// <summary>
/// Enrichment data extracted from Shopify paint products.
/// </summary>
public record PaintEnrichmentData
{
    public required string NormalizedName { get; init; }
    public required string OriginalTitle { get; init; }
    public required string PaintName { get; init; }
    public string? Sku { get; init; }
    public string? Barcode { get; init; }
    public string? ImageUrl { get; init; }
    public string? PaintLine { get; init; }
    public string? PracticalColorName { get; init; }
}

// Shopify JSON response models for paint stores

public sealed class ShopifyPaintsResponse
{
    [JsonPropertyName("products")]
    public List<ShopifyPaintProduct>? Products { get; set; }
}

public sealed class ShopifyPaintProduct
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
    public List<ShopifyPaintVariant>? Variants { get; set; }

    [JsonPropertyName("images")]
    public List<ShopifyPaintImage>? Images { get; set; }
}

public sealed class ShopifyPaintVariant
{
    [JsonPropertyName("sku")]
    public string? Sku { get; set; }

    [JsonPropertyName("barcode")]
    public string? Barcode { get; set; }

    [JsonPropertyName("price")]
    public string? Price { get; set; }

    [JsonPropertyName("available")]
    public bool Available { get; set; }
}

public sealed class ShopifyPaintImage
{
    [JsonPropertyName("src")]
    public string? Src { get; set; }
}
