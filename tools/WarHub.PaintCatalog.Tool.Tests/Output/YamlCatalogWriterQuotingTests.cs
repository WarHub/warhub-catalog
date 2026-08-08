using WarHub.PaintCatalog.Tool.Equivalence;
using WarHub.PaintCatalog.Tool.Output;

namespace WarHub.PaintCatalog.Tool.Tests.Output;

/// <summary>
/// equivalences.yaml and manifest.yaml must quote number-looking STRINGS, exactly as the brand
/// archive does. This is a joinability contract, not a style preference.
///
/// The two halves of the paint catalog are joined on (brandSlug, name, set, productCode).
/// data/paints/brands/*.yaml has always gone through CatalogSerializer and quotes '040';
/// equivalences.yaml built its own serializer and emitted a bare 040, which a YAML 1.1 reader
/// (PyYAML, the first thing a consumer reaches for) reads as OCTAL 32. Measured on the committed
/// file before the fix: all 34,172 productCode scalars were plain, 13,112 of them ambiguous --
/// 12,967 that PyYAML re-types (1,093 changing VALUE) plus 145 that only PyYAML spares, because a
/// leading-zero code containing an 8 or 9 is not valid octal while a YAML 1.2 reader takes it as
/// an int regardless. The two sides could not be joined without re-deriving the raw text -- and
/// the failure is silent, which is the expensive part: it manufactured a false reading of "201
/// dangling equivalence sources" during the AK duplicate retraction.
///
/// These tests pin the OUTPUT of the writer rather than which serializer it holds. A future
/// change is free to build its own serializer again as long as the bytes still round-trip.
/// </summary>
public class YamlCatalogWriterQuotingTests
{
    private static PaintRef Ref(string productCode) => new()
    {
        Brand = "Monument (Pro Acryl)",
        BrandSlug = "monument-pro-acryl",
        Name = "Black Brown",
        ProductCode = productCode,
        Set = "Monument Pro Acrylic Paints",
        Hex = "#2C2D28",
    };

    private static async Task<string> WriteEquivalences(PaintRef source, PaintRef match)
    {
        string dir = Path.Combine(Path.GetTempPath(), $"eqv-{Guid.NewGuid():N}");
        try
        {
            await YamlCatalogWriter.WriteEquivalencesAsync(new EquivalencesFile
            {
                Thresholds = new EquivalenceThresholds { Close = 2.0, Substitute = 5.0 },
                TotalEntries = 1,
                Equivalences =
                [
                    new PaintEquivalenceEntry
                    {
                        Source = source,
                        Matches = [new PaintMatch { Paint = match, DeltaE = 1.2, Tier = "close" }],
                    },
                ],
            }, dir);
            return await File.ReadAllTextAsync(Path.Combine(dir, "equivalences.yaml"));
        }
        finally
        {
            if (Directory.Exists(dir)) Directory.Delete(dir, recursive: true);
        }
    }

    // '040' is the case that actually shipped wrong. A leading zero makes it octal under YAML 1.1,
    // so the value does not merely change type, it changes to 32.
    [Theory]
    [InlineData("040")]   // octal under YAML 1.1 -> 32
    [InlineData("70.950")] // float -> 70.95, the trailing zero lost
    [InlineData("85.033")] // float, value preserved but type is still wrong for a join
    [InlineData("101")]   // plain int: same digits, still not a string
    [InlineData("5")]
    // The 145 that PyYAML alone gets right, and only by accident: a leading zero makes these look
    // octal, the 8/9 makes them invalid octal, so PyYAML falls back to string while a YAML 1.2
    // core-schema reader (which has no octal rule for a bare 0-prefix) reads them as ints. Pinned
    // because a "does PyYAML re-type it?" rule would have left exactly these unquoted.
    [InlineData("008")]
    [InlineData("029")]
    [InlineData("049")]
    public async Task Equivalences_QuoteNumberLookingProductCodes_InBothRoles(string code)
    {
        string yaml = await WriteEquivalences(Ref(code), Ref(code));

        // Twice: once as the entry's `source`, once inside `matches`. A writer that quoted only
        // one role would leave half the relation unjoinable, which is the harder bug to notice.
        Assert.Equal(2, yaml.Split($"productCode: '{code}'").Length - 1);
        Assert.DoesNotContain($"productCode: {code}\n", yaml);
    }

    // The counterpart: quoting is for ambiguity, not decoration. AK17070/WP1405 must stay bare or
    // every diff in a 9 MB file grows a pair of quotes for nothing.
    [Theory]
    [InlineData("AK17070")]
    [InlineData("WP1406")]
    [InlineData("H462")]
    [InlineData("85.163a")]
    public async Task Equivalences_LeaveUnambiguousProductCodesBare(string code)
    {
        string yaml = await WriteEquivalences(Ref(code), Ref(code));

        Assert.Contains($"productCode: {code}", yaml);
        Assert.DoesNotContain($"productCode: '{code}'", yaml);
    }

    /// <summary>
    /// The regression this file exists to prevent is DRIFT: two serializers in one tool that agree
    /// today and stop agreeing after an unrelated edit. So compare them directly on the exact
    /// field the join uses, rather than trusting that both were remembered.
    /// </summary>
    [Fact]
    public async Task Equivalences_QuoteExactlyAsTheBrandArchiveDoes()
    {
        string archive = CatalogStore.CatalogSerializer.CreateSerializer()
            .Serialize(new { productCode = "040" });
        string equivalences = await WriteEquivalences(Ref("040"), Ref("040"));

        Assert.Contains("productCode: '040'", archive);
        Assert.Contains("productCode: '040'", equivalences);
    }
}
