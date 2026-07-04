using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Scraping;

/// <summary>
/// Fetches product data from Corvus Belli's store via their AWS AppSync GraphQL API.
/// The store at store.corvusbelli.com uses an Angular SPA backed by AppSync.
/// </summary>
public sealed class CorvusBelliProductSource : IDisposable
{
    private const string GraphQlEndpoint =
        "https://aiscbwsb6vb3xbysk57tnk3miy.appsync-api.eu-west-1.amazonaws.com/graphql";

    private const string ApiKey = "da2-xxsxwilwsvhuhauw4d7e3qhocy";

    private static readonly string ProductsQuery = """
        query products($category: ICategory!, $lang: LANG!, $filters: [INameValue], $page: Int, $sort: PRODUCT_SORT, $rating: Int) {
            products: listProducts(category: $category, lang: $lang, filters: $filters, page: $page, sort: $sort, rating: $rating) {
                products {
                    availability { from, to }
                    itemAvailability
                    price
                    seo
                    shortname
                    reference
                    labels
                    outstock
                    rating { value, votes }
                    slug
                    preorder
                    category { cat, game, type }
                    img {
                        nextgen
                        front { title, img, description }
                    }
                    meta {
                        groups { group, name }
                        options { group, option, outstock, reference, type }
                    }
                }
                pages
                currentPage
                total
            }
        }
        """;

    private readonly HttpClient _httpClient;
    private readonly bool _verbose;
    private readonly TimeSpan _requestDelay;
    private DateTime _lastRequest = DateTime.MinValue;

