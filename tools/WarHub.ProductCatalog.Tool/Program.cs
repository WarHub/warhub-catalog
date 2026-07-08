using System.CommandLine;
using System.Reflection;
using WarHub.CatalogStore;
using WarHub.CatalogStore.Ledger;
using WarHub.CatalogStore.Reconcile;
using WarHub.ProductCatalog.Tool.Configuration;
using WarHub.ProductCatalog.Tool.Enrichment;
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;
using WarHub.ProductCatalog.Tool.Reconcile;
using WarHub.ProductCatalog.Tool.Scraping;
using YamlDotNet.Serialization;

Option<DirectoryInfo> outputOption = new("--output")
{
    Description = "Output directory for catalog files",
    DefaultValueFactory = _ => new DirectoryInfo("output")
};

Option<FileInfo?> overridesOption = new("--overrides")
{
    Description = "Path to overrides YAML file"
};

Option<DirectoryInfo?> seedOption = new("--seed")
{
    Description = "Path to seed data directory containing YAML files"
};

Option<string?> manufacturerOption = new("--manufacturer")
{
    Description = "Filter to a specific manufacturer (e.g., 'Games Workshop')"
};

Option<string?> gameSystemOption = new("--game-system")
{
    Description = "Filter to a specific game system (e.g., 'Warhammer 40,000')"
};

Option<int> sampleOption = new("--sample")
{
    Description = "Sample N products per faction (0 = all)",
    DefaultValueFactory = _ => 0
};

Option<bool> verboseOption = new("--verbose")
{
    Description = "Verbose logging"
};

Option<bool> skipScrapeOption = new("--skip-scrape")
{
    Description = "Skip web scraping, only use seed data",
    DefaultValueFactory = _ => false
};

Option<bool> enrichEanOption = new("--enrich-ean")
{
    Description = "Enrich products with EAN codes from UPCitemdb API",
    DefaultValueFactory = _ => false
};

Option<string?> upcitemdbKeyOption = new("--upcitemdb-key")
{
    Description = "UPCitemdb API key for paid tier (omit for free trial: 100 req/day)"
};

Option<string[]> eanShopifyStoresOption = new("--ean-shopify-stores")
{
    Description = "Shopify store URLs to scrape for EAN data (e.g., https://goblingaming.co.uk)",
    AllowMultipleArgumentsPerToken = true,
};

Option<int> eanBudgetOption = new("--ean-budget")
{
    Description = "Max UPCitemdb API calls per run (0 = unlimited, default: 0)",
    DefaultValueFactory = _ => 0
};

Option<bool> enrichOnlyOption = new("--enrich-only")
{
    Description = "Skip scraping; load existing YAML catalogs and enrich them with EAN data",
    DefaultValueFactory = _ => false
};

RootCommand rootCommand = new("WarHub Product Catalog Tool — builds miniature product catalog from web sources and seed data")
{
    outputOption,
    overridesOption,
    seedOption,
    manufacturerOption,
    gameSystemOption,
    sampleOption,
    verboseOption,
    skipScrapeOption,
    enrichEanOption,
    upcitemdbKeyOption,
    eanShopifyStoresOption,
    eanBudgetOption,
    enrichOnlyOption,
};

