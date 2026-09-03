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

    /// <summary>
    /// The ledger is per-run operational state and warhub-catalog commits it OUTSIDE data/paints/,
    /// because catalog-publish.yml triggers on that tree and the ledger churns ~8.4k lines a week
    /// with no catalog change behind it. --liveness is what makes that possible, so it is asserted
    /// here on both halves: the ledger appears where the flag points, and NOT at the default
    /// sidecar path -- a silently-ignored flag would still leave a passing "it exists" check on
    /// the default location.
    /// </summary>
    [Fact]
    public async Task RunAsync_LivenessOption_WritesLedgerOutsideTheOutputDirectory()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-liveness-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        string ledgerFile = Path.Combine(root, "state", "paint-liveness.yaml");
        Directory.CreateDirectory(srcDir);

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoSample);

            int exit = await PaintCatalogApp.RunAsync(
                ["--source", srcDir, "--output", outDir, "--liveness", ledgerFile]);

            Assert.Equal(0, exit);
            Assert.True(File.Exists(Path.Combine(outDir, "brands", "vallejo.yaml")));

            // Written where the flag points, directory and all -- the committed layout relies on
            // that for a fresh checkout, and for any run whose state/ dir does not exist yet.
            Assert.True(File.Exists(ledgerFile), $"Expected liveness ledger at {ledgerFile}");
            Assert.Contains("vallejo/", await File.ReadAllTextAsync(ledgerFile));

            // ...and NOT at the default, which in this repository is the path under the trigger.
            Assert.False(
                File.Exists(Path.Combine(outDir, "_liveness.yaml")),
                "--liveness was ignored: the ledger was still written beside --output.");
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }

    // The three colours plus one varnish, which the RoleClassifier files as `varnish` from the
    // name alone -- and which therefore needs `colourless: true` before the archive may be written.
    private const string VallejoWithVarnish = VallejoSample + """

        |Gloss Varnish|70.510|Auxiliaries|255|255|255|![#FFFFFF](https://placehold.co/15x15/FFFFFF/FFFFFF.png) `#FFFFFF`|
        """;

    /// <summary>
    /// The role invariant, both directions, through the real CLI: a varnish without the flag, and
    /// a flagged colour. The run must FAIL and must write NOTHING -- not the brand file, not the
    /// manifest, not the ledger -- because the archive is the only place the two facts meet, and
    /// a half-written one is worse than a refusal.
    /// </summary>
    [Fact]
    public async Task RunAsync_RoleInvariant_FailsTheRunAndWritesNothing()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-role-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        Directory.CreateDirectory(srcDir);

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoWithVarnish);

            // Forward direction: `Gloss Varnish` classifies as varnish and carries no flag.
            int exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir]);
            Assert.Equal(1, exit);
            Assert.False(File.Exists(Path.Combine(outDir, "brands", "vallejo.yaml")), "the brand file was written despite the violation");
            Assert.False(File.Exists(Path.Combine(outDir, "manifest.yaml")), "the manifest was written despite the violation");
            Assert.False(File.Exists(Path.Combine(outDir, "_liveness.yaml")), "the ledger was written despite the violation");

            // Reverse direction: the varnish is flagged now, but so is a colour.
            string overridesPath = Path.Combine(root, "overrides.yaml");
            await File.WriteAllTextAsync(overridesPath, """
                vallejo:
                  "Gloss Varnish|Auxiliaries":
                    colourless: true
                  "Flat Red|Model Color":
                    colourless: true
                """);
            exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir, "--overrides", overridesPath]);
            Assert.Equal(1, exit);
            Assert.False(File.Exists(Path.Combine(outDir, "brands", "vallejo.yaml")));
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }

    /// <summary>
    /// The same fixture with the flag declared: the run passes, and every record carries a role
    /// beside its flag, in the archive's key order.
    /// </summary>
    [Fact]
    public async Task RunAsync_StampsARoleOnEveryRecord()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-role-ok-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        Directory.CreateDirectory(srcDir);

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoWithVarnish);
            string overridesPath = Path.Combine(root, "overrides.yaml");
            await File.WriteAllTextAsync(overridesPath, """
                vallejo:
                  "Gloss Varnish|Auxiliaries":
                    colourless: true
                  "Sand Yellow|Model Color":
                    role: pigment
                """);

            int exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir, "--overrides", overridesPath]);

            Assert.Equal(0, exit);
            string brandYaml = await File.ReadAllTextAsync(Path.Combine(outDir, "brands", "vallejo.yaml"));
            Assert.Equal("colour", FieldOf(brandYaml, "Black", "role"));
            Assert.Equal("colour", FieldOf(brandYaml, "Flat Red", "role"));
            Assert.Equal("pigment", FieldOf(brandYaml, "Sand Yellow", "role"));   // the override outranks the classifier
            Assert.Equal("varnish", FieldOf(brandYaml, "Gloss Varnish", "role"));
            Assert.Equal("true", FieldOf(brandYaml, "Gloss Varnish", "colourless"));
            Assert.Contains("  colourless: true\n  role: varnish\n", brandYaml.Replace("\r\n", "\n"));
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }

    // An archive file for a brand the run's --source does not contain, in the shape the tool
    // writes, with no `role` keys: what every committed brand file looked like before the facet.
    private static string TamiyaArchive(bool clearIsFlagged) => $"""
        brand: Tamiya
        brandSlug: tamiya
        source: Arcturus5404/miniature-paints
        license: MIT
        paints:
        - name: Clear
          category: paint
          status: current
          availability: unknown
        {(clearIsFlagged ? "  colourless: true\n" : "")}  firstSeen: '2026-07-10'
          productCode: X-22
          details:
            set: Acrylics Mini Gloss
            r: 0
            g: 0
            b: 0
            hex: '{(clearIsFlagged ? "" : "#FFFFFF")}'
            volumeMl: 10
            container: jar
            type: Standard
            finish: Gloss
        - name: Flat red
          category: paint
          status: current
          availability: unknown
          firstSeen: '2026-07-10'
          productCode: XF-7
          details:
            set: Acrylics Mini Flat
            r: 180
            g: 30
            b: 20
            hex: '#B41E14'
            volumeMl: 10
            container: jar
            type: Standard
            finish: Matte

        """;

    /// <summary>
    /// The facet is a property of the ARCHIVE, not of which sources ran: a brand file the run did
    /// not produce (two-thin-coats without --scrape, a brand whose source is down) is backfilled
    /// and held to the same invariant. Here the source has only Vallejo; the pre-existing Tamiya
    /// file gains its roles, and a violation inside it stops the whole run.
    /// </summary>
    [Fact]
    public async Task RunAsync_ArchiveOnlyBrands_AreBackfilledAndHeldToTheInvariant()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-role-archive-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        string tamiyaFile = Path.Combine(outDir, "brands", "tamiya.yaml");
        Directory.CreateDirectory(srcDir);
        Directory.CreateDirectory(Path.Combine(outDir, "brands"));

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoSample);

            // The archived `Clear` is a varnish by name and carries no flag: the run must refuse,
            // and refuse for BOTH brands -- Vallejo's clean file must not be written either.
            await File.WriteAllTextAsync(tamiyaFile, TamiyaArchive(clearIsFlagged: false));
            int exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir]);
            Assert.Equal(1, exit);
            Assert.False(File.Exists(Path.Combine(outDir, "brands", "vallejo.yaml")));
            Assert.DoesNotContain("role:", await File.ReadAllTextAsync(tamiyaFile));

            // Flagged, the run passes and the archive-only file is stamped in place.
            await File.WriteAllTextAsync(tamiyaFile, TamiyaArchive(clearIsFlagged: true));
            exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir]);
            Assert.Equal(0, exit);
            string tamiyaYaml = await File.ReadAllTextAsync(tamiyaFile);
            Assert.Equal("varnish", FieldOf(tamiyaYaml, "Clear", "role"));
            Assert.Equal("colour", FieldOf(tamiyaYaml, "Flat red", "role"));
            Assert.Equal("X-22", FieldOf(tamiyaYaml, "Clear", "productCode"));   // nothing else touched
            Assert.True(File.Exists(Path.Combine(outDir, "brands", "vallejo.yaml")));

            // A second run finds nothing to backfill and leaves the file byte-identical.
            exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir]);
            Assert.Equal(0, exit);
            Assert.Equal(tamiyaYaml, await File.ReadAllTextAsync(tamiyaFile));

            // ...but a --brand run never touches a brand it was not asked for.
            await File.WriteAllTextAsync(tamiyaFile, TamiyaArchive(clearIsFlagged: false));
            exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir, "--brand", "Vallejo"]);
            Assert.Equal(0, exit);
            Assert.DoesNotContain("role:", await File.ReadAllTextAsync(tamiyaFile));
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }

    /// <summary>
    /// The invariant's advice -- declare the flag in overrides.yaml -- has to work for the
    /// records it is most likely to name: those no source asserts. An archive-only brand's
    /// `colourless:` and `role:` overrides land, the flag clears the stand-in hex in place, and
    /// the archived history (firstSeen, code) survives the round trip.
    /// </summary>
    [Fact]
    public async Task RunAsync_ArchiveOnlyBrands_TakeTheirOverrides()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-role-archive-ovr-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        string tamiyaFile = Path.Combine(outDir, "brands", "tamiya.yaml");
        Directory.CreateDirectory(srcDir);
        Directory.CreateDirectory(Path.Combine(outDir, "brands"));

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoSample);
            await File.WriteAllTextAsync(tamiyaFile, TamiyaArchive(clearIsFlagged: false));
            string overridesPath = Path.Combine(root, "overrides.yaml");
            await File.WriteAllTextAsync(overridesPath, """
                tamiya:
                  "Clear|Acrylics Mini Gloss":
                    colourless: true
                  "Flat red|Acrylics Mini Flat":
                    role: primer
                """);

            int exit = await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir, "--overrides", overridesPath]);

            Assert.Equal(0, exit);
            string tamiyaYaml = await File.ReadAllTextAsync(tamiyaFile);
            Assert.Equal("true", FieldOf(tamiyaYaml, "Clear", "colourless"));
            Assert.Equal("varnish", FieldOf(tamiyaYaml, "Clear", "role"));
            Assert.Equal("", FieldOf(tamiyaYaml, "Clear", "hex"));            // the stand-in cleared in place
            Assert.Equal("2026-07-10", FieldOf(tamiyaYaml, "Clear", "firstSeen"));
            Assert.Equal("X-22", FieldOf(tamiyaYaml, "Clear", "productCode"));
            Assert.Equal("primer", FieldOf(tamiyaYaml, "Flat red", "role"));  // the override outranks the classifier
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }

    /// <summary>
    /// The same reach inside a PRODUCED brand: a pot the source stopped listing is carried forward
    /// by the reconciler without ever meeting the fresh-path override pass, so its overrides must
    /// land on the archived side. Run 1 archives the varnish; run 2's source no longer lists it,
    /// and the override written between the runs still reaches it, history intact.
    /// </summary>
    [Fact]
    public async Task RunAsync_ARecordTheSourceStoppedListing_StillTakesItsOverrides()
    {
        string root = Path.Combine(Path.GetTempPath(), $"paint-cli-role-unseen-{Guid.NewGuid():N}");
        string srcDir = Path.Combine(root, "src");
        string outDir = Path.Combine(root, "out");
        string overridesPath = Path.Combine(root, "overrides.yaml");
        Directory.CreateDirectory(srcDir);

        try
        {
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoWithVarnish);
            await File.WriteAllTextAsync(overridesPath, """
                vallejo:
                  "Gloss Varnish|Auxiliaries":
                    colourless: true
                """);
            Assert.Equal(0, await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir, "--overrides", overridesPath]));
            string brandFile = Path.Combine(outDir, "brands", "vallejo.yaml");
            string firstSeen = FieldOf(await File.ReadAllTextAsync(brandFile), "Gloss Varnish", "firstSeen")!;

            // The source drops the varnish; the maintainer reclassifies it meanwhile.
            await File.WriteAllTextAsync(Path.Combine(srcDir, "Vallejo.md"), VallejoSample);
            await File.WriteAllTextAsync(overridesPath, """
                vallejo:
                  "Gloss Varnish|Auxiliaries":
                    colourless: true
                    role: cleaner
                """);
            Assert.Equal(0, await PaintCatalogApp.RunAsync(["--source", srcDir, "--output", outDir, "--overrides", overridesPath]));

            string brandYaml = await File.ReadAllTextAsync(brandFile);
            Assert.Equal("cleaner", FieldOf(brandYaml, "Gloss Varnish", "role"));
            Assert.Equal("true", FieldOf(brandYaml, "Gloss Varnish", "colourless"));
            Assert.Equal(firstSeen, FieldOf(brandYaml, "Gloss Varnish", "firstSeen"));   // append-only: history kept
            Assert.Equal("colour", FieldOf(brandYaml, "Black", "role"));                   // the live records are untouched
        }
        finally
        {
            if (Directory.Exists(root))
                Directory.Delete(root, recursive: true);
        }
    }

    /// <summary>The value of a top-level or details key of the named paint in a written brand archive.</summary>
    private static string? FieldOf(string brandYaml, string paintName, string key)
    {
        string[] lines = brandYaml.Split('\n');
        int start = Array.FindIndex(lines, l => l.TrimEnd('\r').EndsWith($"name: {paintName}", StringComparison.Ordinal));
        Assert.True(start >= 0, $"No record named '{paintName}' in:\n{brandYaml}");
        for (int i = start + 1; i < lines.Length; i++)
        {
            string line = lines[i].TrimEnd('\r').Trim();
            if (line.StartsWith("- name:", StringComparison.Ordinal)) break; // next record
            if (line.StartsWith($"{key}:", StringComparison.Ordinal))
                return line[(key.Length + 1)..].Trim().Trim('\'');
        }
        return null;
    }
}
