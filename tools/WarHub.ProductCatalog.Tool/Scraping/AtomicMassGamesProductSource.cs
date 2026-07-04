using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Fetches product data from Atomic Mass Games' WordPress REST API.
/// AMG uses a 'character' custom post type with 'game_line' taxonomy.
/// SKU codes are embedded in the rendered HTML content.
/// </summary>
public sealed partial class AtomicMassGamesProductSource : IDisposable
{
    private const string BaseUrl = "https://www.atomicmassgames.com";

    // WordPress game_line taxonomy IDs
    private static readonly Dictionary<string, int> GameLineIds = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Marvel Crisis Protocol"] = 147,
        ["Star Wars Legion"] = 148,
        ["Star Wars Shatterpoint"] = 170,
        ["Star Wars Armada"] = 171,
        ["Star Wars X-Wing"] = 172,
    };

    private readonly HttpClient _httpClient;
    private readonly bool _verbose;
    private readonly TimeSpan _requestDelay;
    private DateTime _lastRequest = DateTime.MinValue;

    public AtomicMassGamesProductSource(bool verbose = false, TimeSpan? requestDelay = null)
    {
        _verbose = verbose;
        _requestDelay = requestDelay ?? TimeSpan.FromMilliseconds(500);

        _httpClient = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        });
        _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd(
            "WarHub-ProductCatalog/1.0 (+https://github.com/WarHub/warhub-ai-experimental)");
        _httpClient.DefaultRequestHeaders.Accept.ParseAdd("application/json");
    }

    public async Task<IReadOnlyList<RawProduct>> FetchProductsForGameLineAsync(
        string gameSystem,
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        if (!GameLineIds.TryGetValue(gameSystem, out int gameLineId))
        {
            if (_verbose) Console.WriteLine($"    Unknown game line: {gameSystem}");
            return [];
        }

        var allProducts = new List<RawProduct>();
        int page = 1;
        const int perPage = 100;

        while (true)
        {
            await RateLimitAsync(ct);

            string url = $"{BaseUrl}/wp-json/wp/v2/character?game_line={gameLineId}&per_page={perPage}&page={page}&_fields=id,title,slug,link,content";

            if (_verbose) Console.WriteLine($"    Fetching: {url}");

            try
            {
                using HttpResponseMessage response = await _httpClient.GetAsync(url, ct);
                response.EnsureSuccessStatusCode();

                string? totalHeader = response.Headers.TryGetValues("X-WP-Total", out var values)
                    ? values.FirstOrDefault()
                    : null;

                List<AmgCharacter>? characters =
                    await response.Content.ReadFromJsonAsync<List<AmgCharacter>>(JsonOptions, ct);

                if (characters is null || characters.Count == 0)
                    break;

                foreach (AmgCharacter character in characters)
                {
                    RawProduct? rawProduct = MapToRawProduct(character, gameSystem);
                    if (rawProduct is not null)
                        allProducts.Add(rawProduct);
                }

                if (_verbose)
                    Console.WriteLine($"      Page {page}: {characters.Count} characters (total: {allProducts.Count}{(totalHeader is not null ? $"/{totalHeader}" : "")})");

                if (maxProducts > 0 && allProducts.Count >= maxProducts)
                {
                    allProducts = allProducts.Take(maxProducts).ToList();
                    break;
                }

                if (characters.Count < perPage)
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

    internal static RawProduct? MapToRawProduct(AmgCharacter character, string gameSystem)
    {
        string? title = character.Title?.Rendered;
        if (string.IsNullOrWhiteSpace(title))
            return null;

        string name = WebUtility.HtmlDecode(title);
        string? content = character.Content?.Rendered;

        // Extract SKU from HTML content: <span class="product-code">CP217</span>
        string? sku = ExtractSku(content);

        // Extract primary product image from content
        string? imageUrl = ExtractProductImage(content);

        // Extract description from content
        string? description = ExtractDescription(content);

        string? url = character.Link;

        return new RawProduct
        {
            Name = name,
            Sku = sku,
            Url = url,
            ImageUrl = imageUrl,
            Description = description,
            Manufacturer = "Atomic Mass Games",
            GameSystem = gameSystem,
            Status = "current",
        };
    }

    internal static string? ExtractSku(string? html)
    {
        if (string.IsNullOrWhiteSpace(html))
            return null;

        Match match = ProductCodeRegex().Match(html);
        return match.Success ? match.Groups[1].Value : null;
    }

    internal static string? ExtractProductImage(string? html)
    {
        if (string.IsNullOrWhiteSpace(html))
            return null;

        // Look for product image (class="product-image")
        Match match = ProductImageRegex().Match(html);
        if (match.Success)
            return match.Groups[1].Value;

        // Fallback: first image from Asmodee CDN
        match = AsmoDeeCdnImageRegex().Match(html);
        return match.Success ? match.Groups[1].Value : null;
    }

    internal static string? ExtractDescription(string? html)
    {
        if (string.IsNullOrWhiteSpace(html))
            return null;

        // Find the first <p> tag content after the product-code heading
        Match match = DescriptionRegex().Match(html);
        if (!match.Success)
            return null;

        return HtmlCleaner.ToMarkdown(match.Groups[1].Value);
    }

    [GeneratedRegex("""<span\s+class="product-code">([^<]+)</span>""", RegexOptions.IgnoreCase)]
    private static partial Regex ProductCodeRegex();

    [GeneratedRegex("""<img[^>]+class="product-image"[^>]+src="([^"]+)"[^>]*>""", RegexOptions.IgnoreCase)]
    private static partial Regex ProductImageRegex();

    [GeneratedRegex("""(https://cdn\.svc\.asmodee\.net/[^"]+)""", RegexOptions.IgnoreCase)]
    private static partial Regex AsmoDeeCdnImageRegex();

    [GeneratedRegex("""</h1>.*?<p>(.+?)</p>""", RegexOptions.Singleline)]
    private static partial Regex DescriptionRegex();

    private async Task RateLimitAsync(CancellationToken ct)
    {
        TimeSpan elapsed = DateTime.UtcNow - _lastRequest;
        if (elapsed < _requestDelay)
            await Task.Delay(_requestDelay - elapsed, ct);
        _lastRequest = DateTime.UtcNow;
    }

    public void Dispose() => _httpClient.Dispose();

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };
}

// WordPress REST API response models for AMG

internal sealed class AmgCharacter
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("title")]
    public AmgRendered? Title { get; set; }

    [JsonPropertyName("slug")]
    public string? Slug { get; set; }

    [JsonPropertyName("link")]
    public string? Link { get; set; }

    [JsonPropertyName("content")]
    public AmgRendered? Content { get; set; }

    [JsonPropertyName("game_line")]
    public List<int>? GameLine { get; set; }
}

internal sealed class AmgRendered
{
    [JsonPropertyName("rendered")]
    public string? Rendered { get; set; }
}
