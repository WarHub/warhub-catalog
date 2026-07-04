using WarHub.PaintCatalog.Tool.Equivalence;
using WarHub.PaintCatalog.Tool.Models;
using YamlDotNet.Core;
using YamlDotNet.Core.Events;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.EventEmitters;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.PaintCatalog.Tool.Output;

/// <summary>
/// Writes brand catalog YAML files, manifest, and equivalences to the output directory.
/// Multi-line strings use YAML block scalars (|) for readability.
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
    /// Writes a brand catalog YAML file to brands/{slug}.yaml.
    /// </summary>
    public static async Task WriteBrandAsync(BrandCatalog catalog, string outputDir)
    {
        string brandsDir = Path.Combine(outputDir, "brands");
        Directory.CreateDirectory(brandsDir);

        string filePath = Path.Combine(brandsDir, $"{catalog.BrandSlug}.yaml");
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
    /// Writes the equivalences.yaml file to the output directory.
    /// </summary>
    public static async Task WriteEquivalencesAsync(EquivalencesFile equivalences, string outputDir)
    {
        Directory.CreateDirectory(outputDir);

        string filePath = Path.Combine(outputDir, "equivalences.yaml");
        string yaml = Serializer.Serialize(equivalences);
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
