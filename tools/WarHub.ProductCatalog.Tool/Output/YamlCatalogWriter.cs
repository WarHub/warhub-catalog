using WarHub.CatalogStore;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Output;

/// <summary>Writes faction catalog YAML files and the manifest using the shared serializer.</summary>
public static class YamlCatalogWriter
{
    private static readonly YamlDotNet.Serialization.ISerializer Serializer = CatalogSerializer.CreateSerializer();

    public static async Task WriteFactionAsync(FactionCatalog catalog, string outputDir)
    {
        string dir = Path.Combine(outputDir, "manufacturers", catalog.ManufacturerSlug, catalog.GameSystemSlug);
        Directory.CreateDirectory(dir);

        string filePath = Path.Combine(dir, $"{catalog.FactionSlug}.yaml");
        await File.WriteAllTextAsync(filePath, Serializer.Serialize(catalog));
    }

    public static async Task WriteManifestAsync(Manifest manifest, string outputDir)
    {
        Directory.CreateDirectory(outputDir);
        string filePath = Path.Combine(outputDir, "manifest.yaml");
        await File.WriteAllTextAsync(filePath, Serializer.Serialize(manifest));
    }
}