rootCommand.SetAction(async (parseResult, cancellationToken) =>
{
    DirectoryInfo output = parseResult.GetValue(outputOption)!;
    FileInfo? overrides = parseResult.GetValue(overridesOption);
    DirectoryInfo? seed = parseResult.GetValue(seedOption);
    string? manufacturerFilter = parseResult.GetValue(manufacturerOption);
    string? gameSystemFilter = parseResult.GetValue(gameSystemOption);
    int sample = parseResult.GetValue(sampleOption);
    bool verbose = parseResult.GetValue(verboseOption);
    bool skipScrape = parseResult.GetValue(skipScrapeOption);
    bool enrichEan = parseResult.GetValue(enrichEanOption);
    string? upcitemdbKey = parseResult.GetValue(upcitemdbKeyOption);
    string[] eanShopifyStores = parseResult.GetValue(eanShopifyStoresOption) ?? [];
    int eanBudget = parseResult.GetValue(eanBudgetOption);
    bool enrichOnly = parseResult.GetValue(enrichOnlyOption);

    string outputDir = output.FullName;
    string? overridesPath = overrides?.FullName;

    string toolVersion = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";

    bool eanEnabled = enrichEan || eanShopifyStores.Length > 0;
    bool existingOutputHasData = Directory.Exists(Path.Combine(outputDir, "manufacturers"));

    // Auto-enable EAN preservation when existing output has data
    if (!eanEnabled && existingOutputHasData)
    {
        eanEnabled = true;
        if (verbose) Console.WriteLine("Auto-enabling EAN preservation (existing output data found)");
    }

    // Load existing EAN data from product YAML files (preserves EANs across re-scrapes)
    Dictionary<string, (string? Ean, string Source)>? existingEanLookup = null;
    HashSet<string>? catalogSkus = null;
    if (eanEnabled && existingOutputHasData)
    {
        (existingEanLookup, catalogSkus) = await LoadExistingCatalogDataAsync(outputDir, verbose, cancellationToken);
    }

    // Fetch Shopify EAN data (exact SKU→EAN mapping from retailers and manufacturer stores)
    Dictionary<string, ShopifyEanResult>? shopifyEans = null;
    if (eanShopifyStores.Length > 0)
    {
        var alreadyResolved = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (existingEanLookup is not null)
        {
            foreach (string key in existingEanLookup.Keys)
            {
                alreadyResolved.Add(key);
                string? normalized = ShopifyEanSource.NormalizeSku(key);
                if (normalized is not null && normalized != key)
                    alreadyResolved.Add(normalized);
            }
        }

        using var shopify = new ShopifyEanSource(verbose);
        shopifyEans = await shopify.FetchEansAsync(alreadyResolved, eanShopifyStores, catalogSkus, cancellationToken);
        if (verbose) Console.WriteLine($"Shopify EAN scrape: {shopifyEans.Count} barcodes found");
    }

    // Set up UPCitemdb enricher for products not covered by Shopify or existing data
    EanEnricher? eanEnricher = null;
    if (enrichEan)
    {
        var client = new UpcItemDbClient(upcitemdbKey, verbose);
        eanEnricher = new EanEnricher(client, verbose, eanBudget);
        if (verbose && eanBudget > 0)
            Console.WriteLine($"UPCitemdb enrichment enabled (budget: {eanBudget} API calls)");
    }

    // --- Enrich-only mode: load existing catalogs, enrich, write back ---
    if (enrichOnly)
    {
        if (verbose) Console.WriteLine("Enrich-only mode: loading existing YAML catalogs...");

        IReadOnlyList<FactionCatalog> catalogs = await ExistingCatalogLoader.LoadAllAsync(
            outputDir, manufacturerFilter, gameSystemFilter, verbose, cancellationToken);

        if (catalogs.Count == 0)
        {
            Console.WriteLine("No existing catalogs found to enrich.");
            return 0;
        }

        // Ensure enrichment tools are initialized (may not have been if --enrich-ean wasn't passed initially)
        if (eanEnricher is null && enrichEan)
        {
            var client = new UpcItemDbClient(upcitemdbKey, verbose);
            eanEnricher = new EanEnricher(client, verbose, eanBudget);
            if (verbose && eanBudget > 0)
                Console.WriteLine($"UPCitemdb enrichment enabled (budget: {eanBudget} API calls)");
        }

        if (shopifyEans is null && eanShopifyStores.Length > 0)
        {
            var alreadyResolved = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using var shopify = new ShopifyEanSource(verbose);
            shopifyEans = await shopify.FetchEansAsync(alreadyResolved, eanShopifyStores, catalogSkus, cancellationToken);
            if (verbose) Console.WriteLine($"Shopify EAN scrape: {shopifyEans.Count} barcodes found");
        }

        int totalEnriched = 0;
        int totalUpdated = 0;
        var enrichedManufacturerSummaries = new Dictionary<string, (ManufacturerInfo Info, Dictionary<string, (GameSystemInfo GsInfo, List<FactionSummary> Factions)> GameSystems)>();

        foreach (FactionCatalog catalog in catalogs)
        {
            cancellationToken.ThrowIfCancellationRequested();

            IReadOnlyList<Product> products = catalog.Products;

            // Apply Shopify EANs to products that don't have EAN data yet
            if (shopifyEans is not null)
                products = ApplyShopifyEans(products, shopifyEans);

            // Enrich remaining products via UPCitemdb
            if (eanEnricher is not null)
                products = await eanEnricher.EnrichAsync(products, catalog.Manufacturer, cancellationToken);

            int updated = products.Zip(catalog.Products)
                .Count(pair => pair.First.Ean != pair.Second.Ean);

            var enrichedCatalog = catalog with { Products = products.ToList() };

            await YamlCatalogWriter.WriteFactionAsync(enrichedCatalog, outputDir);
            totalEnriched += products.Count;
            totalUpdated += updated;

            // Track summaries for manifest
            ManufacturerInfo? mfgInfo = ManufacturerRegistry.GetManufacturer(catalog.Manufacturer);
            if (!enrichedManufacturerSummaries.ContainsKey(catalog.Manufacturer))
            {
                enrichedManufacturerSummaries[catalog.Manufacturer] = (
                    mfgInfo ?? new ManufacturerInfo(catalog.Manufacturer, catalog.ManufacturerSlug,
                        new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)),
                    new Dictionary<string, (GameSystemInfo, List<FactionSummary>)>(StringComparer.OrdinalIgnoreCase));
            }

            var (_, gameSystems) = enrichedManufacturerSummaries[catalog.Manufacturer];
            if (!gameSystems.ContainsKey(catalog.GameSystem))
            {
                GameSystemInfo? gsInfo = mfgInfo?.GameSystems.GetValueOrDefault(catalog.GameSystem);
                gameSystems[catalog.GameSystem] = (
                    gsInfo ?? new GameSystemInfo(catalog.GameSystem, catalog.GameSystemSlug, []),
                    []);
            }

            gameSystems[catalog.GameSystem].Factions.Add(new FactionSummary
            {
                Name = catalog.Faction,
                Slug = catalog.FactionSlug,
            });

            if (verbose && updated > 0)
                Console.WriteLine($"  {catalog.Manufacturer} / {catalog.GameSystem} / {catalog.Faction}: {updated} EANs updated");
        }

        // Write updated manifest
        var enrichManifest = new Manifest
        {
            ToolVersion = toolVersion,
            Manufacturers = enrichedManufacturerSummaries.Select(kvp =>
            {
                var (mfgInfo, gameSystems) = kvp.Value;
                return new ManufacturerSummary
                {
                    Name = mfgInfo.Name,
                    Slug = mfgInfo.Slug,
                    GameSystems = gameSystems.Select(gsKvp =>
                    {
                        var (gsInfo, factions) = gsKvp.Value;
                        return new GameSystemSummary
                        {
                            Name = gsInfo.Name,
                            Slug = gsInfo.Slug,
                            Factions = factions,
                        };
                    }).ToList(),
                };
            }).ToList(),
        };

        await YamlCatalogWriter.WriteManifestAsync(enrichManifest, outputDir);

        eanEnricher?.LogSummary();
        eanEnricher?.Dispose();

        Console.WriteLine($"Enrich-only done! {totalUpdated} EANs updated across {totalEnriched} products in {catalogs.Count} catalogs");
        return 0;
    }

    // --- Normal scrape pipeline ---
    var allRawProducts = new List<RawProduct>();

    if (verbose) Console.WriteLine($"Output: {outputDir}");
    if (verbose) Console.WriteLine($"Sample: {(sample > 0 ? sample.ToString() : "all")}");
    if (verbose) Console.WriteLine($"Skip scrape: {skipScrape}");

    // Phase 1: Load seed data
    if (seed is not null && seed.Exists)
    {
        if (verbose) Console.WriteLine($"Loading seed data from: {seed.FullName}");
        IReadOnlyList<RawProduct> seedProducts = await SeedDataLoader.LoadAsync(seed.FullName, cancellationToken);
        allRawProducts.AddRange(seedProducts);
        if (verbose) Console.WriteLine($"  Loaded {seedProducts.Count} products from seed data");
    }

    // Manufacturers whose live fetch threw this run — their archived records must NOT
    // be miss-counted (a degraded scrape must never auto-flag products as discontinued).
    var degradedManufacturers = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    // Phase 2: Fetch from live sources (if not skipped)
    if (!skipScrape)
    {
        if (verbose) Console.WriteLine("Fetching from live data sources...");

        // Cache for multi-system stores — fetch all products once, filter per game system
        var multiStoreCache = new Dictionary<string, IReadOnlyList<RawProduct>>();

        foreach ((string mfgName, ManufacturerInfo mfgInfo) in ManufacturerRegistry.Manufacturers)
        {
            if (manufacturerFilter is not null &&
                !mfgName.Equals(manufacturerFilter, StringComparison.OrdinalIgnoreCase))
                continue;

            if (verbose) Console.WriteLine($"\nManufacturer: {mfgName}");

            foreach ((string gsName, GameSystemInfo gsInfo) in mfgInfo.GameSystems)
            {
                if (gameSystemFilter is not null &&
                    !gsName.Equals(gameSystemFilter, StringComparison.OrdinalIgnoreCase))
                    continue;

                if (verbose) Console.WriteLine($"  Game System: {gsName}");

                try
                {
                    IReadOnlyList<RawProduct> fetched = mfgName switch
                    {
                        "Games Workshop" => await FetchGamesWorkshopProducts(gsName, sample, verbose, cancellationToken),
                        "Para Bellum" => await FetchParaBellumProducts(sample, verbose, cancellationToken),
                        "Warlord Games" => await FetchFromMultiStoreCache(multiStoreCache, "Warlord Games", gsName, sample, verbose,
                            () => FetchWarlordGamesAllProducts(verbose, cancellationToken)),
                        "Wyrd Games" => await FetchFromMultiStoreCache(multiStoreCache, "Wyrd Games", gsName, sample, verbose,
                            () => FetchWyrdGamesAllProducts(verbose, cancellationToken)),
                        "Mantic Games" => await FetchFromMultiStoreCache(multiStoreCache, "Mantic Games", gsName, sample, verbose,
                            () => FetchManticGamesAllProducts(verbose, cancellationToken)),
                        "Corvus Belli" => await FetchCorvusBelliProducts(gsName, sample, verbose, cancellationToken),
                        "Atomic Mass Games" => await FetchAtomicMassGamesProducts(gsName, sample, verbose, cancellationToken),
                        "CMON" => await FetchCmonProducts(gsName, sample, verbose, cancellationToken),
                        "Privateer Press" => await FetchPrivateerPressProducts(gsName, sample, verbose, cancellationToken),
                        "Steamforged Games" => await FetchFromMultiStoreCache(multiStoreCache, "Steamforged Games", gsName, sample, verbose,
                            () => FetchSteamforgedGamesAllProducts(verbose, cancellationToken)),
                        _ => [],
                    };

                    allRawProducts.AddRange(fetched);
                    if (verbose) Console.WriteLine($"    Fetched {fetched.Count} products");
                }
                catch (Exception ex)
                {
                    degradedManufacturers.Add(mfgInfo.Slug);
                    if (verbose) Console.WriteLine($"    Warning: Fetch failed: {ex.Message}");
                }
            }
        }
    }

    // Phase 3: Enrich and organize
    if (verbose) Console.WriteLine($"\nTotal raw products: {allRawProducts.Count}");

    // Group by manufacturer → game system → faction
    var grouped = allRawProducts
        .GroupBy(p => (p.Manufacturer, p.GameSystem, p.Faction ?? "General"))
        .OrderBy(g => g.Key.Manufacturer)
        .ThenBy(g => g.Key.GameSystem)
        .ThenBy(g => g.Key.Item3);

    var manufacturerSummaries = new Dictionary<string, (ManufacturerInfo Info, Dictionary<string, (GameSystemInfo GsInfo, List<FactionSummary> Factions)> GameSystems)>();
    int totalProducts = 0;

    string today = DateTime.UtcNow.ToString("yyyy-MM-dd");
    string ledgerPath = Path.Combine(outputDir, "_liveness.yaml");
    LivenessLedger ledger = await LedgerStore.LoadAsync(ledgerPath, cancellationToken);

    // Only a full, live scrape may drive the liveness ledger. A sampled run
    // (--sample) or a scrape-skipping run (--skip-scrape / enrich-only) is not
    // representative — miss-counting its absent records would spuriously flag
    // real products as discontinued in the archive.
    bool authoritativeRun = !skipScrape && sample == 0;

    // A "full" run additionally requires every configured source to have been
    // scraped this run — a --manufacturer/--game-system filter only touches a
    // subset, so orphan GC under a filtered run would prune nothing for the
    // excluded sources while wrongly having the opportunity to prune the
    // included ones from a non-representative pass. The product tool has no
    // other partial-processing mode (no seed-only switch), so this is the
    // complete filter set to check.
    bool fullRun = authoritativeRun && manufacturerFilter is null && gameSystemFilter is null;

    var mfgScrapedTotals = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
    var liveLedgerKeys = new HashSet<string>(StringComparer.Ordinal);
    var prunableSources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    foreach (var group in grouped)
    {
        string mfgName = group.Key.Manufacturer;
        string gsName = group.Key.GameSystem;
        string factionName = group.Key.Item3;

        ManufacturerInfo? mfgInfo = ManufacturerRegistry.GetManufacturer(mfgName);
        string mfgSlug = mfgInfo?.Slug ?? ManufacturerRegistry.Slugify(mfgName);
        string gsSlug = mfgInfo?.GameSystems.GetValueOrDefault(gsName)?.Slug ?? ManufacturerRegistry.Slugify(gsName);
        string factionSlug = ManufacturerRegistry.Slugify(factionName);

        // Enrich products
        IReadOnlyList<Product> enriched = group
            .Select(ProductEnricher.Enrich)
            .ToList();

        // Apply sampling
        if (sample > 0)
        {
            enriched = enriched.Take(sample).ToList();
        }

        // Apply overrides
        enriched = OverrideApplier.Apply(enriched, mfgSlug, gsSlug, overridesPath);

        // Apply Shopify EANs
        if (shopifyEans is not null)
            enriched = ApplyShopifyEans(enriched, shopifyEans);

        // Enrich remaining products via UPCitemdb
        if (eanEnricher is not null)
            enriched = await eanEnricher.EnrichAsync(enriched, mfgName, cancellationToken);

        // A source whose fresh scrape came back implausibly smaller than its last-good
        // count (per the ledger) is treated the same as a degraded fetch: it must not
        // drive miss-flagging this run. The comparison uses the manufacturer's running
        // scraped total (mfgScrapedTotals), i.e. the same accumulated value that will be
        // passed to LivenessUpdater.Apply as scrapedCount below, plus this faction's own
        // enriched count (not yet folded into the running total at this point).
        int priorMfgCount = ledger.Sources.GetValueOrDefault(mfgSlug)?.ProductCount ?? 0;
        bool implausibleDrop = LedgerMaintenance.IsImplausibleDrop(
            priorMfgCount, mfgScrapedTotals.GetValueOrDefault(mfgSlug) + enriched.Count);
        bool sourceHealthy = !degradedManufacturers.Contains(mfgSlug) && !implausibleDrop;

        // Reconcile fresh scrape against the archived faction file (append-only).
        string factionPath = Path.Combine(outputDir, "manufacturers", mfgSlug, gsSlug, $"{factionSlug}.yaml");
        IReadOnlyList<Product> existingProducts = await LoadExistingFactionProductsAsync(factionPath, cancellationToken);

        var adapter = new ProductRecordAdapter();
        var reconciler = new CatalogReconciler<Product>(adapter);
        (IReadOnlyDictionary<string, string> aliases, ISet<string> retracted) =
            OverrideAliases.Load(overridesPath, mfgSlug, gsSlug, factionSlug);

        ReconcileResult<Product> reconciled = reconciler.Reconcile(
            existingProducts, enriched.ToList(), aliases, retracted, today);

        // Ledger update (per faction contributes to a per-manufacturer source entry).
        // Gated on authoritativeRun: only a full, live scrape may drive the ledger
        // (see the authoritativeRun comment above).
        List<Product> finalProducts;
        if (authoritativeRun)
        {
            string sourceKey = mfgSlug;
            var seenLedgerKeys = reconciled.SeenKeys
                .Select(k => $"{mfgSlug}/{gsSlug}/{factionSlug}/{k}").ToHashSet(StringComparer.Ordinal);
            var knownLedgerKeys = reconciled.Records
                .Select(p => $"{mfgSlug}/{gsSlug}/{factionSlug}/{adapter.IdentityKey(p)}").ToList();
            var currentlyFlagged = reconciled.Records
                .Where(p => p.Status == "suspected-discontinued")
                .Select(p => $"{mfgSlug}/{gsSlug}/{factionSlug}/{adapter.IdentityKey(p)}")
                .ToHashSet(StringComparer.Ordinal);

            mfgScrapedTotals[mfgSlug] = mfgScrapedTotals.GetValueOrDefault(mfgSlug) + enriched.Count;

            // Orphan-GC bookkeeping: every reconciled record's ledger key is "live"
            // regardless of this faction's source health (pruning is separately gated
            // per-source via prunableSources below). A manufacturer is prunable only if
            // every faction processed for it this run was healthy — one unhealthy faction
            // withdraws the whole manufacturer from this run's GC, conservatively.
            foreach (string key in knownLedgerKeys)
                liveLedgerKeys.Add(key);
            if (sourceHealthy)
                prunableSources.Add(mfgSlug);
            else
                prunableSources.Remove(mfgSlug);

            LivenessUpdate live = LivenessUpdater.Apply(
                ledger, sourceKey, sourceSucceeded: sourceHealthy, scrapedCount: mfgScrapedTotals[mfgSlug],
                seenKeys: seenLedgerKeys, knownKeysForSource: knownLedgerKeys,
                today: today, currentlyFlaggedKeys: currentlyFlagged);
            ledger = live.Ledger;

            // Apply auto-flag / reactivation status transitions onto the records.
            finalProducts = reconciled.Records.Select(p =>
            {
                string lk = $"{mfgSlug}/{gsSlug}/{factionSlug}/{adapter.IdentityKey(p)}";
                if (live.Flagged.Contains(lk) && p.Status == "current")
                    // A product that vanished from the scrape has genuinely-unknown
                    // availability, not whatever it last reported (e.g. "in_stock").
                    return p with { Status = "suspected-discontinued", Availability = "unknown" };
                if (live.Reactivated.Contains(lk) && p.Status == "suspected-discontinued")
                    return p with { Status = "current" };
                return p;
            }).ToList();
        }
        else
        {
            finalProducts = reconciled.Records.ToList();
        }

        var catalog = new FactionCatalog
        {
            Manufacturer = mfgName,
            ManufacturerSlug = mfgSlug,
            GameSystem = gsName,
            GameSystemSlug = gsSlug,
            Faction = factionName,
            FactionSlug = factionSlug,
            Products = finalProducts,
        };

        await YamlCatalogWriter.WriteFactionAsync(catalog, outputDir);
        totalProducts += finalProducts.Count;

        // Track summaries
        if (!manufacturerSummaries.ContainsKey(mfgName))
        {
            manufacturerSummaries[mfgName] = (
                mfgInfo ?? new ManufacturerInfo(mfgName, mfgSlug,
                    new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)),
                new Dictionary<string, (GameSystemInfo, List<FactionSummary>)>(StringComparer.OrdinalIgnoreCase));
        }

        var (_, gameSystems) = manufacturerSummaries[mfgName];
        if (!gameSystems.ContainsKey(gsName))
        {
            GameSystemInfo? gsInfo = mfgInfo?.GameSystems.GetValueOrDefault(gsName);
            gameSystems[gsName] = (
                gsInfo ?? new GameSystemInfo(gsName, gsSlug, []),
                []);
        }

        gameSystems[gsName].Factions.Add(new FactionSummary
        {
            Name = factionName,
            Slug = factionSlug,
        });

        if (verbose) Console.WriteLine($"  {mfgName} / {gsName} / {factionName}: {finalProducts.Count} products");
    }

    // Build manifest
    var manifest = new Manifest
    {
        ToolVersion = toolVersion,
        Manufacturers = manufacturerSummaries.Select(kvp =>
        {
            var (mfgInfo, gameSystems) = kvp.Value;
            return new ManufacturerSummary
            {
                Name = mfgInfo.Name,
                Slug = mfgInfo.Slug,
                GameSystems = gameSystems.Select(gsKvp =>
                {
                    var (gsInfo, factions) = gsKvp.Value;
                    return new GameSystemSummary
                    {
                        Name = gsInfo.Name,
                        Slug = gsInfo.Slug,
                        Factions = factions,
                    };
                }).ToList(),
            };
        }).ToList(),
    };

    await YamlCatalogWriter.WriteManifestAsync(manifest, outputDir);

    // Orphan GC: only a full, authoritative run may prune the ledger — a sampled,
    // scrape-skipping, or --manufacturer/--game-system-filtered run only observed a
    // subset of records/sources, so it must not conclude that anything unseen is gone.
    if (authoritativeRun && fullRun)
    {
        IReadOnlyList<string> pruned = LedgerMaintenance.PruneOrphans(ledger, liveLedgerKeys, prunableSources);
        if (verbose && pruned.Count > 0)
            Console.WriteLine($"Ledger GC: pruned {pruned.Count} orphaned records.");
    }

    if (authoritativeRun)
        await LedgerStore.SaveAsync(ledgerPath, ledger, cancellationToken);

    eanEnricher?.LogSummary();
    eanEnricher?.Dispose();

    Console.WriteLine($"Done! Generated catalog: {totalProducts} products across {manufacturerSummaries.Count} manufacturers → {outputDir}");
    return 0;
});

