using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Enriches products with EAN codes from UPCitemdb API.
/// EAN data is stored inline on products (Ean + EanSource fields) — no separate cache file.
/// Products with EanSource already set are skipped to avoid re-querying.
/// Manufacturer-aware: uses the correct manufacturer name in search queries.
/// </summary>
public sealed class EanEnricher : IDisposable
{
    private readonly UpcItemDbClient _client;
    private readonly bool _verbose;
    private readonly int _budget;

    /// <summary>All Games Workshop EANs start with this GS1 company prefix.</summary>
    internal const string GwEanPrefix = "5011921";

    private int _apiCalls;
    private int _alreadyResolved;
    private int _enriched;
    private int _budgetSkipped;
    private int _rateLimitSkipped;

    /// <summary>Number of API calls made so far.</summary>
    public int ApiCalls => _apiCalls;

    /// <summary>True if the budget has been exhausted (0 = unlimited) or the API is rate-limited.</summary>
    public bool BudgetExhausted => (_budget > 0 && _apiCalls >= _budget) || _client.IsRateLimited;

    /// <param name="budget">Max API calls per run (0 = unlimited).</param>
    public EanEnricher(UpcItemDbClient client, bool verbose = false, int budget = 0)
    {
        _client = client;
        _verbose = verbose;
        _budget = budget;
    }

    /// <summary>
    /// Enriches a list of products with EAN codes via UPCitemdb.
    /// Skips products that already have Ean or EanSource set.
    /// Returns new product list with Ean and EanSource fields populated.
    /// </summary>
    public async Task<IReadOnlyList<Product>> EnrichAsync(
        IReadOnlyList<Product> products,
        string manufacturerName,
        CancellationToken ct = default)
    {
        var result = new List<Product>(products.Count);

        foreach (Product product in products)
        {
            ct.ThrowIfCancellationRequested();

            // Already has EAN or has been searched before
            if (!string.IsNullOrWhiteSpace(product.Ean) || !string.IsNullOrWhiteSpace(product.EanSource))
            {
                if (!string.IsNullOrWhiteSpace(product.EanSource))
                    _alreadyResolved++;
                result.Add(product);
                continue;
            }

            // Check budget and rate limit before making API call
            if (BudgetExhausted)
            {
                if (_client.IsRateLimited)
                    _rateLimitSkipped++;
                else
                    _budgetSkipped++;
                result.Add(product);
                continue;
            }

            // Query UPCitemdb API
            string? ean = await SearchEanAsync(product.Name, manufacturerName, ct);
            _apiCalls++;

            if (!string.IsNullOrWhiteSpace(ean))
            {
                result.Add(product with { Ean = ean, EanSource = "upcitemdb" });
                _enriched++;
            }
            else
            {
                result.Add(product with { EanSource = "not_found" });
            }
        }

        return result;
    }

    /// <summary>
    /// Searches UPCitemdb by product name with manufacturer context.
    /// For Games Workshop, filters to the GW EAN prefix (5011921).
    /// For other manufacturers, accepts any valid EAN result.
    /// </summary>
    internal async Task<string?> SearchEanAsync(string productName, string manufacturerName, CancellationToken ct)
    {
        bool isGw = manufacturerName.Equals("Games Workshop", StringComparison.OrdinalIgnoreCase);

        // Search with manufacturer name to narrow results
        string query = $"{manufacturerName} {productName}";
        UpcSearchResult? result = await _client.SearchAsync(query, ct);

        if (result is null || result.Items.Count == 0)
            return null;

        IReadOnlyList<UpcItem> candidates;
        if (isGw)
        {
            // Filter to GW EAN prefix for Games Workshop products
            candidates = result.Items
                .Where(item => item.Ean?.StartsWith(GwEanPrefix, StringComparison.Ordinal) == true)
                .ToList();
        }
        else
        {
            // For other manufacturers, accept any item with a valid EAN
            candidates = result.Items
                .Where(item => !string.IsNullOrWhiteSpace(item.Ean))
                .ToList();
        }

        if (candidates.Count == 0)
            return null;

        // Find best match by name similarity
        UpcItem? bestMatch = FindBestNameMatch(productName, candidates);
        return bestMatch?.Ean;
    }

