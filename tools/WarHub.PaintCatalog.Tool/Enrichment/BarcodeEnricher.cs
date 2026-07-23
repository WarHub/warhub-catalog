using WarHub.PaintCatalog.Tool.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Fills a paint's manufacturer <c>Ean</c> from a generated barcode file, keyed the same way as
/// overrides: <c>{brand-slug}</c> → <c>{Name}|{Set}</c> → fields. The file is produced by
/// <c>tools/acquisition/scripts/gen_paint_barcodes.py</c>, which does the fuzzy trade→catalog match
/// once so this side only ever does an exact identity lookup. It only fills a BLANK <c>Ean</c>, so a
/// later hand override in overrides.yaml still wins.
///
/// It deliberately does NOT set <c>ProductCode</c>: that field is part of the paint's identity key
/// (<c>set|name|productCode|hex</c> — see <c>PaintRecordAdapter</c>), so populating it would re-key
/// every matched paint and duplicate it against its archived null-productCode record. The trade
/// product code is kept in the barcode file for reference only. <c>Ean</c> is not part of identity,
/// so it backfills cleanly onto the existing record.
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

            return p with
            {
                Ean = p.Ean ?? barcode.Ean,
            };
        }).ToList();
    }
}