    public CorvusBelliProductSource(bool verbose = false, TimeSpan? requestDelay = null)
    {
        _verbose = verbose;
        _requestDelay = requestDelay ?? TimeSpan.FromMilliseconds(500);

        _httpClient = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        });
        _httpClient.DefaultRequestHeaders.Add("x-api-key", ApiKey);
        _httpClient.DefaultRequestHeaders.Accept.ParseAdd("application/json");
    }

    public async Task<IReadOnlyList<RawProduct>> FetchAllProductsAsync(
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        return await FetchProductsForGameAsync("infinity", "wargames", "Infinity", maxProducts, ct);
    }

    public async Task<IReadOnlyList<RawProduct>> FetchProductsForGameAsync(
        string apiGame,
        string apiType,
        string gameSystemName,
        int maxProducts = 0,
        CancellationToken ct = default)
    {
        var allProducts = new List<RawProduct>();

        int page = 1;
        int totalPages = 1;

        while (page <= totalPages)
        {
            await RateLimitAsync(ct);

            var requestBody = new
            {
                query = ProductsQuery,
                variables = new
                {
                    category = new { type = apiType, game = apiGame },
                    lang = "en",
                    filters = Array.Empty<object>(),
                    page,
                }
            };

            if (_verbose) Console.WriteLine($"    Fetching: Corvus Belli {apiGame} page {page}");

            try
            {
                string json = JsonSerializer.Serialize(requestBody);
                using var content = new StringContent(json, Encoding.UTF8, "application/json");
                using HttpResponseMessage response = await _httpClient.PostAsync(GraphQlEndpoint, content, ct);
                response.EnsureSuccessStatusCode();

                CbGraphQlResponse? gqlResponse =
                    await response.Content.ReadFromJsonAsync<CbGraphQlResponse>(JsonOptions, ct);

                CbProductList? productList = gqlResponse?.Data?.Products;
                if (productList?.Products is null || productList.Products.Count == 0)
                    break;

                totalPages = productList.GetPages();

                foreach (CbProduct product in productList.Products)
                {
                    RawProduct? rawProduct = MapToRawProduct(product, apiGame, gameSystemName);
                    if (rawProduct is not null)
                        allProducts.Add(rawProduct);
                }

                if (_verbose)
                    Console.WriteLine($"      Page {page}/{totalPages}: {productList.Products.Count} products (total: {allProducts.Count}/{productList.GetTotal()})");

                if (maxProducts > 0 && allProducts.Count >= maxProducts)
                {
                    allProducts = allProducts.Take(maxProducts).ToList();
                    return allProducts;
                }

                page++;
            }
            catch (Exception ex) when (ex is HttpRequestException or JsonException or FormatException)
            {
                if (_verbose) Console.WriteLine($"      Error: {ex.GetType().Name}: {ex.Message}");
                break;
            }
        }

        return allProducts;
    }

    internal static RawProduct? MapToRawProduct(CbProduct product, string game, string gameSystemName = "Infinity")
    {
        if (string.IsNullOrWhiteSpace(product.Shortname))
            return null;

        string name = WebUtility.HtmlDecode(product.Shortname);
        string? faction = ExtractFaction(product.Seo, name, gameSystemName);
        string? imageUrl = BuildImageUrl(product.Img, product.Slug);
        string status = DetermineStatus(product);
        string categoryType = gameSystemName == "Aristeia!" ? "boardgames" : "wargames";
        string? url = !string.IsNullOrWhiteSpace(product.Slug)
            ? $"https://store.corvusbelli.com/en/{categoryType}/{game}/{product.Slug}"
            : null;

        return new RawProduct
        {
            Name = name,
            Sku = product.Reference,
            PriceEur = product.Price,
            Url = url,
            ImageUrl = imageUrl,
            Manufacturer = "Corvus Belli",
            GameSystem = gameSystemName,
            Faction = faction,
            Status = status,
            ProductType = product.Category?.Cat,
        };
    }

    internal static string? ExtractFaction(List<string>? seo, string name, string gameSystem = "Infinity")
    {
        string[] factions = gameSystem switch
        {
            "Warcrow" =>
            [
                "Northern Tribes", "Hegemony of Embersig", "Ahlwardt Ice Bears",
                "Varank Nasai", "Scions of Yaldabaoth",
            ],
            _ =>
            [
                "PanOceania", "Yu Jing", "Ariadna", "Haqqislam",
                "Nomads", "Combined Army", "ALEPH", "Tohaa",
                "O-12", "NA2",
            ],
        };

        // Aristeia! has no factions
        if (gameSystem == "Aristeia!")
            return null;

        // Check SEO fields first (more reliable)
        if (seo is not null)
        {
            foreach (string seoText in seo)
            {
                foreach (string faction in factions)
                {
                    if (seoText.Contains(faction, StringComparison.OrdinalIgnoreCase))
                        return faction;
                }
            }
        }

        // Fallback to product name
        foreach (string faction in factions)
        {
            if (name.Contains(faction, StringComparison.OrdinalIgnoreCase))
                return faction;
        }

        return null;
    }

    internal static string? BuildImageUrl(CbImage? img, string? slug)
    {
        string? imgFile = img?.Front?.Img;
        if (string.IsNullOrWhiteSpace(imgFile))
            return null;

        // Corvus Belli serves images from their CDN
        bool isNextGen = img?.NextGen?.ValueKind == JsonValueKind.True;
        string extension = isNextGen ? "webp" : "png";
        return $"https://store.corvusbelli.com/media/catalog/product/{imgFile}";
    }

    internal static string DetermineStatus(CbProduct product)
    {
        if (product.Preorder is not null)
            return "pre_order";
        if (product.Outstock)
            return "out_of_stock";
        return "current";
    }

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

// GraphQL response models for Corvus Belli AppSync API

internal sealed class CbGraphQlResponse
{
    [JsonPropertyName("data")]
    public CbGraphQlData? Data { get; set; }
}

internal sealed class CbGraphQlData
{
    [JsonPropertyName("products")]
    public CbProductList? Products { get; set; }
}

internal sealed class CbProductList
{
    [JsonPropertyName("products")]
    public List<CbProduct>? Products { get; set; }

