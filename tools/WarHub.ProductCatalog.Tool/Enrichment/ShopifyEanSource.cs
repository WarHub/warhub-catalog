using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Fetches EAN (barcode) data from Shopify stores (both retailers and manufacturer stores).
/// Shopify stores expose product data via /products.json and /products/{handle}.json,
/// where individual product endpoints include variant barcodes that list endpoints omit.
/// </summary>
public sealed class ShopifyEanSource : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly bool _verbose;

    /// <summary>
    /// Default Shopify stores known to carry wargaming products with barcodes.
    /// Includes GW retailers, manufacturer stores, distributor stores,
    /// and multi-brand hobby retailers (for Corvus Belli and Para Bellum coverage).
    /// </summary>
    public static readonly IReadOnlyList<string> DefaultStores =
    [
        // Manufacturer stores (small, high match rate — process first)
        "https://steamforged.com",
        "https://giveusyourmoneypleasethankyou-wyrd.com",
        // Note: store.warlordgames.com omitted — 0% barcode rate (all variants have empty barcodes)
        // GW retailers (large catalogs, broad coverage)
        "https://goblingaming.co.uk",
        "https://dicesaloon.co.uk",
        // Distributor (AMG, CMON, Mantic coverage)
        "https://www.asmodee.co.uk",
        // Multi-brand retailers (Corvus Belli and Para Bellum coverage)
        "https://bellfordtoysandhobbies.com",
        "https://tistaminis.com",
        "https://www.elrikshobbies.com",
    ];

    /// <summary>
    /// Stores where only specific collections should be fetched (avoids paginating huge unrelated catalogs).
    /// Key: base store URL, Value: collection handles to fetch.
    /// </summary>
    private static readonly IReadOnlyDictionary<string, IReadOnlyList<string>> CollectionStores =
        new Dictionary<string, IReadOnlyList<string>>(StringComparer.OrdinalIgnoreCase)
        {
            // Mighty Lancer Games: page-based pagination fails, since_id too slow over 10k+ products.
            // Fetch only Warlord-related collections (~400 products, ~85% barcode rate).
            ["https://www.mightylancergames.co.uk"] =
            [
                "konflikt-47", "black-powder", "hail-caesar", "victory-at-sea",
                "black-seas", "blood-red-skies", "warlords-of-erehwon", "judge-dredd",
                "beyond-the-gates-of-antares", "cruel-seas", "spqr", "strontium-dog",
                "achtung-panzer", "epic-battles", "pike-and-shotte",
            ],
            // Entoyment: huge multi-brand wargaming retailer (10k+ total products).
            // Collection-based fetching targets specific game system collections with high barcode rates.
            // Covers: Warlord (~528), Corvus Belli (~482), AMG (~221), Mantic (~79), CMON (~165), Para Bellum (~199)
            ["https://entoyment.co.uk"] =
            [
                // Warlord Games — Bolt Action, Black Powder, Hail Caesar, and more
                "bolt-action", "bolt-action-scenery",
                "achtung-panzer", "konflikt-47",
                "black-powder-napoleonic-wars", "black-powder-anglo-zulu-war",
                "black-powder-french-indian-war", "black-powder-war-of-the-spanish-succession",
                "black-powder-getting-started",
                "black-seas-1",
                "epic-battles-american-civil-war", "epic-battles-napoleonic-wars",
                "epic-battles-pike-shotte", "epic-battles-revolution",
                "hail-caesar-caesarian-romans", "hail-caesar-classical-greece",
                "hail-caesar-dark-ages", "hail-caesar-enemies-of-rome",
                "hail-caesar-getting-started", "hail-caesar-imperial-romans",
                "hail-caesar-epic-battles", "hail-caesar-the-pyrrhic-wars",
                "judge-dredd-rpg",
                // Corvus Belli — Infinity factions
                "infinity-aleph", "infinity-ariadna", "infinity-combined-army",
                "infinity-haqqislam", "infinity-jsa", "infinity-na2",
                "infinity-1", "infinity-o-12", "infinity-pan-oceania",
                "infinity-tohaa", "infinity-yu-jing",
                "infinity-mercenaries", "infinity-getting-started", "infinity-pre-orders",
                // AMG — Marvel Crisis Protocol, Star Wars Shatterpoint, Star Wars Legion
                "marvel-crisis-protocol",
                "star-wars-shatterpoint",
                "star-wars-legion",
                // Mantic — Kings of War
                "kings-of-war-4th-edition",
                // CMON — A Song of Ice and Fire (165 products with barcodes, no SKUs — uses title matching)
                "a_song_of_ice_-_fire_miniatures_game",
                // Para Bellum — Conquest: The Last Argument of Kings
                "conquest-last-argument-of-kings",
            ],
            // Flipside Gaming: massive US multi-brand retailer (31k+ products, 100% barcode fill).
            // Top source for Warlord, Corvus Belli, Mantic, AMG, and Para Bellum.
            ["https://flipsidegaming.com"] =
            [
                "warlord-games",        // ~931 Warlord products
                "infinity",             // ~681 Corvus Belli products
                "mantic-games",         // ~471 Mantic products
                "marvel-crisis-protocol", // ~160 AMG MCP products
                "star-wars-shatterpoint", // ~51 AMG Shatterpoint products
                "conquest",             // ~282 Para Bellum Conquest products
            ],
            // Athena Games: UK multi-brand retailer with 100% barcode fill.
            // Strong Warlord (760+), Mantic (339+), and AMG coverage.
            ["https://athenagames.com"] =
            [
                "warlord-games",        // ~760 Warlord products
                "bolt-action",          // ~368 (overlaps with warlord-games)
                "black-powder",         // ~95 Warlord Black Powder
                "hail-caesar",          // ~56 Warlord Hail Caesar
                "konflikt-47",          // ~32 Warlord Konflikt '47
                "blood-red-skies",      // ~15 Warlord Blood Red Skies
                "mantic-games",         // ~339 Mantic products
                "marvel-crisis-protocol", // ~152 AMG MCP products
                "star-wars-shatterpoint", // ~50 AMG Shatterpoint
                "star-wars-legion",     // ~178 AMG Legion
                "a-song-of-ice-fire-tabletop-miniatures-game", // ~20 CMON
                "kings-of-war",         // ~56 Mantic KoW
                "deadzone-mantic-games", // ~31 Mantic Deadzone
                "firefight-mantic-games", // ~31 Mantic Firefight
                "armada-mantic-games",  // ~18 Mantic Armada
                "conquest-the-last-argument-of-kings", // ~51 Para Bellum Conquest
            ],
            // 401 Games: large Canadian multi-brand retailer (store.401games.ca).
            // Carries Corvus Belli (~635), AMG (~451), CMON (~181), Para Bellum (~28).
            // No Mantic, Warlord, or GW.
            ["https://store.401games.ca"] =
            [
                "corvus-belli-infinity",  // ~635 Corvus Belli Infinity products
                "corvus-belli-warcrow",   // ~61 Corvus Belli Warcrow products
                "atomic-mass-games",      // ~451 AMG (MCP + Legion + Shatterpoint)
                "cmon-a-song-of-ice-and-fire-tabletop-miniatures-game", // ~181 CMON ASOIAF
                "conquest-the-last-argument-of-kings", // ~28 Para Bellum Conquest
            ],
            // LVL Up Gaming: UK multi-brand retailer (lvlupgaming.co.uk).
            // Strong GW coverage (confirmed real 5011921xxx barcodes for Horus Heresy),
            // plus Mantic (~701), Corvus Belli (~484), Para Bellum (~400), AMG.
            // Note: Warlord products have SKU duplicated in barcode field (not real EANs) — excluded.
            ["https://www.lvlupgaming.co.uk"] =
            [
                // GW — focus on gap areas (Horus Heresy, Old World, Middle-earth, specialist games)
                "horus-heresy",           // ~145 GW Horus Heresy (confirmed barcodes)
                "the-old-world",          // ~192 GW The Old World
                "legions-imperialis",     // ~87 GW Legions Imperialis
                "kill-team",              // ~77 GW Kill Team
                "necromunda",             // ~96 GW Necromunda
                "warcry",                 // ~22 GW Warcry
                "warhammer-underworlds",  // ~31 GW Warhammer Underworlds
                // Mantic — large collection, good for filling 1,008 pending gap
                "mantic-games",           // ~701 Mantic products
                "kings-of-war",           // ~362 Mantic Kings of War
                "deadzone",               // ~36 Mantic Deadzone
                // Corvus Belli
                "corvus-belli-infinity",  // ~484 CB Infinity products
                // Para Bellum
                "conquest",               // ~400 Para Bellum Conquest products
                // AMG
                "marvel-crisis-protocol",  // ~146 AMG MCP products
                "star-wars-legion-1",      // ~75 AMG Legion
                "star-wars-shatterpoint",  // ~12 AMG Shatterpoint
            ],
            // Merlin's Miniatures: UK retailer specializing in GW (merlinsminiatures.co.uk).
            // Confirmed real GW barcodes (5011921xxx). Carries new and pre-owned GW,
            // plus Warlord historicals and Mantic. SKU matching filters to relevant products.
            ["https://merlinsminiatures.co.uk"] =
            [
                // GW — boxed products with barcodes
                "horus-heresy",                     // ~109 GW Horus Heresy (confirmed barcodes)
                "legions-imperialis",               // ~90 GW Legions Imperialis
                "kill-team",                        // ~81 GW Kill Team
                "middle-earth",                     // ~32 GW Middle-earth
                "games-workshop-pre-orders",        // ~33 current GW releases
                "games-workshop-online-only-range", // ~56 GW web-exclusive products
                // Warlord historicals (barcode availability varies)
                "bolt-action",                      // ~325 Warlord Bolt Action
                "black-powder",                     // ~126 Warlord Black Powder
                "epic-battles",                     // ~117 Warlord Epic Battles
                "hail-caesar",                      // ~56 Warlord Hail Caesar
                // Mantic
                "kings-of-war",                     // ~28 Mantic Kings of War
                "deadzone",                         // ~31 Mantic Deadzone
            ],
        };

    // Delay between individual requests to a single store
    private static readonly TimeSpan RequestDelay = TimeSpan.FromMilliseconds(350);

    // Max concurrent detail page requests per store (balances speed vs rate limits)
    private const int MaxConcurrentDetailRequests = 3;

    public ShopifyEanSource(bool verbose = false)
    {
        _verbose = verbose;
        _httpClient = new HttpClient();
        _httpClient.DefaultRequestHeaders.Add("Accept", "application/json");
        _httpClient.DefaultRequestHeaders.Add("User-Agent", "WarHub-ProductCatalog/1.0");
        _httpClient.Timeout = TimeSpan.FromSeconds(30);
    }

    /// <summary>
    /// Fetches EAN barcodes from Shopify stores and returns a dictionary of SKU → (Ean, Source).
    /// Only fetches barcodes for SKUs not in the alreadyResolved set.
    /// When catalogSkus is provided, only fetches detail pages for products whose SKU matches the catalog.
    /// </summary>
    public async Task<Dictionary<string, ShopifyEanResult>> FetchEansAsync(
        IReadOnlySet<string>? alreadyResolved = null,
        IReadOnlyList<string>? storeUrls = null,
        IReadOnlySet<string>? catalogSkus = null,
        CancellationToken ct = default)
    {
        storeUrls ??= DefaultStores;
        alreadyResolved ??= new HashSet<string>();
        var results = new Dictionary<string, ShopifyEanResult>(StringComparer.OrdinalIgnoreCase);

        foreach (string storeUrl in storeUrls)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                Dictionary<string, ShopifyEanResult> storeResults;

                // Use collection-based fetching for stores that don't support global pagination
                if (CollectionStores.TryGetValue(storeUrl, out IReadOnlyList<string>? collections))
                {
                    storeResults = await FetchFromCollectionsAsync(
                        alreadyResolved, results, storeUrl, collections, catalogSkus, ct);
                }
                else
                {
                    storeResults = await FetchFromStoreAsync(
                        alreadyResolved, results, storeUrl, catalogSkus, ct);
                }

                foreach (var (sku, eanResult) in storeResults)
                    results.TryAdd(sku, eanResult);
            }
            catch (Exception ex)
            {
                if (_verbose)
                    Console.WriteLine($"  [Shopify] Error scraping {storeUrl}: {ex.Message}");
            }
        }

        // When using default stores, also process collection-based stores (they're not in DefaultStores).
        // When specific storeUrls are provided (e.g., from workflow matrix), only process those stores.
        bool isUsingDefaults = storeUrls == DefaultStores;
        if (isUsingDefaults)
        {
            foreach (var (baseUrl, collections) in CollectionStores)
            {
                ct.ThrowIfCancellationRequested();
                try
                {
                    Dictionary<string, ShopifyEanResult> storeResults =
                        await FetchFromCollectionsAsync(alreadyResolved, results, baseUrl, collections, catalogSkus, ct);
                    foreach (var (sku, eanResult) in storeResults)
                        results.TryAdd(sku, eanResult);
                }
                catch (Exception ex)
                {
                    if (_verbose)
                        Console.WriteLine($"  [Shopify] Error scraping {baseUrl} collections: {ex.Message}");
                }
            }
        }

        if (_verbose)
            Console.WriteLine($"  [Shopify] Total: {results.Count} EAN barcodes found");

        return results;
    }

    private async Task<Dictionary<string, ShopifyEanResult>> FetchFromStoreAsync(
        IReadOnlySet<string> alreadyResolved,
        Dictionary<string, ShopifyEanResult> alreadyFound,
        string storeUrl,
        IReadOnlySet<string>? catalogSkus,
        CancellationToken ct)
    {
        string storeName = new Uri(storeUrl).Host;
        if (_verbose) Console.WriteLine($"\n  [Shopify] Fetching products from {storeName}...");

        var results = new Dictionary<string, ShopifyEanResult>(StringComparer.OrdinalIgnoreCase);

        // Step 1: List all products using page-based pagination
        List<ShopifyProductHandle> needed = [];
        int page = 1;
        int totalProducts = 0;
        int skippedNotInCatalog = 0;

        while (true)
        {
            ct.ThrowIfCancellationRequested();
            ShopifyProductList? list = await GetJsonWithRetryAsync<ShopifyProductList>(
                $"{storeUrl}/products.json?limit=250&page={page}", ct);

            if (list?.Products is null || list.Products.Count == 0)
                break;

            foreach (ShopifyListProduct product in list.Products)
            {
                totalProducts++;
                string? rawSku = product.Variants?.FirstOrDefault()?.Sku;
                string? sku = NormalizeSku(rawSku);
                if (sku is null)
                    continue;

                // Skip products already resolved or found in this run
                if (alreadyResolved.Contains(sku) || alreadyFound.ContainsKey(sku))
                    continue;

                // Skip products not in our catalog (avoids fetching detail pages for unrelated products)
                if (catalogSkus is not null && !catalogSkus.Contains(sku))
                {
                    skippedNotInCatalog++;
                    continue;
                }

                needed.Add(new ShopifyProductHandle(product.Handle!, sku, product.Title ?? ""));
            }

            if (list.Products.Count < 250)
                break;

            page++;
            await Task.Delay(RequestDelay, ct);
        }

        if (_verbose)
        {
            Console.WriteLine($"  [Shopify] {storeName}: {totalProducts} products, {needed.Count} need barcode lookup");
            if (skippedNotInCatalog > 0)
                Console.WriteLine($"  [Shopify] {storeName}: skipped {skippedNotInCatalog} products not in catalog");
        }

        if (needed.Count == 0)
            return results;

        // Step 2: Fetch detail pages concurrently (bounded parallelism)
        int errors = 0;
        int found = 0;
        string source = $"shopify:{storeName}";
        using var semaphore = new SemaphoreSlim(MaxConcurrentDetailRequests);

        var tasks = needed.Select(async (item, index) =>
        {
            await semaphore.WaitAsync(ct);
            try
            {
                // Stagger requests within the concurrency window
                await Task.Delay(RequestDelay, ct);

                ShopifyProductDetail? detail = await GetJsonWithRetryAsync<ShopifyProductDetail>(
                    $"{storeUrl}/products/{item.Handle}.json", ct);

                string? barcode = detail?.Product?.Variants?.FirstOrDefault()?.Barcode;

                if (IsValidBarcode(barcode))
                {
                    lock (results)
                    {
                        results[item.Sku] = new ShopifyEanResult(barcode!, source);
                        found++;
                    }
                }
            }
            catch
            {
                Interlocked.Increment(ref errors);
            }
            finally
            {
                semaphore.Release();
            }

            if (_verbose && (index + 1) % 200 == 0)
                Console.WriteLine($"  [Shopify] {storeName}: {index + 1}/{needed.Count} products fetched ({found} found)...");
        });

        await Task.WhenAll(tasks);

        if (_verbose)
            Console.WriteLine($"  [Shopify] {storeName}: found {results.Count} EAN barcodes ({errors} errors)");

        return results;
    }

    /// <summary>
    /// Fetches EAN barcodes from specific Shopify collections (for stores where global pagination is impractical).
    /// </summary>
    private async Task<Dictionary<string, ShopifyEanResult>> FetchFromCollectionsAsync(
        IReadOnlySet<string> alreadyResolved,
        Dictionary<string, ShopifyEanResult> alreadyFound,
        string storeUrl,
        IReadOnlyList<string> collections,
        IReadOnlySet<string>? catalogSkus,
        CancellationToken ct)
    {
        string storeName = new Uri(storeUrl).Host;
        if (_verbose) Console.WriteLine($"\n  [Shopify] Fetching {collections.Count} collections from {storeName}...");

        var results = new Dictionary<string, ShopifyEanResult>(StringComparer.OrdinalIgnoreCase);
        List<ShopifyProductHandle> needed = [];
        int totalProducts = 0;
        int skippedNotInCatalog = 0;
        var seenHandles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // Iterate through each collection
        foreach (string collection in collections)
        {
            ct.ThrowIfCancellationRequested();
            int page = 1;
            while (true)
            {
                ct.ThrowIfCancellationRequested();
                ShopifyProductList? list = await GetJsonWithRetryAsync<ShopifyProductList>(
                    $"{storeUrl}/collections/{collection}/products.json?limit=250&page={page}", ct);

                if (list?.Products is null || list.Products.Count == 0)
                    break;

                foreach (ShopifyListProduct product in list.Products)
                {
                    totalProducts++;
                    if (product.Handle is null || !seenHandles.Add(product.Handle))
                        continue; // Deduplicate across collections

                    string? rawSku = product.Variants?.FirstOrDefault()?.Sku;
                    string? sku = NormalizeSku(rawSku);

                    if (sku is null)
                    {
                        // No SKU — use title-based key for name matching (e.g., CMON products)
                        string? titleKey = NormalizeTitle(product.Title);
                        if (titleKey is null)
                            continue;
                        sku = $"title:{titleKey}";
                    }
                    else
                    {
                        // SKU-based: apply catalog filter
                        if (catalogSkus is not null && !catalogSkus.Contains(sku))
                        {
                            skippedNotInCatalog++;
                            continue;
                        }
                    }

                    if (alreadyResolved.Contains(sku) || alreadyFound.ContainsKey(sku))
                        continue;

                    needed.Add(new ShopifyProductHandle(product.Handle, sku, product.Title ?? ""));
                }

                if (list.Products.Count < 250)
                    break;
                page++;
                await Task.Delay(RequestDelay, ct);
            }
        }

        if (_verbose)
        {
            Console.WriteLine($"  [Shopify] {storeName}: {totalProducts} products across {collections.Count} collections, {needed.Count} need barcode lookup");
            if (skippedNotInCatalog > 0)
                Console.WriteLine($"  [Shopify] {storeName}: skipped {skippedNotInCatalog} products not in catalog");
        }

        if (needed.Count == 0)
            return results;

        // Fetch detail pages concurrently
        int errors = 0;
        int found = 0;
        string source = $"shopify:{storeName}";
        using var semaphore = new SemaphoreSlim(MaxConcurrentDetailRequests);

        var tasks = needed.Select(async (item, index) =>
        {
            await semaphore.WaitAsync(ct);
            try
            {
                await Task.Delay(RequestDelay, ct);
                ShopifyProductDetail? detail = await GetJsonWithRetryAsync<ShopifyProductDetail>(
                    $"{storeUrl}/products/{item.Handle}.json", ct);
                string? barcode = detail?.Product?.Variants?.FirstOrDefault()?.Barcode;
                if (IsValidBarcode(barcode))
                {
                    lock (results)
                    {
                        results[item.Sku] = new ShopifyEanResult(barcode!, source);
                        found++;
                    }
                }
            }
            catch
            {
                Interlocked.Increment(ref errors);
            }
            finally
            {
                semaphore.Release();
            }

            if (_verbose && (index + 1) % 200 == 0)
                Console.WriteLine($"  [Shopify] {storeName}: {index + 1}/{needed.Count} products fetched ({found} found)...");
        });

        await Task.WhenAll(tasks);

        if (_verbose)
            Console.WriteLine($"  [Shopify] {storeName}: found {results.Count} EAN barcodes ({errors} errors)");

        return results;
    }
    /// Rejects UUIDs, internal IDs, and other non-standard values.
    /// </summary>
    internal static bool IsValidBarcode(string? barcode)
    {
        if (string.IsNullOrWhiteSpace(barcode))
            return false;

        barcode = barcode.Trim();

        // EAN-13 (13 digits) or UPC-A (12 digits) — the standard retail barcode formats
        if (barcode.Length is not (12 or 13))
            return false;

        return barcode.All(char.IsAsciiDigit);
    }

    /// <summary>
    /// HTTP GET with retry on 429 (rate limit) and transient errors.
    /// </summary>
    private async Task<T?> GetJsonWithRetryAsync<T>(string url, CancellationToken ct)
    {
        for (int attempt = 0; attempt < 3; attempt++)
        {
            using HttpResponseMessage response = await _httpClient.GetAsync(url, ct);

            if (response.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
            {
                // Back off on rate limit: 2s, 5s, 10s
                int backoffMs = (attempt + 1) * 2500;
                if (_verbose && attempt == 0)
                    Console.WriteLine($"  [Shopify] Rate limited, backing off {backoffMs}ms...");
                await Task.Delay(backoffMs, ct);
                continue;
            }

            response.EnsureSuccessStatusCode();
            return await response.Content.ReadFromJsonAsync<T>(ct);
        }

        // Final attempt without retry
        using HttpResponseMessage final = await _httpClient.GetAsync(url, ct);
        final.EnsureSuccessStatusCode();
        return await final.Content.ReadFromJsonAsync<T>(ct);
    }

    public void Dispose()
    {
        _httpClient.Dispose();
    }

    // Internal types

    private record ShopifyProductHandle(string Handle, string Sku, string Title);

    /// <summary>
    /// Normalizes Shopify SKUs for matching against catalog SKUs.
    /// For numeric-only SKUs (GW format), strips retailer suffixes like "-restock", "-1".
    /// For Corvus Belli retailer formats (COR prefix), extracts the CB reference number.
    /// For alphanumeric SKUs (Steamforged SFIK-*, Wyrd WYR*, Warlord WGR-*, PB PBW*), preserves as-is.
    /// </summary>
    internal static string? NormalizeSku(string? sku)
    {
        if (string.IsNullOrWhiteSpace(sku))
            return null;

        sku = sku.Trim();

        if (sku.Length == 0)
            return null;

        // Handle CMON retailer SKU formats: CMN prefix (e.g., CMNSIF211 → SIF211)
        if (sku.StartsWith("CMN", StringComparison.OrdinalIgnoreCase)
            && sku.Length > 3 && !char.IsAsciiDigit(sku[3]))
        {
            sku = sku[3..];
        }

        // Handle Corvus Belli retailer SKU formats
        if (sku.StartsWith("COR", StringComparison.OrdinalIgnoreCase))
        {
            if (sku.Length > 3 && char.IsAsciiDigit(sku[3]))
            {
                // Tistaminis format: COR281646-1212 → strip "COR" prefix, continue processing
                sku = sku[3..];
            }
            else if (sku.StartsWith("COR-", StringComparison.OrdinalIgnoreCase))
            {
                // Bellford format: "COR-INF PAN 281 236 1028" → extract digits
                var digits = new string(sku.Where(char.IsAsciiDigit).ToArray());
                if (digits.Length >= 6)
                    return digits[..6]; // CB 6-digit product reference
                if (digits.Length > 0)
                    return digits;
                return null;
            }
        }

        // Check if the base (before first dash) is numeric-only → GW/CB-style SKU
        int dashIndex = sku.IndexOf('-');
        if (dashIndex > 0)
        {
            string prefix = sku[..dashIndex];
            if (prefix.All(char.IsAsciiDigit))
            {
                // Numeric prefix before dash — strip suffix (works for both GW and CB)
                return prefix;
            }
        }
        else if (sku.All(char.IsAsciiDigit))
        {
            // Pure numeric SKU (GW) — use as-is
            return sku;
        }

        // Alphanumeric SKU (Steamforged, Wyrd, Warlord, PB, AMG, CMON, Mantic) — preserve as-is
        // Strip trailing language code "EN" when preceded by a digit (e.g., CP103EN → CP103, CPE03EN → CPE03)
        // Common on AMG/retailer SKUs from US stores like Flipside
        if (sku.Length > 3
            && sku.EndsWith("EN", StringComparison.OrdinalIgnoreCase)
            && char.IsAsciiDigit(sku[^3]))
        {
            sku = sku[..^2];
        }

        return sku;
    }

    /// <summary>
    /// Normalizes product titles for name-based matching when SKUs aren't available (e.g., CMON products).
    /// Strips common brand/game-system prefixes, "House" faction prefixes, removes punctuation,
    /// and collapses whitespace. Returns a lowercase key suitable for matching, or null if title is empty.
    /// </summary>
    internal static string? NormalizeTitle(string? title)
    {
        if (string.IsNullOrWhiteSpace(title))
            return null;

        string t = title.Trim();

        // Remove common game system prefixes (case-insensitive)
        string[] prefixes =
        [
            "a song of ice and fire:",
            "a song of ice & fire:",
            "asoiaf:",
            "asoiaf -",
        ];

        string lower = t.ToLowerInvariant();
        foreach (string prefix in prefixes)
        {
            if (lower.StartsWith(prefix, StringComparison.Ordinal))
            {
                t = t[prefix.Length..].TrimStart();
                lower = t.ToLowerInvariant();
            }
        }

        // Strip "House " prefix — retailers use "House Stark:" but manufacturer uses "Stark:"
        if (lower.StartsWith("house ", StringComparison.Ordinal))
        {
            t = t[6..].TrimStart();
            lower = t.ToLowerInvariant();
        }

        // Remove punctuation (keep letters, digits, spaces)
        var chars = new char[t.Length];
        int pos = 0;
        bool lastWasSpace = false;
        foreach (char c in lower)
        {
            if (char.IsLetterOrDigit(c))
            {
                chars[pos++] = c;
                lastWasSpace = false;
            }
            else if (!lastWasSpace && pos > 0)
            {
                chars[pos++] = ' ';
                lastWasSpace = true;
            }
        }

        string result = new string(chars, 0, pos).TrimEnd();
        return result.Length >= 3 ? result : null;
    }
}