    /// <summary>
    /// Finds the UPC item whose title best matches the product name.
    /// Uses normalized comparison with token matching.
    /// </summary>
    internal static UpcItem? FindBestNameMatch(string productName, IReadOnlyList<UpcItem> candidates)
    {
        if (candidates.Count == 0)
            return null;

        string normalizedProduct = NormalizeName(productName);
        string[] productTokens = normalizedProduct.Split(' ', StringSplitOptions.RemoveEmptyEntries);

        UpcItem? best = null;
        double bestScore = -1;

        foreach (UpcItem candidate in candidates)
        {
            string candidateTitle = NormalizeName(candidate.Title ?? "");
            double score = CalculateMatchScore(productTokens, candidateTitle);

            if (score > bestScore)
            {
                bestScore = score;
                best = candidate;
            }
        }

        // Require minimum 50% token match to avoid false positives
        return bestScore >= 0.5 ? best : null;
    }

    /// <summary>
    /// Calculates a match score (0.0 to 1.0) between product name tokens and a candidate title.
    /// Higher score means better match.
    /// </summary>
    internal static double CalculateMatchScore(string[] productTokens, string candidateTitle)
    {
        if (productTokens.Length == 0)
            return 0;

        int matched = 0;
        foreach (string token in productTokens)
        {
            if (candidateTitle.Contains(token, StringComparison.OrdinalIgnoreCase))
                matched++;
        }

        return (double)matched / productTokens.Length;
    }

    /// <summary>
    /// Normalizes a product name for comparison: lowercase, remove common noise words,
    /// remove special characters.
    /// </summary>
    internal static string NormalizeName(string name)
    {
        // Remove common noise from UPCitemdb titles like "(B08ZJSRZ47)" Amazon ASINs
        string cleaned = System.Text.RegularExpressions.Regex.Replace(name, @"\(B\w{9,}\)", "");
        // Remove "Games Workshop", "Warhammer 40K", etc.
        cleaned = cleaned.Replace("Games Workshop", "", StringComparison.OrdinalIgnoreCase);
        cleaned = cleaned.Replace("Warhammer 40,000", "", StringComparison.OrdinalIgnoreCase);
        cleaned = cleaned.Replace("Warhammer 40K", "", StringComparison.OrdinalIgnoreCase);
        cleaned = cleaned.Replace("Warhammer", "", StringComparison.OrdinalIgnoreCase);
        cleaned = cleaned.Replace("Age of Sigmar", "", StringComparison.OrdinalIgnoreCase);
        // Remove special characters
        cleaned = System.Text.RegularExpressions.Regex.Replace(cleaned, @"[^\w\s]", " ");
        // Collapse whitespace
        cleaned = System.Text.RegularExpressions.Regex.Replace(cleaned, @"\s+", " ");
        return cleaned.Trim().ToLowerInvariant();
    }

    /// <summary>
    /// Logs enrichment summary stats.
    /// </summary>
    public void LogSummary()
    {
        if (_verbose)
        {
            Console.WriteLine($"\n  [EAN Enrichment Summary]");
            Console.WriteLine($"    API calls:        {_apiCalls}{(_budget > 0 ? $" / {_budget} budget" : "")}");
            Console.WriteLine($"    Already resolved: {_alreadyResolved}");
            Console.WriteLine($"    Enriched:         {_enriched}");
            if (_budgetSkipped > 0)
                Console.WriteLine($"    Budget skipped:   {_budgetSkipped}");
            if (_rateLimitSkipped > 0)
                Console.WriteLine($"    Rate-limit skipped: {_rateLimitSkipped}");
        }
    }

    public void Dispose()
    {
        _client.Dispose();
    }
}
