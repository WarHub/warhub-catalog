using WarHub.PaintCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Applies the manufacturer's own assertions about a paint from a generated bridge file, keyed the
/// same way as overrides: <c>{brand-slug}</c> → <c>{Name}|{Set}</c> → fields. The file is produced
/// by <c>tools/acquisition/scripts/gen_paint_barcodes.py</c> from the GW trade sheets, which does
/// the fuzzy trade→catalog match once so this side only ever does an exact identity lookup.
///
/// Two fields cross, with DIFFERENT precedence, because they contest different things:
///
/// - <c>Ean</c> fills a BLANK slot only. There is no competing derivation to beat; anything already
///   in the slot came from a hand override or a prior source and must not be clobbered.
/// - <c>VolumeMl</c> OVERWRITES. It is contesting <c>VolumeTable</c>, a hardcoded per-(brand, set)
///   constant that runs earlier in the chain (<c>VolumeEnricher</c>) and always writes — so a
///   fill-blanks rule could never fire, and the whole point is that GW's own SIZE column beats a
///   guess. The table puts Citadel <c>Air</c> at 12 ml; GW ships it at 24 and says so in the trade
///   row's SIZE column and its name (<c>AIR: AVERLAND SUNSET (24ML)</c>). Technical is genuinely
///   mixed (12/18/24 ml), which no per-set constant can express. A hand override still wins:
///   <c>OverrideApplier</c> runs AFTER this in <c>PaintCatalogApp</c>. Precedence is therefore
///   table → this bridge → overrides.yaml, and it is the call order that enforces it.
///
/// A paint can carry MORE than one barcode. Measured on the committed file: 9 sprays are sold as
/// both an R/O-Europe and a UK/ROW trade SKU (one shared SSC code, two live EAN-13s). Those extras
/// land in <c>AdditionalEans</c> so a scan of either still resolves. They are CONCURRENT regional
/// variants, not retired barcodes -- which one occupies <c>Ean</c> is decided only by evidence
/// order, so nothing here may present the others as superseded.
///
/// It deliberately does NOT set <c>ProductCode</c>: that field is part of the paint's identity key
/// (<c>set|name|productCode|hex</c> — see <c>PaintRecordAdapter</c>), so populating it would re-key
/// every matched paint and duplicate it against its archived null-productCode record. The trade
/// product code is kept in the bridge file for reference only. <c>Ean</c> and <c>VolumeMl</c> are
/// not part of identity, so they land cleanly on the existing record.
///
/// <c>Availability</c> deliberately does not cross either -- see the generator's header for why
/// (the trade evidence carries none at all, and it is a volatile per-SKU value that has no business
/// in an append-only archive keyed by paint identity).
/// </summary>
public static class BarcodeEnricher
{
    private static readonly IDeserializer YamlDeserializer = new DeserializerBuilder()
        .WithNamingConvention(CamelCaseNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    public static IReadOnlyList<Paint> Apply(IReadOnlyList<Paint> paints, string brandSlug, string? barcodesPath)
    {
        if (string.IsNullOrEmpty(barcodesPath) || !File.Exists(barcodesPath))
            return paints;

        Dictionary<string, Dictionary<string, PaintOverride>>? file;
        try
        {
            file = YamlDeserializer.Deserialize<Dictionary<string, Dictionary<string, PaintOverride>>>(
                File.ReadAllText(barcodesPath));
        }
        catch
        {
            return paints;
        }

        if (file is null || !file.TryGetValue(brandSlug, out Dictionary<string, PaintOverride>? brandBarcodes))
            return paints;

        return paints.Select(p =>
        {
            string key = $"{p.Name}|{p.Set}";
            if (!brandBarcodes.TryGetValue(key, out PaintOverride? barcode))
                return p;

            string? primary = p.Ean ?? barcode.Ean;
            return p with
            {
                Ean = primary,
                // The file can list a paint under more than one barcode (concurrent regional trade
                // SKUs -- see the class remarks). Keep every one of them: the file's own primary is
                // included as a candidate so it is not lost when the paint already had a different
                // hand-set Ean that wins above.
                AdditionalEans = BarcodeSet.Union(primary, p.AdditionalEans, barcode.AdditionalEans, [barcode.Ean]),
                // Manufacturer-asserted pot size WINS over the VolumeTable guess written upstream
                // by VolumeEnricher; when the bridge has no volume for this paint (older file, or
                // a trade row with a blank SIZE, or two SKUs disagreeing) the table value stands.
                VolumeMl = barcode.VolumeMl ?? p.VolumeMl,
            };
        }).ToList();
    }
}