    [JsonPropertyName("pages")]
    public JsonElement Pages { get; set; }

    [JsonPropertyName("currentPage")]
    public JsonElement CurrentPage { get; set; }

    [JsonPropertyName("total")]
    public JsonElement Total { get; set; }

    public int GetPages() => ParseJsonInt(Pages);
    public int GetCurrentPage() => ParseJsonInt(CurrentPage);
    public int GetTotal() => ParseJsonInt(Total);

    private static int ParseJsonInt(JsonElement el)
    {
        return el.ValueKind switch
        {
            JsonValueKind.Number when el.TryGetInt32(out int i) => i,
            JsonValueKind.Number => (int)el.GetDouble(),
            JsonValueKind.String when int.TryParse(el.GetString(), out int v) => v,
            _ => 0,
        };
    }
}

internal sealed class CbProduct
{
    [JsonPropertyName("shortname")]
    public string? Shortname { get; set; }

    [JsonPropertyName("reference")]
    public string? Reference { get; set; }

    [JsonPropertyName("slug")]
    public string? Slug { get; set; }

    [JsonPropertyName("price")]
    public decimal? Price { get; set; }

    [JsonPropertyName("seo")]
    public List<string>? Seo { get; set; }

    [JsonPropertyName("labels")]
    public List<string>? Labels { get; set; }

    [JsonPropertyName("outstock")]
    public bool Outstock { get; set; }

    [JsonPropertyName("preorder")]
    public object? Preorder { get; set; }

    [JsonPropertyName("category")]
    public CbCategory? Category { get; set; }

    [JsonPropertyName("img")]
    public CbImage? Img { get; set; }

    [JsonPropertyName("availability")]
    public CbAvailability? Availability { get; set; }

    [JsonPropertyName("itemAvailability")]
    public string? ItemAvailability { get; set; }

    [JsonPropertyName("rating")]
    public CbRating? Rating { get; set; }

    [JsonPropertyName("meta")]
    public CbMeta? Meta { get; set; }
}

internal sealed class CbCategory
{
    [JsonPropertyName("cat")]
    public string? Cat { get; set; }

    [JsonPropertyName("game")]
    public string? Game { get; set; }

    [JsonPropertyName("type")]
    public string? Type { get; set; }
}

internal sealed class CbImage
{
    [JsonPropertyName("nextgen")]
    public JsonElement? NextGen { get; set; }

    [JsonPropertyName("front")]
    public CbImageFront? Front { get; set; }
}

internal sealed class CbImageFront
{
    [JsonPropertyName("title")]
    public string? Title { get; set; }

    [JsonPropertyName("img")]
    public string? Img { get; set; }

    [JsonPropertyName("description")]
    public string? Description { get; set; }
}

internal sealed class CbAvailability
{
    [JsonPropertyName("from")]
    public string? From { get; set; }

    [JsonPropertyName("to")]
    public string? To { get; set; }
}

internal sealed class CbRating
{
    [JsonPropertyName("value")]
    public double Value { get; set; }

    [JsonPropertyName("votes")]
    public int Votes { get; set; }
}

internal sealed class CbMeta
{
    [JsonPropertyName("groups")]
    public List<CbMetaGroup>? Groups { get; set; }

    [JsonPropertyName("options")]
    public List<CbMetaOption>? Options { get; set; }
}

internal sealed class CbMetaGroup
{
    [JsonPropertyName("group")]
    public string? Group { get; set; }

    [JsonPropertyName("name")]
    public string? Name { get; set; }
}

internal sealed class CbMetaOption
{
    [JsonPropertyName("group")]
    public string? Group { get; set; }

    [JsonPropertyName("option")]
    public string? Option { get; set; }

    [JsonPropertyName("outstock")]
    public bool Outstock { get; set; }

    [JsonPropertyName("reference")]
    public string? Reference { get; set; }

    [JsonPropertyName("type")]
    public string? Type { get; set; }
}