Option<string> migrateDataDirOption = new("--data-dir")
{
    Description = "Path to data/products",
    Required = true
};

Command migrateCommand = new("migrate", "One-time migration of existing data to the new schema")
{
    migrateDataDirOption,
};

migrateCommand.SetAction(async (parseResult, cancellationToken) =>
{
    string dir = parseResult.GetValue(migrateDataDirOption)!;
    string date = DateTime.UtcNow.ToString("yyyy-MM-dd");
    return await WarHub.ProductCatalog.Tool.Migration.ProductMigrator.MigrateAsync(dir, date, cancellationToken);
});

rootCommand.Add(migrateCommand);

return rootCommand.Parse(args).Invoke();

// --- Data source helper methods ---

static async Task<IReadOnlyList<RawProduct>> FetchGamesWorkshopProducts(
    string gameSystem, int sample, bool verbose, CancellationToken ct)
{
    using var algolia = new AlgoliaProductSource(verbose: verbose);
    return await algolia.FetchProductsAsync(
        gameSystem,
        maxProducts: sample > 0 ? sample : 0,
        ct: ct);
}

static async Task<IReadOnlyList<RawProduct>> FetchParaBellumProducts(
    int sample, bool verbose, CancellationToken ct)
{
    using var wooCommerce = new WooCommerceProductSource(
        baseUrl: "https://eshop.para-bellum.com",
        manufacturer: "Para Bellum",
        gameSystem: "Conquest",
        verbose: verbose);
    return await wooCommerce.FetchAllProductsAsync(
        maxProducts: sample > 0 ? sample : 0,
        ct: ct);
}

