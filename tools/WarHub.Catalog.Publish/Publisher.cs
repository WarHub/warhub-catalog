using System.Text.Json;

namespace WarHub.Catalog.Publish;

internal sealed record PublishOptions(
    string CatalogDir, string PaintsDir, string OutDir, string SchemaDir, Provenance Prov);

internal sealed record PublishResult(
    int Products, int Paints, int Barcodes, int CrossCatalogBarcodes, int Sets, int SetMembers, int Files);

/// <summary>
/// Orchestrates a full publish: read source YAML, emit the dist/ JSON tree (consolidated
/// + partitions + indexes + barcode index + set contents + schemas + manifest), validating every
/// document as it is written.
///
/// Both catalogs are ASSEMBLED before either is WRITTEN. The two shapes are not independent: a
/// Citadel pot is a SKU in one and a colour in the other, joined only by its barcode, and neither
/// side can name the other until both sides' ids exist. So the order is
/// assemble products -> assemble paints -> link -> write both -> write the two relations.
///
/// The relations come last for the same reason and differ only in their join key: the barcode
/// index joins on the code printed on the pot, the set-contents relation on the codes a box states
/// as its contents. Both need every id to exist first, which is why neither can be built upstream.
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

        SetContents setContents = SetContents.Build(
            YamlSource.LoadSetContents(o.CatalogDir), productAssembly.Records, paintAssembly.Records);

        int products = ProductBuilder.Write(productAssembly, o.Prov, writer);
        int paints = PaintBuilder.Write(paintAssembly, o.Prov, writer);

        // Written last of the data documents: they index the two above.
        const string barcodesPath = "barcodes.json";
        writer.Write(barcodesPath, "barcode-index", "barcode-index", null, barcodes.Total,
            barcodes.ToDocument(o.Prov, barcodesPath));

        // Needs both catalogs for the same reason the barcode index does, but joins on a different
        // key: a boxed set's contents are stated as the manufacturer's own codes, resolved upstream
        // to paint identities, and only nameable as paint IDS once PaintBuilder has minted them.
        const string setContentsPath = "set-contents.json";
        writer.Write(setContentsPath, "set-contents", "set-contents", null, setContents.Total,
            setContents.ToDocument(o.Prov, setContentsPath));

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
                // Same reasoning for the boxed-set relation: how many boxes have a known contents
                // list, and how many product->paint edges that comes to, without a second fetch.
                ["sets"] = setContents.Total,
                ["setMembers"] = setContents.Members,
            },
            Files = writer.Files,
        };
        string manifestJson = JsonSerializer.Serialize(manifest, JsonConfig.Options);
        validator.Validate("manifest", manifestJson, "manifest.json");
        File.WriteAllText(Path.Combine(o.OutDir, "manifest.json"), manifestJson);

        return new PublishResult(
            products, paints, barcodes.Total, barcodes.CrossCatalog,
            setContents.Total, setContents.Members, writer.Files.Count + 1);
    }
}
