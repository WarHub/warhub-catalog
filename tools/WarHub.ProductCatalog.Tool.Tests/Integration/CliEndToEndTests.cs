using WarHub.ProductCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.ProductCatalog.Tool.Tests.Integration;

/// <summary>
/// Drives the real CLI entrypoint (<see cref="ProductCatalogApp.RunAsync"/>) end to end against a
/// temp seed fixture: entry -> seed -> enrich -> reconcile -> write. This is the only test that
/// invokes the CLI pipeline the way the real process does; all other tests exercise the pipeline
/// stages individually.
/// </summary>
/// <remarks>
/// This uses <c>--skip-scrape</c> to avoid any network access, which makes the run
/// NON-authoritative (<c>authoritativeRun = !skipScrape &amp;&amp; sample == 0</c> in
/// <see cref="ProductCatalogApp.RunAsync"/>). As a result the liveness ledger
/// (<c>_liveness.yaml</c>) is NOT written and the auto-flag/reactivation and orphan-GC branches do
/// NOT run on this path — this test therefore does not assert on them. That coverage is provided
/// instead by <see cref="LedgerOrphanGcTests"/> and <see cref="ManufacturerCompleteScrapedTotalTests"/>
/// (which mirror the authoritative-run ledger logic directly), plus the empirical no-churn
/// migration run. A fully-authoritative CLI e2e would require live scraping against real
/// manufacturer sources, which is out of scope for an automated test.
/// </remarks>
public class CliEndToEndTests
{
    private static readonly ISerializer YamlSerializer = new SerializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .ConfigureDefaultValuesHandling(DefaultValuesHandling.OmitNull)
        .DisableAliases()
        .Build();

    [Fact]
    public async Task RunAsync_SeedToOutput_WritesFactionFileAndManifest()
    {
        string root = Path.Combine(Path.GetTempPath(), $"product-cli-e2e-{Guid.NewGuid():N}");
        string seedDir = Path.Combine(root, "seed");
        string outDir = Path.Combine(root, "out");
        Directory.CreateDirectory(seedDir);

        try
        {
            var seedProducts = new List<RawProduct>
            {
                new()
                {
                    Name = "Combat Patrol Space Marines",
                    Sku = "99120101402",
                    Ean = "5011921178629",
                    ProductType = "combat_patrol",
                    PriceGbp = 85.00m,
                    Manufacturer = "Games Workshop",
                    GameSystem = "Warhammer 40,000",
                    Faction = "Space Marines",
                    Status = "current",
                    Contents =
                    [
                        new ProductUnit { UnitName = "Primaris Captain", Quantity = 1, BaseSize = "40mm" },
                        new ProductUnit { UnitName = "Infernus Marines", Quantity = 5, BaseSize = "32mm" },
                    ],
                },
            };

            string seedYaml = YamlSerializer.Serialize(seedProducts);
            await File.WriteAllTextAsync(Path.Combine(seedDir, "gw-40k.yaml"), seedYaml);

            int exit = await ProductCatalogApp.RunAsync(["--seed", seedDir, "--skip-scrape", "--output", outDir]);

            Assert.Equal(0, exit);

            string factionFile = Path.Combine(outDir, "manufacturers", "games-workshop", "warhammer-40k", "space-marines.yaml");
            Assert.True(File.Exists(factionFile), $"Expected faction catalog at {factionFile}");
            string factionYaml = await File.ReadAllTextAsync(factionFile);
            Assert.Contains("category:", factionYaml);
            Assert.Contains("status:", factionYaml);
            Assert.Contains("availability:", factionYaml);
            Assert.Contains("name: Combat Patrol Space Marines", factionYaml);

            string manifestFile = Path.Combine(outDir, "manifest.yaml");
            Assert.True(File.Exists(manifestFile), $"Expected manifest at {manifestFile}");
            string manifestYaml = await File.ReadAllTextAsync(manifestFile);
            Assert.Contains("games-workshop", manifestYaml);

            // --skip-scrape makes this run non-authoritative, so no ledger is written.
            string ledgerFile = Path.Combine(outDir, "_liveness.yaml");
            Assert.False(File.Exists(ledgerFile), $"Non-authoritative run must not write a ledger at {ledgerFile}");
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }
}
