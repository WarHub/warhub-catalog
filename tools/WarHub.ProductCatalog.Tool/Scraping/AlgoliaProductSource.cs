using System.Globalization;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using WarHub.ProductCatalog.Tool.Configuration;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Fetches Games Workshop product data from their Algolia search index.
/// GW uses Algolia (https://algolia.com) to power their product search on warhammer.com.
/// The index 'prod-lazarus-product-{locale}' contains all products including
/// miniature kits, paints, books, and accessories.
/// </summary>
public sealed class AlgoliaProductSource : IDisposable
{
    private const string DefaultAppId = "M5ZIQZNQ2H";
    private const string DefaultSearchKey = "92c6a8254f9d34362df8e6d96475e5d8";
    private const string DefaultIndexName = "prod-lazarus-product-en-gb";
    private const int MaxHitsPerPage = 100;

    private readonly HttpClient _httpClient;
    private readonly string _appId;
    private readonly string _searchKey;
    private readonly string _indexName;
    private readonly bool _verbose;
    private readonly TimeSpan _requestDelay;
    private DateTime _lastRequest = DateTime.MinValue;

    public AlgoliaProductSource(
        string? appId = null,
        string? searchKey = null,
        string? indexName = null,
        TimeSpan? requestDelay = null,
        bool verbose = false)
    {
        _appId = appId ?? DefaultAppId;
        _searchKey = searchKey ?? DefaultSearchKey;
        _indexName = indexName ?? DefaultIndexName;
        _requestDelay = requestDelay ?? TimeSpan.FromMilliseconds(500);
        _verbose = verbose;

        _httpClient = new HttpClient();
        _httpClient.DefaultRequestHeaders.Add("x-algolia-application-id", _appId);
        _httpClient.DefaultRequestHeaders.Add("x-algolia-api-key", _searchKey);
    }

    /// <summary>
    /// Fetches all miniature kit products for a given game system.
    /// Pages through results automatically.
    /// </summary>
    public async Task<IReadOnlyList<RawProduct>> FetchProductsAsync(
        string? gameSystem = null,
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        var allProducts = new List<RawProduct>();
        int page = 0;

        while (true)
        {
            await RateLimitAsync(ct);

            AlgoliaQuery query = BuildQuery(gameSystem, page);
            AlgoliaResponse? response = await SearchAsync(query, ct);

            if (response is null || response.Hits.Count == 0)
                break;

            foreach (AlgoliaHit hit in response.Hits)
            {
                RawProduct? product = MapToRawProduct(hit);
                if (product is not null)
                {
                    allProducts.Add(product);
                }
            }

            if (_verbose)
                Console.WriteLine($"    Page {page + 1}/{response.NbPages}: {response.Hits.Count} hits (total: {response.NbHits})");

            if (maxProducts > 0 && allProducts.Count >= maxProducts)
            {
                allProducts = allProducts.Take(maxProducts).ToList();
                break;
            }

            page++;
            if (page >= response.NbPages)
                break;
        }

        return allProducts;
    }

    /// <summary>
    /// Gets total product counts by game system.
    /// </summary>
    public async Task<IReadOnlyDictionary<string, int>> GetGameSystemCountsAsync(CancellationToken ct = default)
    {
        await RateLimitAsync(ct);

        var query = new AlgoliaQuery
        {
            Query = "",
            HitsPerPage = 0,
            Page = 0,
            Filters = "productType:miniatureKit",
            Facets = ["GameSystemsRoot.lvl0"],
        };

        AlgoliaResponse? response = await SearchAsync(query, ct);
        if (response?.Facets is null)
            return new Dictionary<string, int>();

        if (response.Facets.TryGetValue("GameSystemsRoot.lvl0", out Dictionary<string, int>? gameSystems))
        {
            return gameSystems;
        }

        return new Dictionary<string, int>();
    }

    private AlgoliaQuery BuildQuery(string? gameSystem, int page)
    {
        var query = new AlgoliaQuery
        {
            Query = "",
            HitsPerPage = MaxHitsPerPage,
            Page = page,
            Filters = "productType:miniatureKit",
        };

        if (!string.IsNullOrWhiteSpace(gameSystem))
        {
            // Map game system names to Algolia facet values
            string algoliaGameSystem = MapGameSystem(gameSystem);
            query.FacetFilters = [[$"GameSystemsRoot.lvl0:{algoliaGameSystem}"]];
        }

        return query;
    }

    private async Task<AlgoliaResponse?> SearchAsync(AlgoliaQuery query, CancellationToken ct)
    {
        string url = $"https://{_appId.ToLowerInvariant()}-dsn.algolia.net/1/indexes/{_indexName}/query";

        try
        {
            HttpResponseMessage response = await _httpClient.PostAsJsonAsync(url, query, JsonOptions, ct);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadFromJsonAsync<AlgoliaResponse>(JsonOptions, ct);
        }
        catch (HttpRequestException ex)
        {
            if (_verbose) Console.WriteLine($"    Algolia error: {ex.Message}");
            return null;
        }
    }

