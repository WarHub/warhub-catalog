using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Scraping;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.ProductCatalog.Tool.Tests.Scraping;

public class SeedDataLoaderTests
{
    private static readonly ISerializer YamlSerializer = new SerializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .ConfigureDefaultValuesHandling(DefaultValuesHandling.OmitNull)
        .DisableAliases()
        .Build();

    [Fact]
    public async Task LoadAsync_NonExistentDirectory_ReturnsEmpty()
    {
        IReadOnlyList<RawProduct> result = await SeedDataLoader.LoadAsync("/nonexistent/path");

        Assert.Empty(result);
    }

    [Fact]
    public async Task LoadAsync_EmptyDirectory_ReturnsEmpty()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(tempDir);

        try
        {
            IReadOnlyList<RawProduct> result = await SeedDataLoader.LoadAsync(tempDir);
            Assert.Empty(result);
        }
        finally
        {
            Directory.Delete(tempDir, true);
        }
    }

    [Fact]
    public async Task LoadAsync_ValidSeedFile_LoadsProducts()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(tempDir);

        string seedYaml = YamlSerializer.Serialize(new List<RawProduct>
        {
            new()
            {
                Name = "Test Product",
                Manufacturer = "Games Workshop",
                GameSystem = "Warhammer 40,000",
                Faction = "Space Marines",
                Status = "current",
            },
            new()
            {
                Name = "Second Product",
                Manufacturer = "Games Workshop",
                GameSystem = "Warhammer 40,000",
                Faction = "Necrons",
                Status = "current",
            },
        });

        File.WriteAllText(Path.Combine(tempDir, "seed.yaml"), seedYaml);

        try
        {
            IReadOnlyList<RawProduct> result = await SeedDataLoader.LoadAsync(tempDir);

            Assert.Equal(2, result.Count);
            Assert.Equal("Test Product", result[0].Name);
            Assert.Equal("Second Product", result[1].Name);
        }
        finally
        {
            Directory.Delete(tempDir, true);
        }
    }

    [Fact]
    public async Task LoadAsync_MultipleFiles_CombinesProducts()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(tempDir);

        string yaml1 = YamlSerializer.Serialize(new List<RawProduct>
        {
            new() { Name = "Product A", Manufacturer = "Games Workshop", GameSystem = "40k" },
        });
        string yaml2 = YamlSerializer.Serialize(new List<RawProduct>
        {
            new() { Name = "Product B", Manufacturer = "Games Workshop", GameSystem = "AoS" },
        });

        File.WriteAllText(Path.Combine(tempDir, "a.yaml"), yaml1);
        File.WriteAllText(Path.Combine(tempDir, "b.yaml"), yaml2);

        try
        {
            IReadOnlyList<RawProduct> result = await SeedDataLoader.LoadAsync(tempDir);

            Assert.Equal(2, result.Count);
        }
        finally
        {
            Directory.Delete(tempDir, true);
        }
    }

    [Fact]
    public async Task LoadFileAsync_NonExistentFile_ReturnsEmpty()
    {
        IReadOnlyList<RawProduct> result = await SeedDataLoader.LoadFileAsync("/nonexistent.yaml");

        Assert.Empty(result);
    }

    [Fact]
    public async Task LoadFileAsync_ValidFile_LoadsProducts()
    {
        string tempFile = Path.GetTempFileName();
        string yaml = YamlSerializer.Serialize(new List<RawProduct>
        {
            new() { Name = "File Product", Manufacturer = "GW", GameSystem = "40k" },
        });
        File.WriteAllText(tempFile, yaml);

        try
        {
            IReadOnlyList<RawProduct> result = await SeedDataLoader.LoadFileAsync(tempFile);

            Assert.Single(result);
            Assert.Equal("File Product", result[0].Name);
        }
        finally
        {
            File.Delete(tempFile);
        }
    }
}