/// <summary>Result from Shopify EAN lookup: barcode and source store.</summary>
public record ShopifyEanResult(string Ean, string Source);

// Shopify JSON models (list endpoint)

internal record ShopifyProductList
{
    [JsonPropertyName("products")]
    public IReadOnlyList<ShopifyListProduct>? Products { get; init; }
}

internal record ShopifyListProduct
{
    [JsonPropertyName("id")]
    public long Id { get; init; }

    [JsonPropertyName("title")]
    public string? Title { get; init; }

    [JsonPropertyName("handle")]
    public string? Handle { get; init; }

    [JsonPropertyName("vendor")]
    public string? Vendor { get; init; }

    [JsonPropertyName("product_type")]
    public string? ProductType { get; init; }

    [JsonPropertyName("variants")]
    public IReadOnlyList<ShopifyListVariant>? Variants { get; init; }
}

internal record ShopifyListVariant
{
    [JsonPropertyName("sku")]
    public string? Sku { get; init; }
}

// Shopify JSON models (individual product endpoint)

internal record ShopifyProductDetail
{
    [JsonPropertyName("product")]
    public ShopifyDetailProduct? Product { get; init; }
}

internal record ShopifyDetailProduct
{
    [JsonPropertyName("title")]
    public string? Title { get; init; }

    [JsonPropertyName("variants")]
    public IReadOnlyList<ShopifyDetailVariant>? Variants { get; init; }
}

internal record ShopifyDetailVariant
{
    [JsonPropertyName("sku")]
    public string? Sku { get; init; }

    [JsonPropertyName("barcode")]
    public string? Barcode { get; init; }

    [JsonPropertyName("price")]
    public string? Price { get; init; }
}
