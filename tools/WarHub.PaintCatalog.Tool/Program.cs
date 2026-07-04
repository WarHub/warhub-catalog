using System.CommandLine;
using System.CommandLine.Parsing;
using System.Reflection;
using WarHub.PaintCatalog.Tool.Configuration;
using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Equivalence;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Output;
using WarHub.PaintCatalog.Tool.Parsing;
using WarHub.PaintCatalog.Tool.Scraping;

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
    string toolVersion = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";
    var brandSummaries = new List<BrandSummary>();
    var allCatalogs = new List<BrandCatalog>();
    int totalPaints = 0;

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

        await YamlCatalogWriter.WriteBrandAsync(catalog, outputDir);
        allCatalogs.Add(catalog);

        brandSummaries.Add(new BrandSummary
        {
            Name = brandInfo.DisplayName,
            Slug = brandInfo.Slug,
            PaintCount = paints.Count,
            HasProductCodes = hasProductCodes
        });

        totalPaints += paints.Count;

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

            await YamlCatalogWriter.WriteBrandAsync(catalog, outputDir);
            allCatalogs.Add(catalog);

            brandSummaries.Add(new BrandSummary
            {
                Name = scrapedBrand.DisplayName,
                Slug = slug,
                PaintCount = scrapedPaints.Count,
                HasProductCodes = hasProductCodes
            });

            totalPaints += scrapedPaints.Count;

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

            // Re-write the YAML with enriched data
            await YamlCatalogWriter.WriteBrandAsync(updatedCatalog, outputDir);

            if (verbose) Console.WriteLine($" enriched {enriched}/{matchingCatalog.PaintCount} paints");
        }
    }

    // Write manifest
    var manifest = new Manifest
    {
        ToolVersion = toolVersion,
        SourceRepo = "Arcturus5404/miniature-paints",
        TotalPaints = totalPaints,
        Brands = brandSummaries
    };

    await YamlCatalogWriter.WriteManifestAsync(manifest, outputDir);

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

return rootCommand.Parse(args).Invoke();