/// <summary>
/// Loads existing EAN data and all catalog SKUs from product YAML files.
/// EAN lookup preserves EANs across re-scrapes. Catalog SKUs filter Shopify detail page fetches.
/// </summary>
static async Task<(Dictionary<string, (string? Ean, string Source)> EanLookup, HashSet<string> CatalogSkus)> LoadExistingCatalogDataAsync(
    string outputDir, bool verbose, CancellationToken ct)
{
    string manufacturersDir = Path.Combine(outputDir, "manufacturers");
    var eanLookup = new Dictionary<string, (string? Ean, string Source)>(StringComparer.OrdinalIgnoreCase);
    var catalogSkus = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    if (!Directory.Exists(manufacturersDir))
        return (eanLookup, catalogSkus);

    IReadOnlyList<FactionCatalog> catalogs = await ExistingCatalogLoader.LoadAllAsync(
        outputDir, null, null, verbose: false, ct);

    foreach (FactionCatalog catalog in catalogs)
    {
        foreach (Product product in catalog.Products)
        {
            string? key = product.ProductCode ?? product.Sku;
            bool hasEanData = !string.IsNullOrWhiteSpace(product.Ean) || !string.IsNullOrWhiteSpace(product.EanSource);

            if (!string.IsNullOrWhiteSpace(key))
            {
                // Add both raw and normalized SKU forms for matching.
                // Shopify retailers normalize SKUs (e.g., "COR281134-1072" → "281134"),
                // so catalog SKUs must also be normalized for the Contains() check to work.
                catalogSkus.Add(key);
                string? normalized = ShopifyEanSource.NormalizeSku(key);
                if (normalized is not null && normalized != key)
                    catalogSkus.Add(normalized);

                if (!string.IsNullOrWhiteSpace(product.Ean))
                    eanLookup.TryAdd(key, (product.Ean, product.EanSource ?? "existing"));
                else if (!string.IsNullOrWhiteSpace(product.EanSource))
                    eanLookup.TryAdd(key, (null, product.EanSource));
            }
            else if (hasEanData)
            {
                // Name-based fallback key for products without SKU/ProductCode (e.g., CMON).
                // Uses catalog path context to avoid collisions across manufacturers.
                string nameKey = $"name:{catalog.ManufacturerSlug}/{catalog.GameSystemSlug}/{catalog.FactionSlug}:{product.Name.Trim()}";
                if (!string.IsNullOrWhiteSpace(product.Ean))
                    eanLookup.TryAdd(nameKey, (product.Ean, product.EanSource ?? "existing"));
                else
                    eanLookup.TryAdd(nameKey, (null, product.EanSource!));
            }
        }
    }

    if (verbose)
    {
        Console.WriteLine($"  [EAN] Loaded {eanLookup.Count(e => e.Value.Ean is not null)} existing EANs from product files");
        Console.WriteLine($"  [EAN] Loaded {catalogSkus.Count} catalog SKUs for Shopify filtering");
    }

    return (eanLookup, catalogSkus);
}

