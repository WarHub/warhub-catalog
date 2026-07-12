using System.Text.Json;

namespace WarHub.Catalog.Publish;

internal sealed record PublishOptions(
    string CatalogDir, string PaintsDir, string OutDir, string SchemaDir, Provenance Prov);

internal sealed record PublishResult(int Products, int Paints, int Files);

/// <summary>
/// Orchestrates a full publish: read source YAML, emit the dist/ JSON tree (consolidated
/// + partitions + indexes + schemas + manifest), validating every document as it is written.
/// </summary>
internal static class Publisher
{
    public static PublishResult Run(PublishOptions o)
    {
        SchemaValidator validator = SchemaValidator.LoadFrom(o.SchemaDir);

        if (Directory.Exists(o.OutDir))
        {
            Directory.Delete(o.OutDir, recursive: true);
        }
        Directory.CreateDirectory(o.OutDir);

        var writer = new CatalogWriter(o.OutDir, validator);

        int products = ProductBuilder.Build(
            YamlSource.LoadCanonicalCatalogs(o.CatalogDir), YamlSource.LoadTaxonomyLabels(o.CatalogDir), o.Prov, writer);
        int paints = PaintBuilder.Build(
            [.. YamlSource.LoadBrands(o.PaintsDir)], YamlSource.LoadEquivalences(o.PaintsDir), o.Prov, writer);

        writer.CopySchemas(o.SchemaDir);

        // Manifest — the discovery document. Written outside the file list (it indexes the rest).
        var manifest = new ManifestDocument
        {
            Version = o.Prov.Version,
            GeneratedAt = o.Prov.GeneratedAt,
            GitCommit = o.Prov.GitCommit,
            Source = new SourceRef(o.Prov.Repo, o.Prov.Release, o.Prov.PageBaseUrl),
            Counts = new Dictionary<string, int> { ["products"] = products, ["paints"] = paints },
            Files = writer.Files,
        };
        string manifestJson = JsonSerializer.Serialize(manifest, JsonConfig.Options);
        validator.Validate("manifest", manifestJson, "manifest.json");
        File.WriteAllText(Path.Combine(o.OutDir, "manifest.json"), manifestJson);

        return new PublishResult(products, paints, writer.Files.Count + 1);
    }
}
