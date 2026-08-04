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

        // Same hazard HarvestApplier documents: `{Name}|{Set}` is not unique, so a keyed entry
        // applied to every match copies one SKU's barcode and pot size onto two different paints.
        // No entry in the committed citadel file lands on an ambiguous key today (measured
        // 2026-08-01: 71 such keys brand-wide, 0 of them here), so this changes nothing now -- it
        // stops the file acquiring that power silently the first time GW ships a same-name,
        // same-set pair. `productCode` disambiguates where it can; anything still ambiguous is
        // skipped, because a barcode on the wrong pot is worse than no barcode.
        var ambiguous = paints.GroupBy(p => $"{p.Name}|{p.Set}", StringComparer.Ordinal)
            .Where(g => g.Count() > 1)
            .ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);

        return paints.Select(p =>
        {
            string key = $"{p.Name}|{p.Set}";
            if (ambiguous.TryGetValue(key, out List<Paint>? rivals)
                && brandBarcodes.TryGetValue(key, out PaintOverride? contested))
            {
                var owner = rivals
                    .Where(r => !string.IsNullOrWhiteSpace(contested.ProductCode)
                                && string.Equals(r.ProductCode, contested.ProductCode, StringComparison.OrdinalIgnoreCase))
                    .ToList();
                if (owner.Count != 1 || !ReferenceEquals(owner[0], p))
                    return p;
            }
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
                // Trade list prices, when the bridge quotes them. Blank-fill only, same as Ean: a
                // hand override still wins. Availability is NOT taken from the same evidence --
                // a trade sheet says what a pot costs, never whether anyone has one in stock.
                // NOTE: measured 2026-08-04, GW's paint workbooks carry NO price column at all
                // (0 of 938 paint observations have one), so these are inert on today's data --
                // kept because the field must exist before the harvest bridge can supply it.
                PriceGbp = p.PriceGbp ?? barcode.PriceGbp,
                PriceUsd = p.PriceUsd ?? barcode.PriceUsd,
                PriceEur = p.PriceEur ?? barcode.PriceEur,
                PriceCad = p.PriceCad ?? barcode.PriceCad,
            };
        }).ToList();
    }
}