/// <summary>
/// Loads the products from an existing faction catalog YAML file, for reconciliation
/// against the freshly-enriched scrape. Returns an empty list if the file doesn't exist yet.
/// </summary>
static async Task<IReadOnlyList<Product>> LoadExistingFactionProductsAsync(string factionPath, CancellationToken ct)
{
    if (!File.Exists(factionPath))
        return [];
    string yaml = await File.ReadAllTextAsync(factionPath, ct);
    FactionCatalog? catalog = ProductToolYaml.Deserializer.Deserialize<FactionCatalog>(yaml);
    return catalog?.Products ?? [];
}

/// <summary>
/// Applies Shopify EAN data to products by matching on SKU or product name.
/// Only applies to products that don't already have EAN or EanSource set.
/// Tries both raw and normalized SKU forms, since Shopify sources normalize
/// retailer SKUs (e.g., "COR281134-1072" → "281134") while catalog may store raw form.
/// Falls back to title-based matching for products without SKU matches (e.g., CMON).
/// </summary>
static IReadOnlyList<Product> ApplyShopifyEans(
    IReadOnlyList<Product> products,
    Dictionary<string, ShopifyEanResult> shopifyEans)
{
    return products.Select(p =>
    {
        if (!string.IsNullOrWhiteSpace(p.Ean) || !string.IsNullOrWhiteSpace(p.EanSource))
            return p;

        // Try SKU-based matching first
        string? sku = p.Sku;
        if (sku is not null)
        {
            // Try raw SKU first, then normalized form
            if (shopifyEans.TryGetValue(sku, out ShopifyEanResult? result))
                return p with { Ean = result.Ean, EanSource = result.Source };

            string? normalized = ShopifyEanSource.NormalizeSku(sku);
            if (normalized is not null && normalized != sku &&
                shopifyEans.TryGetValue(normalized, out result))
                return p with { Ean = result.Ean, EanSource = result.Source };
        }

        // Fall back to title-based matching (for products without SKUs, e.g., CMON)
        string? titleKey = ShopifyEanSource.NormalizeTitle(p.Name);
        if (titleKey is not null)
        {
            string key = $"title:{titleKey}";
            if (shopifyEans.TryGetValue(key, out ShopifyEanResult? titleResult))
                return p with { Ean = titleResult.Ean, EanSource = titleResult.Source };
        }

        return p;
    }).ToList();
}

