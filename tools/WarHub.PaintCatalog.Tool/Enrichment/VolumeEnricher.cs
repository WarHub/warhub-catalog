using WarHub.PaintCatalog.Tool.Configuration;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Enriches paints with deterministic volume and packaging data.
///
/// <see cref="VolumeTable"/> is a per-(brand, set) CONSTANT — a floor, not the truth. It writes
/// unconditionally, so it must run before any evidence-backed source: <see cref="BarcodeEnricher"/>
/// overwrites <c>VolumeMl</c> with the manufacturer's own figure where one exists, and
/// <see cref="OverrideApplier"/> beats both. Sets whose real pot size varies per paint (Citadel
/// Technical ships at 12, 18 and 24 ml) cannot be expressed here at all and rely on that.
/// </summary>
public static class VolumeEnricher
{
    /// <summary>
    /// Returns a new Paint with volume and packaging set based on brand/set lookup.
    /// </summary>
    public static Paint Enrich(Paint paint, string brandDisplayName)
    {
        var lookup = VolumeTable.Lookup(brandDisplayName, paint.Set);
        if (lookup is null)
            return paint;

        return paint with
        {
            VolumeMl = lookup.Value.VolumeMl,
            Packaging = lookup.Value.Packaging
        };
    }
}
