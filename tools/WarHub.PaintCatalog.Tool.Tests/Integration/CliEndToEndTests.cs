using WarHub.PaintCatalog.Tool;

namespace WarHub.PaintCatalog.Tool.Tests.Integration;

/// <summary>
/// Drives the real CLI entrypoint (<see cref="PaintCatalogApp.RunAsync"/>) end to end against a
/// temp fixture: parse -> enrich -> finalize (reconcile + ledger) -> write. This is the only test
/// that exercises the two-phase accumulation + finalization path the way the real CLI does; all
/// other tests exercise the pipeline stages individually.
/// </summary>
public class CliEndToEndTests
{
    // Same minimal shape SampleModeTests relies on: a "# Vallejo" heading + the pipe-table
    // MarkdownPaintParser expects. "Vallejo.md" is a filename BrandRegistry.IsMiniatureBrand
    // recognizes and BrandRegistry.GetByFileName maps to the "vallejo" slug.
    private const string VallejoSample = """
        # Vallejo

        |Name|Code|Set|R|G|B|Hex|
        |---|---|---|---|---|---|---|
        |Black|70.950|Model Color|0|0|0|![#000000](https://placehold.co/15x15/000000/000000.png) `#000000`|
        |Flat Red|70.957|Model Color|180|30|20|![#B41E14](https://placehold.co/15x15/B41E14/B41E14.png) `#B41E14`|
        |Sand Yellow|70.916|Model Color|171|148|93|![#AB945D](https://placehold.co/15x15/AB945D/AB945D.png) `#AB945D`|
        """;

    [Fact]
    public async Task RunAsync_SourceToOutput_WritesArchivalBrandFileAndLedger()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-e2e-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        Directory.CreateDirectory(srcDir);

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoSample);

            int exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir]);

            Assert.Equal(0, exit);

            string brandFile = Path.Combine(outDir, "brands", "vallejo.yaml");
            Assert.True(File.Exists(brandFile), $"Expected brand archive at {brandFile}");
            string brandYaml = await File.ReadAllTextAsync(brandFile);
            Assert.Contains("category: paint", brandYaml);
            Assert.Contains("details:", brandYaml);
            Assert.Contains("name: Black", brandYaml);

            string ledgerFile = Path.Combine(outDir, "_liveness.yaml");
            Assert.True(File.Exists(ledgerFile), $"Expected liveness ledger at {ledgerFile}");
            string ledgerYaml = await File.ReadAllTextAsync(ledgerFile);
            Assert.Contains("vallejo/", ledgerYaml);
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }
}