// --- Multi-system store cache helper ---
// For stores that host multiple game systems, fetch all products once and cache.
// Subsequent calls for different game systems use the cached data.

static async Task<IReadOnlyList<RawProduct>> FetchFromMultiStoreCache(
    Dictionary<string, IReadOnlyList<RawProduct>> cache, string manufacturer,
    string gameSystem, int sample, bool verbose,
    Func<Task<IReadOnlyList<RawProduct>>> fetchAll)
{
    if (!cache.TryGetValue(manufacturer, out IReadOnlyList<RawProduct>? allProducts))
    {
        allProducts = await fetchAll();
        cache[manufacturer] = allProducts;
        if (verbose) Console.WriteLine($"    Cached {allProducts.Count} total products for {manufacturer}");
    }
    else
    {
        if (verbose) Console.WriteLine($"    Using cached {allProducts.Count} products");
    }

    List<RawProduct> filtered = allProducts
        .Where(p => p.GameSystem.Equals(gameSystem, StringComparison.OrdinalIgnoreCase))
        .ToList();

    if (sample > 0)
        filtered = filtered.Take(sample).ToList();

    return filtered;
}

// --- Warlord Games (Shopify) ---

static async Task<IReadOnlyList<RawProduct>> FetchWarlordGamesAllProducts(
    bool verbose, CancellationToken ct)
{
    using var source = new ShopifyProductSource(
        baseUrl: "https://store.warlordgames.com",
        manufacturer: "Warlord Games",
        defaultGameSystem: "Bolt Action",
        gameSystemExtractor: WarlordGamesGameSystem,
        factionExtractor: WarlordGamesFaction,
        defaultCurrency: "GBP",
        verbose: verbose);
    return await source.FetchAllProductsAsync(maxProducts: 0, ct: ct);
}

static string? WarlordGamesGameSystem(ShopifyProduct product)
{
    // Warlord Games uses product_type field for game system — maps directly
    string productType = product.ProductType ?? "";
    return productType switch
    {
        _ when productType.Contains("Bolt Action", StringComparison.OrdinalIgnoreCase) => "Bolt Action",
        _ when productType.Contains("Black Powder", StringComparison.OrdinalIgnoreCase)
            && !productType.Contains("Epic", StringComparison.OrdinalIgnoreCase) => "Black Powder",
        _ when productType.Contains("Hail Caesar", StringComparison.OrdinalIgnoreCase)
            && !productType.Contains("Epic", StringComparison.OrdinalIgnoreCase) => "Hail Caesar",
        _ when productType.Contains("Pike & Shotte", StringComparison.OrdinalIgnoreCase)
            && !productType.Contains("Epic", StringComparison.OrdinalIgnoreCase) => "Pike & Shotte",
        _ when productType.Contains("Victory at Sea", StringComparison.OrdinalIgnoreCase) => "Victory at Sea",
        _ when productType.Contains("Blood Red Skies", StringComparison.OrdinalIgnoreCase) => "Blood Red Skies",
        _ when productType.Contains("Konflikt", StringComparison.OrdinalIgnoreCase) => "Konflikt '47",
        _ when productType.Contains("Gates of Antares", StringComparison.OrdinalIgnoreCase) => "Beyond the Gates of Antares",
        _ when productType.Contains("Black Seas", StringComparison.OrdinalIgnoreCase) => "Black Seas",
        _ when productType.Contains("Cruel Seas", StringComparison.OrdinalIgnoreCase) => "Cruel Seas",
        _ when productType.Contains("Achtung Panzer", StringComparison.OrdinalIgnoreCase) => "Achtung Panzer!",
        _ when productType.Contains("Erehwon", StringComparison.OrdinalIgnoreCase) => "Warlords of Erehwon",
        _ when productType.Contains("Judge Dredd", StringComparison.OrdinalIgnoreCase) => "Judge Dredd",
        _ when productType.Contains("SPQR", StringComparison.OrdinalIgnoreCase) => "SPQR",
        _ when productType.Contains("Stargrave", StringComparison.OrdinalIgnoreCase) => "Stargrave",
        _ when productType.Contains("Epic Black Powder", StringComparison.OrdinalIgnoreCase) => "Epic Black Powder",
        _ when productType.Contains("Epic Hail Caesar", StringComparison.OrdinalIgnoreCase) => "Epic Hail Caesar",
        _ when productType.Contains("Epic Pike & Shotte", StringComparison.OrdinalIgnoreCase)
            || productType.Contains("Epic Pike And Shotte", StringComparison.OrdinalIgnoreCase) => "Epic Pike & Shotte",
        _ => null,
    };
}