    internal static RawProduct? MapToRawProduct(AlgoliaHit hit)
    {
        if (string.IsNullOrWhiteSpace(hit.Name))
            return null;

        // Extract game system and faction from hierarchy
        string gameSystem = "Warhammer 40,000";
        string? faction = null;

        if (hit.GameSystemsRoot is not null)
        {
            if (hit.GameSystemsRoot.TryGetValue("lvl0", out List<string>? lvl0) && lvl0.Count > 0)
            {
                gameSystem = MapAlgoliaGameSystem(lvl0[0]);
            }

            // lvl3 has faction info: "Warhammer 40,000 > Space Marines > Unit Type > Infantry"
            if (hit.GameSystemsRoot.TryGetValue("lvl3", out List<string>? lvl3) && lvl3.Count > 0)
            {
                faction = ExtractFaction(lvl3[0]);
            }
            // Fall back to lvl2 or lvl1 for faction
            else if (hit.GameSystemsRoot.TryGetValue("lvl2", out List<string>? lvl2) && lvl2.Count > 0)
            {
                faction = ExtractFaction(lvl2[0]);
            }
            else if (hit.GameSystemsRoot.TryGetValue("lvl1", out List<string>? lvl1) && lvl1.Count > 0)
            {
                faction = ExtractFaction(lvl1[0]);
            }
        }

        // Build URL from slug
        string? url = !string.IsNullOrWhiteSpace(hit.Slug)
            ? $"https://www.warhammer.com/en-GB/shop/{hit.Slug}"
            : null;

        // Get first image
        string? imageUrl = hit.Images is { Count: > 0 }
            ? $"https://www.warhammer.com{hit.Images[0]}"
            : null;

        // Determine status
        string status = DetermineStatus(hit);

        // Determine product type from Algolia data
        string? productType = ClassifyAlgoliaProductType(hit);

        // Extract the actual GW SKU from objectID format: "P-{number}-{gwSku}"
        string? gwSku = ExtractGwSku(hit.Sku ?? hit.ObjectID);

        return new RawProduct
        {
            Name = hit.Name,
            Sku = gwSku ?? hit.Sku,
            ProductCode = hit.ObjectID,
            PriceGbp = hit.Price,
            Url = url,
            ImageUrl = imageUrl,
            Description = HtmlCleaner.ToMarkdown(hit.Description),
            Manufacturer = "Games Workshop",
            GameSystem = gameSystem,
            Faction = faction,
            Status = status,
            ProductType = productType,
        };
    }

    internal static string? ClassifyAlgoliaProductType(AlgoliaHit hit)
    {
        string name = hit.Name?.ToLowerInvariant() ?? "";

        if (name.Contains("combat patrol"))
            return "combat_patrol";
        if (name.Contains("battleforce"))
            return "battleforce";
        if (name.Contains("army set") || name.Contains("army box"))
            return "army_box";
        if (name.Contains("starter set") || name.Contains("starter edition"))
            return "starter_set";

        // Use Algolia's hierarchy info: Check if it's a character based on unit type
        if (hit.GameSystemsRoot is not null)
        {
            bool isCharacter = hit.GameSystemsRoot.Values
                .SelectMany(list => list)
                .Any(v => v.Contains("Character", StringComparison.OrdinalIgnoreCase));
            if (isCharacter)
                return "character";

            bool isVehicle = hit.GameSystemsRoot.Values
                .SelectMany(list => list)
                .Any(v => v.Contains("Vehicle", StringComparison.OrdinalIgnoreCase));
            if (isVehicle)
                return "vehicle";
        }

        return null; // Let enricher classify further
    }

    internal static string DetermineStatus(AlgoliaHit hit)
    {
        if (hit.IsPreOrder)
            return "pre_order";
        if (hit.IsLastChanceToBuy)
            return "limited";
        if (hit.IsMadeToOrder)
            return "limited";
        if (hit.IsAvailableWhileStocksLast)
            return "limited";
        if (!hit.IsInStock && hit.IsAvailable)
            return "out_of_stock";
        if (!hit.IsAvailable)
            return "discontinued";
        return "current";
    }

    /// <summary>
    /// Extracts the actual Games Workshop SKU from the Algolia objectID format.
    /// Algolia uses "P-{number}-{gwSku}" or "prod{number}-{gwSku}" format.
    /// The real GW SKU is the last segment (e.g., "99120113100").
    /// </summary>
    internal static string? ExtractGwSku(string? objectId)
    {
        if (string.IsNullOrWhiteSpace(objectId))
            return null;

        // Format: "P-240927-99120113100" or "prod5100348-60040199167"
        int lastDash = objectId.LastIndexOf('-');
        if (lastDash > 0 && lastDash < objectId.Length - 1)
        {
            return objectId[(lastDash + 1)..];
        }

        return objectId;
    }

