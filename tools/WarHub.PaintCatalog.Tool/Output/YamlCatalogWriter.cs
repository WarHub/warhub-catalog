using WarHub.CatalogStore;
using WarHub.PaintCatalog.Tool.Equivalence;
using WarHub.PaintCatalog.Tool.Models;
using YamlDotNet.Serialization;

namespace WarHub.PaintCatalog.Tool.Output;

/// <summary>
/// Writes brand catalog YAML files, manifest, and equivalences to the output directory.
/// Multi-line strings use YAML block scalars (|) for readability.
/// </summary>
public static class YamlCatalogWriter
{
    // THE SHARED SERIALIZER, not a local one. This file used to build its own with a
    // BlockScalarEmitter that handled multi-line strings and nothing else, so every string that
    // LOOKS like a number went out as a plain scalar -- and a plain scalar is a type declaration,
    // not a formatting choice.
    //
    // Measured on the committed equivalences.yaml: ALL 34,172 `productCode` scalars were emitted
    // plain (this file quoted nothing, ever). 13,112 of them are ambiguous and now carry quotes:
    //   - 12,967 a YAML 1.1 reader (PyYAML) re-types, of which 1,093 come back a DIFFERENT VALUE
    //     -- '040' -> 32 read as octal, '71.130' -> 71.13, '85.050' -> 85.05;
    //   - a further 145 PyYAML happens to keep as strings ONLY because a leading-zero code
    //     containing an 8 or a 9 ('008', '029', '049') is not valid octal, while a YAML 1.2 core
    //     -schema reader has no octal rule there and reads every one of them as an int.
    // Which reader you use decided which half of the field was corrupt. That is the whole argument
    // for quoting on the WRITE side rather than documenting a loader requirement.
    //
    // The archive under brands/ has always quoted them, because it goes through CatalogSerializer
    // -- so the two halves of the same catalog disagreed about the type of the one field that
    // joins them, and equivalences.yaml could not be joined to the archive from Python without
    // re-deriving the raw text. Not hypothetical: it produced a false "201 dangling equivalence
    // sources" reading during the AK duplicate retraction -- PaintCatalogApp.cs and
    // PaintRecordMapper.cs carry the true figures that reading displaced.
    //
    // QuotingEventEmitter is a strict superset of what BlockScalarEmitter did -- same literal-block
    // rule for multi-line strings, checked FIRST so a multi-line string that also looks numeric
    // still blocks rather than quotes, plus the ambiguous-scalar rule. Nothing is lost by deleting
    // the local one, and CatalogSerializer's "all catalog data files" claim becomes true rather
    // than aspirational.
    private static readonly ISerializer Serializer = CatalogSerializer.CreateSerializer();

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
}
