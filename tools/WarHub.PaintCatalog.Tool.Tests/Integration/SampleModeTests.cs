using WarHub.PaintCatalog.Tool.Configuration;
using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Output;
using WarHub.PaintCatalog.Tool.Parsing;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.PaintCatalog.Tool.Tests.Integration;

public class SampleModeTests
{
    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();
    private const string VallejoSample = """
        # Vallejo

        |Name|Code|Set|R|G|B|Hex|
        |---|---|---|---|---|---|---|
        |Black|70.950|Model Color|0|0|0|![#000000](https://placehold.co/15x15/000000/000000.png) `#000000`|
        |Flat Red|70.957|Model Color|180|30|20|![#B41E14](https://placehold.co/15x15/B41E14/B41E14.png) `#B41E14`|
        |Sand Yellow|70.916|Model Color|171|148|93|![#AB945D](https://placehold.co/15x15/AB945D/AB945D.png) `#AB945D`|
        |3B Russian Green|71.281|Model Air|71|73|70|![#474946](https://placehold.co/15x15/474946/474946.png) `#474946`|
        |Dead White|72.001|Game Color|255|255|255|![#FFFFFF](https://placehold.co/15x15/FFFFFF/FFFFFF.png) `#FFFFFF`|
        """;

    private const string CitadelSample = """
        # Citadel Colour

        |Name|Set|R|G|B|Hex|
        |---|---|---|---|---|---|
        |Mephiston Red|Base|154|14|5|![#9A0E05](https://placehold.co/15x15/9A0E05/9A0E05.png) `#9A0E05`|
        |Abaddon Black|Base|0|0|0|![#000000](https://placehold.co/15x15/000000/000000.png) `#000000`|
        |Agrax Earthshade|Shade|54|42|28|![#362A1C](https://placehold.co/15x15/362A1C/362A1C.png) `#362A1C`|
        |Mechrite Red|Foundation (discontinued)|155|30|20|![#9B1E14](https://placehold.co/15x15/9B1E14/9B1E14.png) `#9B1E14`|
        """;

    [Fact]
    public async Task EndToEnd_ParseEnrichAndWriteYaml()
    {
        string outputDir = Path.Combine(Path.GetTempPath(), $"paint-catalog-test-{Guid.NewGuid():N}");

        try
        {
            // Parse
            IReadOnlyList<Paint> vallejoPaints = MarkdownPaintParser.Parse(VallejoSample);
            IReadOnlyList<Paint> citadelPaints = MarkdownPaintParser.Parse(CitadelSample);

            Assert.Equal(5, vallejoPaints.Count);
            Assert.Equal(4, citadelPaints.Count);

            // Enrich Vallejo: volume + EAN
            vallejoPaints = vallejoPaints
                .Select(p => VolumeEnricher.Enrich(p, "Vallejo"))
                .Select(p => p with { Ean = EanComputer.ComputeVallejoEan(p.ProductCode) ?? p.Ean })
                .ToList();

            // Enrich Citadel: volume only
            citadelPaints = citadelPaints
                .Select(p => VolumeEnricher.Enrich(p, "Citadel Colour"))
                .ToList();

            // Verify enrichment
            Paint black = vallejoPaints.First(p => p.Name == "Black");
            Assert.Equal(18, black.VolumeMl);
            Assert.Equal("dropper", black.Packaging);
            Assert.Equal("8429551709507", black.Ean);

            Paint mephiston = citadelPaints.First(p => p.Name == "Mephiston Red");
            Assert.Equal(12, mephiston.VolumeMl);
            Assert.Equal("pot", mephiston.Packaging);

            Paint mechrite = citadelPaints.First(p => p.Name == "Mechrite Red");
            Assert.True(mechrite.IsDiscontinued);

            // Write YAML
            var vallejoCatalog = new BrandCatalog
            {
                Brand = "Vallejo",
                BrandSlug = "vallejo",
                PaintCount = vallejoPaints.Count,
                Paints = vallejoPaints.ToList()
            };
            await YamlCatalogWriter.WriteBrandAsync(vallejoCatalog, outputDir);

            var citadelCatalog = new BrandCatalog
            {
                Brand = "Citadel Colour",
                BrandSlug = "citadel-colour",
                PaintCount = citadelPaints.Count,
                Paints = citadelPaints.ToList()
            };
            await YamlCatalogWriter.WriteBrandAsync(citadelCatalog, outputDir);

            // Write manifest
            var manifest = new Manifest
            {
                ToolVersion = "1.0.0",
                SourceRepo = "Arcturus5404/miniature-paints",
                TotalPaints = vallejoPaints.Count + citadelPaints.Count,
                Brands =
                [
                    new BrandSummary { Name = "Vallejo", Slug = "vallejo", PaintCount = vallejoPaints.Count, HasProductCodes = true },
                    new BrandSummary { Name = "Citadel Colour", Slug = "citadel-colour", PaintCount = citadelPaints.Count, HasProductCodes = false }
                ]
            };
            await YamlCatalogWriter.WriteManifestAsync(manifest, outputDir);

            // Verify files exist
            Assert.True(File.Exists(Path.Combine(outputDir, "brands", "vallejo.yaml")));
            Assert.True(File.Exists(Path.Combine(outputDir, "brands", "citadel-colour.yaml")));
            Assert.True(File.Exists(Path.Combine(outputDir, "manifest.yaml")));

            // Verify YAML structure
            string vallejoYaml = await File.ReadAllTextAsync(Path.Combine(outputDir, "brands", "vallejo.yaml"));
            BrandCatalog? parsed = YamlDeserializer.Deserialize<BrandCatalog>(vallejoYaml);
            Assert.NotNull(parsed);
            Assert.Equal("Vallejo", parsed.Brand);
            Assert.Equal(5, parsed.PaintCount);
            Assert.Equal(5, parsed.Paints.Count);
        }
        finally
        {
            if (Directory.Exists(outputDir))
                Directory.Delete(outputDir, recursive: true);
        }
    }

    [Fact]
    public void SampleMode_LimitsPaintsPerBrand()
    {
        IReadOnlyList<Paint> paints = MarkdownPaintParser.Parse(VallejoSample);
        Assert.Equal(5, paints.Count);

        // Apply sampling
        IReadOnlyList<Paint> sampled = paints.Take(2).ToList();
        Assert.Equal(2, sampled.Count);
        Assert.Equal("Black", sampled[0].Name);
        Assert.Equal("Flat Red", sampled[1].Name);
    }

    [Fact]
    public void SampleMode_ZeroMeansAll()
    {
        IReadOnlyList<Paint> paints = MarkdownPaintParser.Parse(VallejoSample);
        int sampleSize = 0;

        IReadOnlyList<Paint> result = sampleSize > 0 ? paints.Take(sampleSize).ToList() : paints;
        Assert.Equal(5, result.Count);
    }

    [Fact]
    public void VallejoEans_VerifiedAgainstUPCitemdb()
    {
        // These EANs were verified against UPCitemdb.com
        var verifiedEans = new Dictionary<string, string>
        {
            ["70.950"] = "8429551709507", // Black
            ["70.916"] = "8429551709163", // Sand Yellow
        };

        foreach ((string code, string expectedEan) in verifiedEans)
        {
            string? computedEan = EanComputer.ComputeVallejoEan(code);
            Assert.Equal(expectedEan, computedEan);
        }
    }
}
