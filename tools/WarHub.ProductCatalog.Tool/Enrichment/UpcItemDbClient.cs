using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// HTTP client for UPCitemdb API. Supports both free trial and paid tiers.
/// Free tier: 100 requests/day, 2 search requests per 30 seconds.
/// </summary>
public sealed class UpcItemDbClient : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly bool _verbose;
    private DateTime _lastRequest = DateTime.MinValue;
    private int _consecutiveRateLimits;

    // Free trial: 2 requests per 30 seconds for search
    private static readonly TimeSpan RateLimit = TimeSpan.FromSeconds(16);

    /// <summary>
    /// Number of consecutive rate limit (429) responses before stopping.
    /// </summary>
    private const int MaxConsecutiveRateLimits = 2;

    /// <summary>
    /// True if the client has hit too many consecutive rate limits and should not be used.
    /// </summary>
    public bool IsRateLimited => _consecutiveRateLimits >= MaxConsecutiveRateLimits;

    /// <summary>
    /// Creates a new UPCitemdb client.
    /// If apiKey is null, uses the free trial endpoint (100 requests/day).
    /// </summary>
    public UpcItemDbClient(string? apiKey = null, bool verbose = false)
    {
        _verbose = verbose;
        _httpClient = new HttpClient();
        _httpClient.DefaultRequestHeaders.Add("Accept", "application/json");
        _httpClient.DefaultRequestHeaders.Add("User-Agent", "WarHub-ProductCatalog/1.0");

        if (!string.IsNullOrWhiteSpace(apiKey))
        {
            _httpClient.BaseAddress = new Uri("https://api.upcitemdb.com/prod/v1/");
            _httpClient.DefaultRequestHeaders.Add("user_key", apiKey);
        }
        else
        {
            _httpClient.BaseAddress = new Uri("https://api.upcitemdb.com/prod/trial/");
        }
    }

    /// <summary>
    /// Searches for products by name. Returns matching items.
    /// </summary>
    public async Task<UpcSearchResult?> SearchAsync(string query, CancellationToken ct = default)
    {
        await RateLimitAsync(ct);

        string url = $"search?s={Uri.EscapeDataString(query)}&match_mode=0&type=product";

        if (_verbose)
            Console.WriteLine($"  [UPCitemdb] Searching: {query}");

        try
        {
            UpcSearchResult? result = await _httpClient.GetFromJsonAsync<UpcSearchResult>(url, ct);
            _consecutiveRateLimits = 0; // Reset on success
            if (_verbose)
                Console.WriteLine($"  [UPCitemdb] Found {result?.Total ?? 0} results");
            return result;
        }
        catch (HttpRequestException ex) when (ex.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
        {
            _consecutiveRateLimits++;
            if (_verbose)
                Console.WriteLine($"  [UPCitemdb] Rate limited ({_consecutiveRateLimits}/{MaxConsecutiveRateLimits}), waiting 30s...");
            await Task.Delay(TimeSpan.FromSeconds(30), ct);
            return null;
        }
        catch (HttpRequestException ex)
        {
            if (_verbose)
                Console.WriteLine($"  [UPCitemdb] Error: {ex.Message}");
            return null;
        }
    }

    /// <summary>
    /// Looks up a product by exact EAN/UPC code.
    /// </summary>
    public async Task<UpcSearchResult?> LookupAsync(string ean, CancellationToken ct = default)
    {
        await RateLimitAsync(ct);

        string url = $"lookup?upc={Uri.EscapeDataString(ean)}";

        try
        {
            return await _httpClient.GetFromJsonAsync<UpcSearchResult>(url, ct);
        }
        catch (HttpRequestException ex)
        {
            if (_verbose)
                Console.WriteLine($"  [UPCitemdb] Lookup error: {ex.Message}");
            return null;
        }
    }

    private async Task RateLimitAsync(CancellationToken ct)
    {
        TimeSpan elapsed = DateTime.UtcNow - _lastRequest;
        if (elapsed < RateLimit)
        {
            await Task.Delay(RateLimit - elapsed, ct);
        }
        _lastRequest = DateTime.UtcNow;
    }

    public void Dispose()
    {
        _httpClient.Dispose();
    }
}

// UPCitemdb response models

public record UpcSearchResult
{
    [JsonPropertyName("code")]
    public string? Code { get; init; }

    [JsonPropertyName("total")]
    public int Total { get; init; }

    [JsonPropertyName("offset")]
    public int Offset { get; init; }

    [JsonPropertyName("items")]
    public IReadOnlyList<UpcItem> Items { get; init; } = [];
}

public record UpcItem
{
    [JsonPropertyName("ean")]
    public string? Ean { get; init; }

    [JsonPropertyName("title")]
    public string? Title { get; init; }

    [JsonPropertyName("upc")]
    public string? Upc { get; init; }

    [JsonPropertyName("brand")]
    public string? Brand { get; init; }

    [JsonPropertyName("model")]
    public string? Model { get; init; }

    [JsonPropertyName("description")]
    public string? Description { get; init; }

    [JsonPropertyName("category")]
    public string? Category { get; init; }
}
