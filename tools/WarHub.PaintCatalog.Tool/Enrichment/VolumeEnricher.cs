using WarHub.PaintCatalog.Tool.Configuration;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Enriches paints with deterministic volume and packaging data.
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
