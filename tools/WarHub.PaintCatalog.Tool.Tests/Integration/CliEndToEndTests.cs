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

    /// <summary>
    /// The volume precedence chain, asserted through the REAL CLI rather than against the enrichers
    /// in isolation — because the precedence is not a rule any one enricher states, it is the order
    /// PaintCatalogApp calls them in (VolumeEnricher → BarcodeEnricher → OverrideApplier). A
    /// reordering that broke it would leave every unit test green.
    ///
    /// Black:       table 18 → bridge 33            → 33 (manufacturer beats the hardcoded table)
    /// Flat Red:    table 18 → bridge 33 → over 44  → 44 (a hand override beats the manufacturer)
    /// Sand Yellow: table 18, no bridge entry       → 18 (absent volume changes nothing)
    /// </summary>
    [Fact]
    public async Task RunAsync_VolumePrecedence_TableThenManufacturerThenOverride()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-vol-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        Directory.CreateDirectory(srcDir);

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoSample);

            string barcodesPath = Path.Combine(root, "barcodes.yaml");
            await File.WriteAllTextAsync(barcodesPath, """
                vallejo:
                  "Black|Model Color":
                    ean: "8429551709507"
                    volumeMl: 33
                  "Flat Red|Model Color":
                    ean: "8429551709576"
                    volumeMl: 33
                """);

            string overridesPath = Path.Combine(root, "overrides.yaml");
            await File.WriteAllTextAsync(overridesPath, """
                vallejo:
                  "Flat Red|Model Color":
                    volumeMl: 44
                """);

            int exit = await PaintCatalogApp.RunAsync([
                "--source", srcDir, "--output", outDir,
                "--barcodes", barcodesPath, "--overrides", overridesPath]);

            Assert.Equal(0, exit);

            string brandYaml = await File.ReadAllTextAsync(Path.Combine(outDir, "brands", "vallejo.yaml"));
            Assert.Equal(33, VolumeOf(brandYaml, "Black"));
            Assert.Equal(44, VolumeOf(brandYaml, "Flat Red"));
            Assert.Equal(18, VolumeOf(brandYaml, "Sand Yellow"));
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }

    /// <summary>The <c>details.volumeMl</c> of the named paint in a written brand archive.</summary>
    private static int VolumeOf(string brandYaml, string paintName)
    {
        string[] lines = brandYaml.Split('\n');
        int start = Array.FindIndex(lines, l => l.TrimEnd('\r').EndsWith($"name: {paintName}", StringComparison.Ordinal));
        Assert.True(start >= 0, $"No record named '{paintName}' in:\n{brandYaml}");
        for (int i = start + 1; i < lines.Length; i++)
        {
            string line = lines[i].TrimEnd('\r').Trim();
            if (line.StartsWith("- name:", StringComparison.Ordinal)) break; // next record
            if (line.StartsWith("volumeMl:", StringComparison.Ordinal))
                return int.Parse(line["volumeMl:".Length..].Trim());
        }
        Assert.Fail($"No volumeMl for '{paintName}' in:\n{brandYaml}");
        return -1;
    }

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
