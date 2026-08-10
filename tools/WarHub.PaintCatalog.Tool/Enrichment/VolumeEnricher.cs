using WarHub.PaintCatalog.Tool.Configuration;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Enriches paints with deterministic net-contents data (volume / weight / container).
///
/// <see cref="VolumeTable"/> is a per-(brand, set) CONSTANT — a floor, not the truth. It writes
/// whatever it states, so it must run before any evidence-backed source: <see cref="BarcodeEnricher"/>
/// overwrites <c>VolumeMl</c> with the manufacturer's own figure where one exists, and
/// <see cref="OverrideApplier"/> beats both. Sets whose real pot size varies per paint (Citadel
/// Technical ships at 12, 18 and 24 ml) cannot be expressed here at all and rely on that.
///
/// Since 2026-08-06 a rule may ABSTAIN on any individual field, so the write is no longer
/// unconditional per field — see <see cref="NetContents"/>. On today's table (38 rules, every one
/// stating both a volume and a container, none stating a weight) that is a no-op: the fold reduces
/// to the previous straight assignment for all 7,903 records the table reaches.
/// </summary>
public static class VolumeEnricher
{
    /// <summary>
    /// Returns a new Paint with the net-contents triple folded in from the brand/set lookup.
    /// </summary>
    public static Paint Enrich(Paint paint, string brandDisplayName)
    {
        var lookup = VolumeTable.Lookup(brandDisplayName, paint.Set);
        if (lookup is null)
            return paint;

        NetContents.Claim merged = NetContents.Merge(
            new NetContents.Claim(lookup.Value.VolumeMl, lookup.Value.WeightG, lookup.Value.Packaging),
            new NetContents.Claim(paint.VolumeMl, paint.WeightG, paint.Packaging));

        return paint with
        {
            VolumeMl = merged.VolumeMl,
            WeightG = merged.WeightG,
            Packaging = merged.Container,
        };
    }
}