    internal static string ExtractFaction(string hierarchyValue)
    {
        // Hierarchy format: "Warhammer 40,000 > Space Marines > Unit Type > Infantry"
        string[] parts = hierarchyValue.Split(" > ", StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        // Skip the game system (first part) and unit type classification parts
        string[] skipTerms = ["Unit Type", "Infantry", "Character", "Vehicle", "Monster", "Battleline",
            "Hero", "Unit", "Artillery", "Cavalry", "Start Here", "Xenos Armies",
            "Imperium of Man", "Forces of Chaos", "Force Organisation",
            "Armies of the Old World", "Armies of Infamy"];

        foreach (string part in parts.Skip(1))
        {
            if (!skipTerms.Contains(part, StringComparer.OrdinalIgnoreCase))
            {
                return part;
            }
        }

        return "General";
    }

    internal static string MapGameSystem(string gameSystem)
    {
        return gameSystem switch
        {
            "Warhammer 40,000" or "Warhammer 40K" => "Warhammer 40,000",
            "Age of Sigmar" => "Age of Sigmar",
            "Horus Heresy" or "The Horus Heresy" => "The Horus Heresy",
            "Middle-earth" => "Middle-Earth",
            "The Old World" => "The Old World",
            "Other Games" => "Other Games",
            _ => gameSystem,
        };
    }

    internal static string MapAlgoliaGameSystem(string algoliaGameSystem)
    {
        return algoliaGameSystem switch
        {
            "Warhammer 40,000" => "Warhammer 40,000",
            "Age of Sigmar" => "Age of Sigmar",
            "The Horus Heresy" => "Horus Heresy",
            "Middle-Earth" => "Middle-earth",
            "The Old World" => "The Old World",
            "Other Games" => "Other Games",
            _ => algoliaGameSystem,
        };
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
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}

// Algolia request/response models

internal sealed class AlgoliaQuery
{
    [JsonPropertyName("query")]
    public string Query { get; set; } = "";

    [JsonPropertyName("hitsPerPage")]
    public int HitsPerPage { get; set; } = 100;

    [JsonPropertyName("page")]
    public int Page { get; set; }

    [JsonPropertyName("filters")]
    public string? Filters { get; set; }

    [JsonPropertyName("facetFilters")]
    public List<List<string>>? FacetFilters { get; set; }

    [JsonPropertyName("facets")]
    public List<string>? Facets { get; set; }
}

internal sealed class AlgoliaResponse
{
    [JsonPropertyName("hits")]
    public List<AlgoliaHit> Hits { get; set; } = [];

    [JsonPropertyName("nbHits")]
    public int NbHits { get; set; }

    [JsonPropertyName("page")]
    public int Page { get; set; }

    [JsonPropertyName("nbPages")]
    public int NbPages { get; set; }

    [JsonPropertyName("hitsPerPage")]
    public int HitsPerPage { get; set; }

    [JsonPropertyName("facets")]
    public Dictionary<string, Dictionary<string, int>>? Facets { get; set; }
}

internal sealed class AlgoliaHit
{
    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("slug")]
    public string? Slug { get; set; }

    [JsonPropertyName("sku")]
    public string? Sku { get; set; }

    [JsonPropertyName("price")]
    public decimal? Price { get; set; }

    [JsonPropertyName("description")]
    public string? Description { get; set; }

    [JsonPropertyName("images")]
    public List<string>? Images { get; set; }

    [JsonPropertyName("material")]
    public List<string>? Material { get; set; }

    [JsonPropertyName("productType")]
    public string? ProductType { get; set; }

    [JsonPropertyName("isInStock")]
    public bool IsInStock { get; set; }

    [JsonPropertyName("isAvailable")]
    public bool IsAvailable { get; set; } = true;

    [JsonPropertyName("isPreOrder")]
    public bool IsPreOrder { get; set; }

    [JsonPropertyName("isNewRelease")]
    public bool IsNewRelease { get; set; }

    [JsonPropertyName("isLastChanceToBuy")]
    public bool IsLastChanceToBuy { get; set; }

    [JsonPropertyName("isMadeToOrder")]
    public bool IsMadeToOrder { get; set; }

    [JsonPropertyName("isWebstoreExclusive")]
    public bool IsWebstoreExclusive { get; set; }

    [JsonPropertyName("isAvailableWhileStocksLast")]
    public bool IsAvailableWhileStocksLast { get; set; }

    [JsonPropertyName("statusCode")]
    public string? StatusCode { get; set; }

    [JsonPropertyName("objectID")]
    public string? ObjectID { get; set; }

    [JsonPropertyName("GameSystemsRoot")]
    public Dictionary<string, List<string>>? GameSystemsRoot { get; set; }

    [JsonPropertyName("ctPrice")]
    public AlgoliaPrice? CtPrice { get; set; }
}

internal sealed class AlgoliaPrice
{
    [JsonPropertyName("centAmount")]
    public int CentAmount { get; set; }

    [JsonPropertyName("currencyCode")]
    public string? CurrencyCode { get; set; }

    [JsonPropertyName("fractionDigits")]
    public int FractionDigits { get; set; }
}
