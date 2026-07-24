using System.CommandLine;
using System.CommandLine.Parsing;
using System.Reflection;
using WarHub.CatalogStore.Ledger;
using WarHub.CatalogStore.Reconcile;
using WarHub.PaintCatalog.Tool.Configuration;
using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Equivalence;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Output;
using WarHub.PaintCatalog.Tool.Parsing;
using WarHub.PaintCatalog.Tool.Reconcile;
using WarHub.PaintCatalog.Tool.Scraping;

namespace WarHub.PaintCatalog.Tool;

/// <summary>
/// The paint catalog tool's CLI entrypoint, extracted from <c>Program.cs</c> so it can be
/// invoked in-process from tests (see CliEndToEndTests) as well as from the real CLI.
/// </summary>
internal static class PaintCatalogApp
{
    public static async Task<int> RunAsync(string[] args)
    {
        Option<DirectoryInfo?> sourceOption = new("--source")
        {
            Description = "Path to Arcturus5404/miniature-paints/paints/ directory"
        };

        Option<DirectoryInfo> outputOption = new("--output")
        {
            Description = "Output directory for YAML files",
            DefaultValueFactory = _ => new DirectoryInfo("output")
        };

        Option<FileInfo?> overridesOption = new("--overrides")
        {
            Description = "Path to overrides.yaml file"
        };

        Option<FileInfo?> barcodesOption = new("--barcodes")
        {
            Description = "Path to a generated barcode file ({brand}/{Name}|{Set} -> ean/productCode)"
        };

        Option<DirectoryInfo?> harvestOption = new("--harvest")
        {
            Description = "Directory of generated manufacturer harvest files (data/paints/harvest)"
        };

        Option<int> sampleOption = new("--sample")
        {
            Description = "Sample N paints per brand (0 = all)",
            DefaultValueFactory = _ => 0
        };

        Option<string?> brandOption = new("--brand")
        {
            Description = "Process specific brand only (empty = all)"
        };

        Option<bool> equivalencesOption = new("--equivalences")
        {
            Description = "Generate paint equivalences (cross-brand matches via Delta E)"
        };

        Option<bool> scrapeOption = new("--scrape")
        {
            Description = "Enable web scraping for additional brands (Scalemates, Shopify)"
        };

        Option<bool> verboseOption = new("--verbose")
        {
            Description = "Verbose logging"
        };

        RootCommand rootCommand = new("WarHub Paint Catalog Tool — parses Arcturus5404/miniature-paints into structured YAML")
        {
            sourceOption,
            outputOption,
            overridesOption,
            barcodesOption,
            harvestOption,
            sampleOption,
            brandOption,
            equivalencesOption,
            scrapeOption,
            verboseOption
        };

        rootCommand.SetAction(async (parseResult, cancellationToken) =>
        {
            DirectoryInfo? source = parseResult.GetValue(sourceOption);
            DirectoryInfo output = parseResult.GetValue(outputOption)!;
            FileInfo? overrides = parseResult.GetValue(overridesOption);
            FileInfo? barcodes = parseResult.GetValue(barcodesOption);
            DirectoryInfo? harvest = parseResult.GetValue(harvestOption);
            int sample = parseResult.GetValue(sampleOption);
            string? brandFilter = parseResult.GetValue(brandOption);
            bool generateEquivalences = parseResult.GetValue(equivalencesOption);
            bool enableScraping = parseResult.GetValue(scrapeOption);
            bool verbose = parseResult.GetValue(verboseOption);

            if (source is null || !source.Exists)
            {
                if (!enableScraping)
                {
                    Console.Error.WriteLine("Error: --source directory is required and must exist.");
                    Console.Error.WriteLine("Provide the path to the Arcturus5404/miniature-paints/paints/ directory.");
                    Console.Error.WriteLine("Or use --scrape to only scrape web sources.");
                    return 1;
                }
                // Scraping-only mode: skip Arcturus5404 parsing
                if (verbose) Console.WriteLine("Running in scrape-only mode (no --source provided).");
            }

            string[] mdFiles = source is not null && source.Exists
                ? Directory.GetFiles(source.FullName, "*.md")
                : [];
            if (mdFiles.Length == 0 && !enableScraping)
            {
                Console.Error.WriteLine($"Error: No .md files found in {source?.FullName}");
                return 1;
            }

            string outputDir = output.FullName;
            string? overridesPath = overrides?.FullName;
            string? barcodesPath = barcodes?.FullName;
            IReadOnlyDictionary<string, HarvestApplier.BrandHarvest> harvestData =
                HarvestApplier.Load(harvest?.FullName);
            if (verbose && harvestData.Count > 0)
                Console.WriteLine($"Harvest files loaded for {harvestData.Count} brand(s).");
            string toolVersion = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";
            var brandSummaries = new List<BrandSummary>();
            var allCatalogs = new List<BrandCatalog>();

            // Every brand's final flat Paints (post all enrichment, including Shopify) plus whether its
            // source succeeded this run. A single finalization pass below maps -> loads -> reconciles ->
            // ledgers -> writes each brand exactly once, after both phases below have contributed to it.
            var pendingBrands = new Dictionary<string, (string Brand, string BrandSlug, string Source, string License, List<Paint> Paints, bool Succeeded)>(
                StringComparer.OrdinalIgnoreCase);

            string today = DateTime.UtcNow.ToString("yyyy-MM-dd");
            string ledgerPath = Path.Combine(outputDir, "_liveness.yaml");
            LivenessLedger ledger = await LedgerStore.LoadAsync(ledgerPath, cancellationToken);

            // Only a full, unsampled run may drive the liveness ledger. A --sample run is not
            // representative — miss-counting its absent records would spuriously flag real paints as
            // discontinued in the archive. A --brand run only touches its own source, so it is safe.
            bool authoritativeRun = sample == 0;

            if (verbose) Console.WriteLine($"Source: {source?.FullName ?? "(none)"}");
            if (verbose) Console.WriteLine($"Output: {outputDir}");
            if (verbose) Console.WriteLine($"Sample: {(sample > 0 ? sample.ToString() : "all")}");
            if (verbose) Console.WriteLine($"Brand: {brandFilter ?? "all"}");
            if (verbose) Console.WriteLine($"Equivalences: {generateEquivalences}");
            if (verbose) Console.WriteLine($"Scraping: {enableScraping}");

            foreach (string mdFile in mdFiles.OrderBy(f => f))
            {
                string fileName = Path.GetFileName(mdFile);

                // Filter to miniature-relevant brands
                if (!BrandRegistry.IsMiniatureBrand(fileName))
                {
                    if (verbose) Console.WriteLine($"  Skipping {fileName} (not a miniature brand)");
                    continue;
                }

                BrandInfo? brandInfo = BrandRegistry.GetByFileName(fileName);
                if (brandInfo is null) continue;

                // Apply brand filter
                if (!string.IsNullOrEmpty(brandFilter) &&
                    !brandInfo.DisplayName.Equals(brandFilter, StringComparison.OrdinalIgnoreCase))
                {
                    if (verbose) Console.WriteLine($"  Skipping {fileName} (brand filter: {brandFilter})");
                    continue;
                }

                if (verbose) Console.Write($"  Parsing {fileName}...");

                string content = await File.ReadAllTextAsync(mdFile, cancellationToken);
                IReadOnlyList<Paint> paints = MarkdownPaintParser.Parse(content);

                // Apply sampling
                if (sample > 0)
                {
                    paints = paints.Take(sample).ToList();
                }

                // Merge harvested additions (committed manufacturer snapshots) BEFORE the
                // enrichment chain, so volume/type/finish/EAN enrichment treats them like
                // native paints. Skipped on sampled runs: a sample is a smoke test of the
                // Arcturus parse, not a place to grow the catalog.
                if (sample == 0)
                {
                    int before = paints.Count;
                    paints = HarvestApplier.AppendAdditions(paints, brandInfo.Slug, harvestData);
                    if (verbose && paints.Count > before)
                        Console.Write($" +{paints.Count - before} harvested");
                }

                // Enrich with volume/packaging
                paints = paints.Select(p => VolumeEnricher.Enrich(p, brandInfo.DisplayName)).ToList();

                // Enrich with paint type and finish
                paints = paints
                    .Select(p => PaintTypeClassifier.Enrich(p, brandInfo.DisplayName))
                    .Select(p => FinishClassifier.Enrich(p, brandInfo.DisplayName))
                    .ToList();

                // Enrich with Vallejo EAN
                if (brandInfo.DisplayName == "Vallejo")
                {
                    paints = paints.Select(p => p with
                    {
                        Ean = EanComputer.ComputeVallejoEan(p.ProductCode) ?? p.Ean
                    }).ToList();
                }

                // Fill EAN + product code from the generated manufacturer-barcode file (only fills
                // blanks; a manual override below still wins).
                paints = BarcodeEnricher.Apply(paints, brandInfo.Slug, barcodesPath);

                // Fill blank Ean/ImageUrl from the committed manufacturer harvest (exact
                // {Name}|{Set} lookups resolved at generation time; overrides below still win).
                paints = HarvestApplier.ApplyEnrichment(paints, brandInfo.Slug, harvestData);

                // Apply overrides
                paints = OverrideApplier.Apply(paints, brandInfo.Slug, overridesPath);

                bool hasProductCodes = paints.Any(p => p.ProductCode is not null);

                var catalog = new BrandCatalog
                {
                    Brand = brandInfo.DisplayName,
                    BrandSlug = brandInfo.Slug,
                    PaintCount = paints.Count,
                    Paints = paints.ToList()
                };

                allCatalogs.Add(catalog);
                pendingBrands[brandInfo.Slug] = (
                    catalog.Brand, catalog.BrandSlug, catalog.Source, catalog.License,
                    paints.ToList(), Succeeded: paints.Count > 0);

                brandSummaries.Add(new BrandSummary
                {
                    Name = brandInfo.DisplayName,
                    Slug = brandInfo.Slug,
                    HasProductCodes = hasProductCodes
                });

                if (verbose) Console.WriteLine($" {paints.Count} paints");
            }

            // Phase 2: Scrape additional brands from web sources
            if (enableScraping)
            {
                if (verbose) Console.WriteLine("\n--- Web Scraping Phase ---");

                // Scrape brands from Scalemates
                foreach (var (slug, scrapedBrand) in ScrapedBrandRegistry.ScalematesBrands)
                {
                    // Apply brand filter
                    if (!string.IsNullOrEmpty(brandFilter) &&
                        !scrapedBrand.DisplayName.Equals(brandFilter, StringComparison.OrdinalIgnoreCase))
                    {
                        if (verbose) Console.WriteLine($"  Skipping {scrapedBrand.DisplayName} (brand filter: {brandFilter})");
                        continue;
                    }

                    if (verbose) Console.Write($"  Scraping {scrapedBrand.DisplayName} from Scalemates...");

                    using var scraper = new ScalematesPaintSource(verbose: verbose);
                    IReadOnlyList<Paint> scrapedPaints = await scraper.FetchBrandPaintsAsync(
                        scrapedBrand.ScalematesPath, scrapedBrand.DisplayName, cancellationToken);

                    if (scrapedPaints.Count == 0)
                    {
                        if (verbose) Console.WriteLine(" no paints found");
                        continue;
                    }

                    // Apply sampling
                    if (sample > 0)
                        scrapedPaints = scrapedPaints.Take(sample).ToList();

                    // Enrich with volume/packaging (use defaults if scraper didn't provide)
                    scrapedPaints = scrapedPaints.Select(p => p with
                    {
                        VolumeMl = p.VolumeMl ?? scrapedBrand.DefaultVolumeMl,
                        Packaging = p.Packaging ?? scrapedBrand.DefaultPackaging
                    }).ToList();

                    // Enrich with type and finish
                    scrapedPaints = scrapedPaints
                        .Select(p => PaintTypeClassifier.Enrich(p, scrapedBrand.DisplayName))
                        .Select(p => FinishClassifier.Enrich(p, scrapedBrand.DisplayName))
                        .ToList();

                    // Apply overrides
                    scrapedPaints = OverrideApplier.Apply(scrapedPaints, slug, overridesPath);

                    bool hasProductCodes = scrapedPaints.Any(p => p.ProductCode is not null);

                    var catalog = new BrandCatalog
                    {
                        Brand = scrapedBrand.DisplayName,
                        BrandSlug = slug,
                        Source = "Scalemates.com",
                        License = "Scraped",
                        PaintCount = scrapedPaints.Count,
                        Paints = scrapedPaints.ToList()
                    };

                    allCatalogs.Add(catalog);
                    pendingBrands[slug] = (
                        catalog.Brand, catalog.BrandSlug, catalog.Source, catalog.License,
                        scrapedPaints.ToList(), Succeeded: true);

                    brandSummaries.Add(new BrandSummary
                    {
                        Name = scrapedBrand.DisplayName,
                        Slug = slug,
                        HasProductCodes = hasProductCodes
                    });

                    if (verbose) Console.WriteLine($" {scrapedPaints.Count} paints");
                }

                // Enrich existing catalogs with Shopify data (swatch images, SKUs)
                foreach (var (storeSlug, storeInfo) in ScrapedBrandRegistry.ShopifyStores)
                {
                    // Find matching catalog
                    BrandCatalog? matchingCatalog = allCatalogs.FirstOrDefault(c =>
                        c.BrandSlug.Equals(storeSlug, StringComparison.OrdinalIgnoreCase));

                    if (matchingCatalog is null)
                    {
                        if (verbose) Console.WriteLine($"  Skipping Shopify enrichment for {storeSlug} (no matching catalog)");
                        continue;
                    }

                    if (verbose) Console.Write($"  Enriching {matchingCatalog.Brand} from Shopify ({storeInfo.BaseUrl})...");

                    using var shopifySource = new ShopifyPaintSource(storeInfo.BaseUrl, verbose: verbose);

                    var allEnrichment = new Dictionary<string, PaintEnrichmentData>(StringComparer.OrdinalIgnoreCase);
                    foreach (string collection in storeInfo.Collections)
                    {
                        var enrichment = await shopifySource.FetchPaintEnrichmentAsync(collection, cancellationToken);
                        foreach (var (key, value) in enrichment)
                        {
                            allEnrichment.TryAdd(key, value);
                        }
                    }

                    if (allEnrichment.Count == 0)
                    {
                        if (verbose) Console.WriteLine(" no enrichment data found");
                        continue;
                    }

                    // Apply enrichment: match by paint name
                    int enriched = 0;
                    List<Paint> enrichedPaints = matchingCatalog.Paints.Select(p =>
                    {
                        if (allEnrichment.TryGetValue(p.Name, out PaintEnrichmentData? data))
                        {
                            enriched++;
                            return p with
                            {
                                ImageUrl = data.ImageUrl ?? p.ImageUrl,
                                Ean = data.Barcode ?? p.Ean,
                                ProductCode = data.Sku ?? p.ProductCode,
                            };
                        }
                        return p;
                    }).ToList();

                    // Update the catalog with enriched paints
                    var updatedCatalog = matchingCatalog with
                    {
                        Paints = enrichedPaints
                    };

                    // Replace in allCatalogs
                    int idx = allCatalogs.IndexOf(matchingCatalog);
                    if (idx >= 0) allCatalogs[idx] = updatedCatalog;

                    // Carry the enrichment into the pending write: the brand's file is written exactly
                    // once, in the finalization pass below, after all enrichment for it is complete.
                    if (pendingBrands.TryGetValue(storeSlug, out var pendingEntry))
                    {
                        pendingBrands[storeSlug] = (
                            pendingEntry.Brand, pendingEntry.BrandSlug, pendingEntry.Source, pendingEntry.License,
                            enrichedPaints, pendingEntry.Succeeded);
                    }

                    if (verbose) Console.WriteLine($" enriched {enriched}/{matchingCatalog.PaintCount} paints");
                }
            }

            // Finalization: for each brand (after all working-model enrichment, including Shopify, is
            // complete), map its final flat Paints to archival PaintRecords, reconcile them against the
            // existing archive (append-only), update the shared liveness ledger, apply auto-flag /
            // reactivation transitions, and write the brand file exactly once.
            if (verbose) Console.WriteLine("\n--- Finalizing brands (reconcile + ledger + write) ---");

            var adapter = new PaintRecordAdapter();
            var reconciler = new CatalogReconciler<PaintRecord>(adapter);
            int totalPaints = 0;

            // A "full" run additionally requires no --brand filter — a filtered run only
            // touches one brand's source, so orphan GC under it would wrongly conclude that
            // every other, untouched brand's records are gone.
            bool fullRun = authoritativeRun && string.IsNullOrEmpty(brandFilter);

            var liveLedgerKeys = new HashSet<string>(StringComparer.Ordinal);
            var prunableSources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            // Snapshot each brand's last-good ProductCount BEFORE the loop, because
            // LivenessUpdater.Apply mutates ledger.Sources in place — reading the prior count
            // mid-loop could let an earlier brand's write leak into a later brand's "prior".
            // Each brand is its own source and is processed exactly once below, so this is
            // technically safe either way, but snapshotting is the robust pattern (mirrors the
            // product tool's mfgPriorCounts).
            var priorCounts = ledger.Sources.ToDictionary(
                kvp => kvp.Key, kvp => kvp.Value.ProductCount, StringComparer.OrdinalIgnoreCase);

            foreach (var (brandSlug, pending) in pendingBrands.OrderBy(kvp => kvp.Key, StringComparer.Ordinal))
            {
                List<PaintRecord> fresh = pending.Paints.Select(PaintRecordMapper.ToRecord).ToList();
                string brandFilePath = Path.Combine(outputDir, "brands", $"{brandSlug}.yaml");
                IReadOnlyList<PaintRecord> existing = await BrandArchiveWriter.LoadAsync(brandFilePath, cancellationToken);

                (IReadOnlyDictionary<string, string> aliases, ISet<string> retracted) =
                    PaintOverrideAliases.Load(overridesPath, brandSlug);

                ReconcileResult<PaintRecord> reconciled = reconciler.Reconcile(existing, fresh, aliases, retracted, today);

                List<PaintRecord> finalRecords;
                if (authoritativeRun)
                {
                    var seenLedgerKeys = reconciled.SeenKeys
                        .Select(k => $"{brandSlug}/{k}").ToHashSet(StringComparer.Ordinal);
                    var knownLedgerKeys = reconciled.Records
                        .Select(p => $"{brandSlug}/{adapter.IdentityKey(p)}").ToList();
                    var currentlyFlagged = reconciled.Records
                        .Where(p => p.Status == "suspected-discontinued")
                        .Select(p => $"{brandSlug}/{adapter.IdentityKey(p)}")
                        .ToHashSet(StringComparer.Ordinal);

                    // A brand whose fresh scrape came back implausibly smaller than its
                    // last-good count (per the ledger) is treated as unhealthy: it must not
                    // drive miss-flagging this run, and it is excluded from orphan GC below.
                    int priorCount = priorCounts.GetValueOrDefault(brandSlug);
                    bool healthy = pending.Succeeded && !LedgerMaintenance.IsImplausibleDrop(priorCount, pending.Paints.Count);

                    // Orphan-GC bookkeeping: every reconciled record's ledger key is "live"
                    // regardless of this brand's health (pruning is separately gated per-source
                    // via prunableSources below).
                    foreach (string key in knownLedgerKeys)
                        liveLedgerKeys.Add(key);
                    if (healthy)
                        prunableSources.Add(brandSlug);
                    else
                        prunableSources.Remove(brandSlug);

                    LivenessUpdate live = LivenessUpdater.Apply(
                        ledger, brandSlug, sourceSucceeded: healthy, scrapedCount: pending.Paints.Count,
                        seenKeys: seenLedgerKeys, knownKeysForSource: knownLedgerKeys,
                        today: today, currentlyFlaggedKeys: currentlyFlagged);
                    ledger = live.Ledger;

                    // Apply auto-flag / reactivation status transitions onto the records.
                    finalRecords = reconciled.Records.Select(p =>
                    {
                        string lk = $"{brandSlug}/{adapter.IdentityKey(p)}";
                        if (live.Flagged.Contains(lk) && p.Status == "current")
                            // A paint that vanished from the source has genuinely-unknown availability,
                            // not whatever it last reported.
                            return p with { Status = "suspected-discontinued", Availability = "unknown" };
                        if (live.Reactivated.Contains(lk) && p.Status == "suspected-discontinued")
                            return p with { Status = "current" };
                        return p;
                    }).ToList();
                }
                else
                {
                    finalRecords = reconciled.Records.ToList();
                }

                var archive = new BrandArchive
                {
                    Brand = pending.Brand,
                    BrandSlug = brandSlug,
                    Source = pending.Source,
                    License = pending.License,
                    Paints = finalRecords,
                };

                await BrandArchiveWriter.WriteAsync(archive, outputDir, cancellationToken);
                totalPaints += finalRecords.Count;

                if (verbose) Console.WriteLine($"  {brandSlug}: {finalRecords.Count} archived records ({fresh.Count} fresh this run)");
            }

            // Write manifest
            var manifest = new Manifest
            {
                ToolVersion = toolVersion,
                SourceRepo = "Arcturus5404/miniature-paints",
                Brands = brandSummaries
            };

            await YamlCatalogWriter.WriteManifestAsync(manifest, outputDir);

            // Orphan GC: only a full, authoritative run (no --sample, no --brand filter) may
            // prune the ledger — a sampled or brand-filtered run only observed a subset of
            // records/sources, so it must not conclude that anything unseen is gone.
            if (fullRun)
            {
                IReadOnlyList<string> pruned = LedgerMaintenance.PruneOrphans(ledger, liveLedgerKeys, prunableSources);
                if (verbose && pruned.Count > 0)
                    Console.WriteLine($"Ledger GC: pruned {pruned.Count} orphaned records.");
            }

            if (authoritativeRun)
                await LedgerStore.SaveAsync(ledgerPath, ledger, cancellationToken);

            Console.WriteLine($"Done! Generated catalog: {totalPaints} paints across {brandSummaries.Count} brands → {outputDir}");

            // Generate equivalences if requested
            if (generateEquivalences)
            {
                if (verbose) Console.WriteLine("Computing paint equivalences (CIEDE2000 Delta E)...");

                var sw = System.Diagnostics.Stopwatch.StartNew();
                var finder = new EquivalenceFinder();
                EquivalencesFile equivalences = finder.FindEquivalences(allCatalogs);
                sw.Stop();

                await YamlCatalogWriter.WriteEquivalencesAsync(equivalences, outputDir);

                Console.WriteLine($"Equivalences: {equivalences.TotalEntries} entries computed in {sw.Elapsed.TotalSeconds:F1}s → equivalences.yaml");
            }

            return 0;
        });

        Option<DirectoryInfo> migrateDataOption = new("--data")
        {
            Description = "Path to data/paints",
            Required = true
        };

        Command migrateCommand = new("migrate", "One-time idempotent migration of data/paints to the new schema")
        {
            migrateDataOption,
        };

        migrateCommand.SetAction(async (parseResult, cancellationToken) =>
        {
            DirectoryInfo dir = parseResult.GetValue(migrateDataOption)!;
            string date = DateTime.UtcNow.ToString("yyyy-MM-dd");
            return await WarHub.PaintCatalog.Tool.Migration.PaintMigrator.MigrateAsync(dir.FullName, date, cancellationToken);
        });

        rootCommand.Add(migrateCommand);

        return await rootCommand.Parse(args).InvokeAsync();
    }
}
