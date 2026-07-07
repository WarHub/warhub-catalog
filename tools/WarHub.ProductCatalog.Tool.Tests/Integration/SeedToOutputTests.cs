using WarHub.ProductCatalog.Tool.Enrichment;
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;
using WarHub.ProductCatalog.Tool.Scraping;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.ProductCatalog.Tool.Tests.Integration;

public class SeedToOutputTests
{
    private static readonly ISerializer YamlSerializer = new SerializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .ConfigureDefaultValuesHandling(DefaultValuesHandling.OmitNull)
        .DisableAliases()
        .Build();

    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    [Fact]
    public async Task EndToEnd_SeedData_ProducesValidOutput()
    {
        // Arrange: create seed data
        string seedDir = Path.Combine(Path.GetTempPath(), $"seed-{Guid.NewGuid()}");
        string outputDir = Path.Combine(Path.GetTempPath(), $"output-{Guid.NewGuid()}");
        Directory.CreateDirectory(seedDir);

        var seedProducts = new List<RawProduct>
        {
            new()
            {
                Name = "Combat Patrol: Space Marines",
                Sku = "99120101402",
                Ean = "5011921178629",
                ProductType = "combat_patrol",
                PriceGbp = 85.00m,
                Url = "https://www.games-workshop.com/en-GB/combat-patrol-space-marines",
                Manufacturer = "Games Workshop",
                GameSystem = "Warhammer 40,000",
                Faction = "Space Marines",
                Status = "current",
                Contents =
                [
                    new ProductUnit { UnitName = "Primaris Captain", Quantity = 1, BaseSize = "40mm" },
                    new ProductUnit { UnitName = "Infernus Marines", Quantity = 5, BaseSize = "32mm" },
                    new ProductUnit { UnitName = "Terminator Squad", Quantity = 5, BaseSize = "40mm" },
                ],
            },
            new()
            {
                Name = "Necron Warriors",
                Sku = "99120110053",
                PriceGbp = 29.00m,
                Manufacturer = "Games Workshop",
                GameSystem = "Warhammer 40,000",
                Faction = "Necrons",
                Status = "current",
                Contents =
                [
                    new ProductUnit { UnitName = "Necron Warriors", Quantity = 12, BaseSize = "32mm" },
                    new ProductUnit { UnitName = "Canoptek Scarab Swarms", Quantity = 3, BaseSize = "32mm" },
                ],
            },
        };

        string seedYaml = YamlSerializer.Serialize(seedProducts);
        File.WriteAllText(Path.Combine(seedDir, "gw-40k.yaml"), seedYaml);

        try
        {
            // Act: Load → Enrich → Write
            IReadOnlyList<RawProduct> loaded = await SeedDataLoader.LoadAsync(seedDir);

            var grouped = loaded.GroupBy(p => (p.Manufacturer, p.GameSystem, p.Faction ?? "General"));

            foreach (var group in grouped)
            {
                IReadOnlyList<Product> enriched = group
                    .Select(ProductEnricher.Enrich)
                    .ToList();

                var catalog = new FactionCatalog
                {
                    Manufacturer = group.Key.Manufacturer,
                    ManufacturerSlug = "games-workshop",
                    GameSystem = group.Key.GameSystem,
                    GameSystemSlug = "warhammer-40k",
                    Faction = group.Key.Item3,
                    FactionSlug = group.Key.Item3.ToLowerInvariant().Replace(' ', '-'),
                    Products = enriched.ToList(),
                };

                await YamlCatalogWriter.WriteFactionAsync(catalog, outputDir);
            }

            // Assert: Files created correctly
            string smPath = Path.Combine(outputDir, "manufacturers", "games-workshop", "warhammer-40k", "space-marines.yaml");
            string necronPath = Path.Combine(outputDir, "manufacturers", "games-workshop", "warhammer-40k", "necrons.yaml");

            Assert.True(File.Exists(smPath), "Space Marines file should exist");
            Assert.True(File.Exists(necronPath), "Necrons file should exist");

            // Validate Space Marines catalog
            string smYaml = await File.ReadAllTextAsync(smPath);
            FactionCatalog smCatalog = YamlDeserializer.Deserialize<FactionCatalog>(smYaml);

            Assert.Equal("Games Workshop", smCatalog.Manufacturer);
            Assert.Single(smCatalog.Products);
            Assert.Equal("Combat Patrol: Space Marines", smCatalog.Products[0].Name);
            Assert.Equal("miniatures", smCatalog.Products[0].Category);
            Assert.Equal("box", smCatalog.Products[0].Packaging);
            Assert.Equal(85.00m, smCatalog.Products[0].PriceGbp);
            Assert.Equal(3, smCatalog.Products[0].Contents!.Count);

            // Validate Necrons catalog
            string necronYaml = await File.ReadAllTextAsync(necronPath);
            FactionCatalog necronCatalog = YamlDeserializer.Deserialize<FactionCatalog>(necronYaml);
            Assert.Single(necronCatalog.Products);
        }
        finally
        {
            if (Directory.Exists(seedDir)) Directory.Delete(seedDir, true);
            if (Directory.Exists(outputDir)) Directory.Delete(outputDir, true);
        }
    }

    [Fact]
    public async Task EndToEnd_EmptySeed_ProducesNoOutput()
    {
        string seedDir = Path.Combine(Path.GetTempPath(), $"seed-empty-{Guid.NewGuid()}");
        Directory.CreateDirectory(seedDir);

        try
        {
            IReadOnlyList<RawProduct> loaded = await SeedDataLoader.LoadAsync(seedDir);

            Assert.Empty(loaded);
        }
        finally
        {
            Directory.Delete(seedDir, true);
        }
    }
}