static string? WarlordGamesFaction(ShopifyProduct product, string gameSystem)
{
    if (product.Tags is null) return null;

    string[] boltActionArmies =
    [
        "british", "american", "soviet", "german",
        "japanese", "italian", "french", "finnish",
        "hungarian", "polish", "chinese", "partisan",
    ];

    foreach (string tag in product.Tags)
    {
        string tagLower = tag.ToLowerInvariant();
        string? match = boltActionArmies.FirstOrDefault(a => tagLower.Contains(a));
        if (match is not null)
        {
            // Title-case the faction name
            return char.ToUpper(match[0]) + match[1..];
        }
    }

    return null;
}

// --- Wyrd Games (Shopify) ---

static async Task<IReadOnlyList<RawProduct>> FetchWyrdGamesAllProducts(
    bool verbose, CancellationToken ct)
{
    using var source = new ShopifyProductSource(
        baseUrl: "https://giveusyourmoneypleasethankyou-wyrd.com",
        manufacturer: "Wyrd Games",
        defaultGameSystem: "Malifaux",
        gameSystemExtractor: WyrdGamesGameSystem,
        factionExtractor: WyrdGamesFaction,
        defaultCurrency: "USD",
        verbose: verbose);
    return await source.FetchAllProductsAsync(maxProducts: 0, ct: ct);
}

static string? WyrdGamesGameSystem(ShopifyProduct product)
{
    // Check tags for "The Other Side"
    if (product.Tags?.Any(t => t.Equals("The Other Side", StringComparison.OrdinalIgnoreCase)) == true)
        return "The Other Side";
    // Products tagged with M3e, M4E, or Malifaux are Malifaux
    if (product.Tags?.Any(t =>
        t.Equals("M3e", StringComparison.OrdinalIgnoreCase) ||
        t.Equals("M4E", StringComparison.OrdinalIgnoreCase) ||
        t.Equals("Malifaux", StringComparison.OrdinalIgnoreCase)) == true)
        return "Malifaux";
    return null;
}

static string? WyrdGamesFaction(ShopifyProduct product, string gameSystem)
{
    if (product.Tags is null) return null;

    if (gameSystem == "The Other Side")
    {
        // TOS factions from tags: Abyssinia, CotBM, GHorde, KEmpire, Kimon
        var tosFactionMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["Abyssinia"] = "Abyssinia",
            ["CotBM"] = "Cult of the Burning Man",
            ["GHorde"] = "Gibbering Hordes",
            ["KEmpire"] = "King's Empire",
            ["Kimon"] = "Kimon",
        };
        foreach (string tag in product.Tags)
        {
            if (tosFactionMap.TryGetValue(tag, out string? faction))
                return faction;
        }
        return null;
    }

    // Malifaux factions
    string[] factions =
    [
        "Guild", "Resurrectionists", "Arcanists", "Arcanist",
        "Neverborn", "Outcasts", "Outcast",
        "Bayou", "Ten Thunders", "Explorer's Society",
    ];

    foreach (string tag in product.Tags)
    {
        // Normalize: "Arcanist" → "Arcanists"
        string? match = factions.FirstOrDefault(f =>
            tag.Equals(f, StringComparison.OrdinalIgnoreCase));
        if (match is not null)
        {
            // Normalize singular to plural
            return match switch
            {
                "Arcanist" => "Arcanists",
                "Outcast" => "Outcasts",
                _ => match,
            };
        }
    }

    // Also check body_html for faction keywords
    string? body = product.BodyHtml;
    if (body is not null)
    {
        foreach (string faction in factions)
        {
            if (body.Contains($"Faction: {faction}", StringComparison.OrdinalIgnoreCase) ||
                body.Contains($"Faction:</strong> {faction}", StringComparison.OrdinalIgnoreCase))
            {
                return faction switch
                {
                    "Arcanist" => "Arcanists",
                    "Outcast" => "Outcasts",
                    _ => faction,
                };
            }
        }
    }

    return null;
}

// --- Mantic Games (WooCommerce) ---

static async Task<IReadOnlyList<RawProduct>> FetchManticGamesAllProducts(
    bool verbose, CancellationToken ct)
{
    // Fetch all products with a placeholder game system, then re-classify
    using var wooCommerce = new WooCommerceProductSource(
        baseUrl: "https://www.manticgames.com",
        manufacturer: "Mantic Games",
        gameSystem: "_unclassified_",
        verbose: verbose);
    IReadOnlyList<RawProduct> all = await wooCommerce.FetchAllProductsAsync(maxProducts: 0, ct: ct);

    // Re-classify each product by game system based on URL/name patterns
    var classified = new List<RawProduct>();
    string[] manticSystems = ["Kings of War", "Deadzone", "Firefight", "Armada", "DreadBall", "Halo: Flashpoint", "The Walking Dead: All Out War"];
    foreach (RawProduct product in all)
    {
        string? matchedSystem = null;
        foreach (string gs in manticSystems)
        {
            if (IsManticGameSystem(product, gs))
            {
                matchedSystem = gs;
                break;
            }
        }
        if (matchedSystem is not null)
            classified.Add(product with { GameSystem = matchedSystem });
    }
    return classified;
}

static bool IsManticGameSystem(RawProduct product, string gameSystem)
{
    // The WooCommerceProductSource sets GameSystem from the constructor parameter,
    // but we need to verify the product actually belongs to this game system.
    // We'll rely on URL/name patterns since categories are already handled.
    string name = product.Name.ToLowerInvariant();
    string? url = product.Url?.ToLowerInvariant();

    return gameSystem switch
    {
        "Kings of War" => url?.Contains("kings-of-war") == true ||
                          name.Contains("kings of war") ||
                          url?.Contains("/kow") == true,
        "Deadzone" => url?.Contains("deadzone") == true ||
                      name.Contains("deadzone"),
        "Firefight" => url?.Contains("firefight") == true ||
                       name.Contains("firefight"),
        "Armada" => url?.Contains("armada") == true ||
                    name.Contains("armada"),
        "DreadBall" => url?.Contains("dreadball") == true ||
                       name.Contains("dreadball"),
        "Halo: Flashpoint" => url?.Contains("halo") == true ||
                              name.Contains("halo") ||
                              name.Contains("flashpoint"),
        "The Walking Dead: All Out War" => url?.Contains("walking-dead") == true ||
                                           url?.Contains("all-out-war") == true ||
                                           name.Contains("walking dead"),
        _ => true,
    };
}

// --- Corvus Belli (AppSync GraphQL API) ---

