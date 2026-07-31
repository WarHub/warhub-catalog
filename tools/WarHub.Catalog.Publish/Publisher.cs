using System.Text.Json;

namespace WarHub.Catalog.Publish;

internal sealed record PublishOptions(
    string CatalogDir, string PaintsDir, string OutDir, string SchemaDir, Provenance Prov);

internal sealed record PublishResult(int Products, int Paints, int Barcodes, int CrossCatalogBarcodes, int Files);

/// <summary>
/// Orchestrates a full publish: read source YAML, emit the dist/ JSON tree (consolidated
/// + partitions + indexes + barcode index + schemas + manifest), validating every document as it
/// is written.
///
/// Both catalogs are ASSEMBLED before either is WRITTEN. The two shapes are not independent: a
/// Citadel pot is a SKU in one and a colour in the other, joined only by its barcode, and neither
/// side can name the other until both sides' ids exist. So the order is
/// assemble products -> assemble paints -> link -> write both -> write the barcode index.
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

        ProductAssembly productAssembly = ProductBuilder.Assemble(
            YamlSource.LoadCanonicalCatalogs(o.CatalogDir), YamlSource.LoadTaxonomyLabels(o.CatalogDir));
        PaintAssembly paintAssembly = PaintBuilder.Assemble(
            [.. YamlSource.LoadBrands(o.PaintsDir)], YamlSource.LoadEquivalences(o.PaintsDir));

        BarcodeIndex barcodes = BarcodeIndex.Build(productAssembly.Records, paintAssembly.Records);
        barcodes.ApplyTo(productAssembly, paintAssembly);

        int products = ProductBuilder.Write(productAssembly, o.Prov, writer);
        int paints = PaintBuilder.Write(paintAssembly, o.Prov, writer);

        // Written last of the data documents: it indexes both of them.
        const string barcodesPath = "barcodes.json";
        writer.Write(barcodesPath, "barcode-index", "barcode-index", null, barcodes.Total,
            barcodes.ToDocument(o.Prov, barcodesPath));

        writer.CopySchemas(o.SchemaDir);

        // Manifest — the discovery document. Written outside the file list (it indexes the rest).
        var manifest = new ManifestDocument
        {
            Version = o.Prov.Version,
            GeneratedAt = o.Prov.GeneratedAt,
            GitCommit = o.Prov.GitCommit,
            Source = new SourceRef(o.Prov.Repo, o.Prov.Release, o.Prov.PageBaseUrl),
            Counts = new Dictionary<string, int>
            {
                ["products"] = products,
                ["paints"] = paints,
                ["barcodes"] = barcodes.Total,
                // Surfaced on the discovery document so a consumer can see the size of the
                // product/paint overlap without fetching barcodes.json at all.
                ["crossCatalogBarcodes"] = barcodes.CrossCatalog,
            },
            Files = writer.Files,
        };
        string manifestJson = JsonSerializer.Serialize(manifest, JsonConfig.Options);
        validator.Validate("manifest", manifestJson, "manifest.json");
        File.WriteAllText(Path.Combine(o.OutDir, "manifest.json"), manifestJson);

        return new PublishResult(products, paints, barcodes.Total, barcodes.CrossCatalog, writer.Files.Count + 1);
    }
}
