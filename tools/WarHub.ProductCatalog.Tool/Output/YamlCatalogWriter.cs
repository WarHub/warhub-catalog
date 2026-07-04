using WarHub.ProductCatalog.Tool.Models;
using YamlDotNet.Core;
using YamlDotNet.Core.Events;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.EventEmitters;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.ProductCatalog.Tool.Output;

/// <summary>
/// Writes faction catalog YAML files and manifest to the output directory.
/// Multi-line strings (descriptions) use YAML block scalars (|) for readability.
/// </summary>
public static class YamlCatalogWriter
{
    private static readonly ISerializer Serializer = new SerializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .WithEventEmitter(next => new BlockScalarEmitter(next))
        .ConfigureDefaultValuesHandling(DefaultValuesHandling.OmitNull)
        .DisableAliases()
        .Build();

    /// <summary>
    /// Writes a faction catalog YAML file to manufacturers/{manufacturer}/{game-system}/{faction}.yaml.
    /// </summary>
    public static async Task WriteFactionAsync(FactionCatalog catalog, string outputDir)
    {
        string dir = Path.Combine(outputDir, "manufacturers",
            catalog.ManufacturerSlug, catalog.GameSystemSlug);
        Directory.CreateDirectory(dir);

        string filePath = Path.Combine(dir, $"{catalog.FactionSlug}.yaml");
        string yaml = Serializer.Serialize(catalog);
        await File.WriteAllTextAsync(filePath, yaml);
    }

    /// <summary>
    /// Writes the manifest.yaml file to the output directory.
    /// </summary>
    public static async Task WriteManifestAsync(Manifest manifest, string outputDir)
    {
        Directory.CreateDirectory(outputDir);

        string filePath = Path.Combine(outputDir, "manifest.yaml");
        string yaml = Serializer.Serialize(manifest);
        await File.WriteAllTextAsync(filePath, yaml);
    }

    /// <summary>
    /// Custom event emitter that uses block scalar style (|) for multi-line strings.
    /// </summary>
    private sealed class BlockScalarEmitter(IEventEmitter next) : ChainedEventEmitter(next)
    {
        public override void Emit(ScalarEventInfo eventInfo, IEmitter emitter)
        {
            if (eventInfo.Source.Type == typeof(string) &&
                eventInfo.Source.Value is string text &&
                text.Contains('\n'))
            {
                eventInfo.Style = ScalarStyle.Literal;
            }

            base.Emit(eventInfo, emitter);
        }
    }
}