static async Task<IReadOnlyList<RawProduct>> FetchCorvusBelliProducts(
    string gameSystem, int sample, bool verbose, CancellationToken ct)
{
    // Map game system name to Corvus Belli's API game identifier and category type
    var (apiGame, apiType) = gameSystem switch
    {
        "Infinity" => ("infinity", "wargames"),
        "Warcrow" => ("warcrow", "wargames"),
        "Aristeia!" => ("aristeia", "boardgames"),
        _ => (gameSystem.ToLowerInvariant(), "wargames"),
    };

    using var source = new CorvusBelliProductSource(verbose: verbose);
    return await source.FetchProductsForGameAsync(
        apiGame, apiType, gameSystem,
        maxProducts: sample > 0 ? sample : 0, ct: ct);
}

// --- Atomic Mass Games (WordPress REST API) ---

static async Task<IReadOnlyList<RawProduct>> FetchAtomicMassGamesProducts(
    string gameSystem, int sample, bool verbose, CancellationToken ct)
{
    using var source = new AtomicMassGamesProductSource(verbose: verbose);
    return await source.FetchProductsForGameLineAsync(
        gameSystem,
        maxProducts: sample > 0 ? sample : 0, ct: ct);
}

// --- CMON (WordPress REST API with browser-like User-Agent) ---

static async Task<IReadOnlyList<RawProduct>> FetchCmonProducts(
    string gameSystem, int sample, bool verbose, CancellationToken ct)
{
    await using var source = new CmonProductSource(verbose: verbose);
    return await source.FetchAllProductsAsync(
        maxProducts: sample > 0 ? sample : 0, ct: ct);
}

// --- Privateer Press (physical products mostly discontinued, Warmachine IP now owned by Steamforged Games) ---

static Task<IReadOnlyList<RawProduct>> FetchPrivateerPressProducts(
    string gameSystem, int sample, bool verbose, CancellationToken ct)
{
    if (verbose) Console.WriteLine($"    Privateer Press ({gameSystem}): Warmachine is now sold by Steamforged Games — use 'Steamforged Games' manufacturer instead");
    return Task.FromResult<IReadOnlyList<RawProduct>>([]);
}

// --- Steamforged Games (Shopify: steamforged.com, USD) ---
// Steamforged acquired Warmachine/Hordes IP from Privateer Press in June 2024.
// They sell physical miniatures via Shopify. Multi-brand store: Warmachine, Guild Ball, Godtear, Epic Encounters.

static async Task<IReadOnlyList<RawProduct>> FetchSteamforgedGamesAllProducts(
    bool verbose, CancellationToken ct)
{
    var vendorMap = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
    {
        ["Warmachine"] = ["Warmachine", "Warmachine (app subscribers only)"],
        ["Guild Ball"] = ["Guild Ball"],
        ["Godtear"] = ["Godtear"],
        ["Epic Encounters"] = ["Epic Encounters", "Epic Encounters: Local Legends"],
    };

    var warmachineFactionTagMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["warmachine-cygnar"] = "Cygnar",
        ["warmachine-khador"] = "Khador",
        ["warmachine-cryx"] = "Cryx",
        ["warmachine-orgoth"] = "Orgoth",
        ["warmachine-dusk"] = "Dusk",
        ["warmachine-southern-kriels"] = "Southern Kriels",
        ["warmachine-khymaera"] = "Khymaera",
        ["warmachine-old-umbrey"] = "Old Umbrey",
        ["warmachine-storm-legion"] = "Storm Legion",
        ["warmachine-gravediggers"] = "Gravediggers",
        ["warmachine-crucible-guard"] = "Crucible Guard",
        ["warmachine-crucibleguard"] = "Crucible Guard",
        ["warmachine-mercenary"] = "Mercenary",
    };

    var godtearClassMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["Slayer"] = "Slayer",
        ["Guardian"] = "Guardian",
        ["Maelstrom"] = "Maelstrom",
        ["Shaper"] = "Shaper",
    };
    using var source = new ShopifyProductSource(
        baseUrl: "https://steamforged.com",
        manufacturer: "Steamforged Games",
        defaultGameSystem: "_unclassified_",
        gameSystemExtractor: p =>
        {
            // Classify game system by vendor
            string? vendor = p.Vendor;
            if (string.IsNullOrWhiteSpace(vendor)) return null;

            foreach ((string gs, string[] vendors) in vendorMap)
            {
                if (vendors.Any(v => string.Equals(vendor, v, StringComparison.OrdinalIgnoreCase)))
                    return gs;
            }
            return null;
        },
        productTypeClassifier: p =>
        {
            // Filter out products not from any known game system vendor
            string? vendor = p.Vendor;
            bool isRelevant = !string.IsNullOrWhiteSpace(vendor) &&
                vendorMap.Values.Any(vendors =>
                    vendors.Any(v => string.Equals(vendor, v, StringComparison.OrdinalIgnoreCase)));
            if (!isRelevant)
                return "__skip__";

            return p.ProductType?.ToLowerInvariant() switch
            {
                "miniatures" => "single_kit",
                "terrain" => "terrain",
                "wargame" => "starter_set",
                _ => null,
            };
        },
        factionExtractor: (p, gs) =>
        {
            if (p.Tags is null) return null;

            if (gs == "Warmachine")
            {
                foreach (string tag in p.Tags)
                {
                    if (warmachineFactionTagMap.TryGetValue(tag, out string? faction))
                        return faction;
                }
            }
            else if (gs == "Godtear")
            {
                foreach (string tag in p.Tags)
                {
                    if (godtearClassMap.TryGetValue(tag, out string? cls))
                        return cls;
                }
            }

            return null;
        },
        defaultCurrency: "USD",
        verbose: verbose);

    IReadOnlyList<RawProduct> allProducts = await source.FetchAllProductsAsync(
        maxProducts: 0, ct: ct);

    // Filter out non-matching products
    return allProducts
        .Where(p => p.ProductType != "__skip__")
        .ToList();
}

/// <summary>
/// Holds the YAML deserializer shared by top-level statements in this file, so it isn't
/// rebuilt on every <c>LoadExistingFactionProductsAsync</c> call (once per faction, per run).
/// A file-scoped type is used because top-level statements can't declare their own fields.
/// </summary>
file static class ProductToolYaml
{
    public static readonly IDeserializer Deserializer = CatalogSerializer.CreateDeserializer();
}
