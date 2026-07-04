using WarHub.PaintCatalog.Tool.ColorScience;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Equivalence;

/// <summary>
/// Finds cross-brand paint equivalences using CIEDE2000 Delta E color difference.
/// </summary>
public class EquivalenceFinder
{
    private readonly double _closeThreshold;
    private readonly double _substituteThreshold;
    private readonly int _maxMatchesPerPaint;

    public EquivalenceFinder(
        double closeThreshold = 5.0,
        double substituteThreshold = 10.0,
        int maxMatchesPerPaint = 5)
    {
        _closeThreshold = closeThreshold;
        _substituteThreshold = substituteThreshold;
        _maxMatchesPerPaint = maxMatchesPerPaint;
    }

    /// <summary>
    /// Finds equivalences across all brands. For each non-discontinued paint,
    /// finds the best matches from other brands within the substitute threshold.
    /// </summary>
    public EquivalencesFile FindEquivalences(
        IReadOnlyList<BrandCatalog> catalogs)
    {
        // Build flat list of (paint, brand info) pairs, excluding discontinued
        var allPaints = catalogs
            .SelectMany(c => c.Paints
                .Where(p => !p.IsDiscontinued)
                .Select(p => (Paint: p, Brand: c.Brand, BrandSlug: c.BrandSlug)))
            .ToList();

        // Pre-compute Lab values for all paints
        var labValues = allPaints
            .Select(p => CieLab.FromRgb(p.Paint.R, p.Paint.G, p.Paint.B))
            .ToArray();

        var entries = new List<PaintEquivalenceEntry>();

        for (int i = 0; i < allPaints.Count; i++)
        {
            var (sourcePaint, sourceBrand, sourceBrandSlug) = allPaints[i];
            var sourceLab = labValues[i];

            var matches = new List<(int Index, double DeltaE)>();

            for (int j = 0; j < allPaints.Count; j++)
            {
                if (i == j) continue;

                // Only cross-brand matches
                if (allPaints[j].BrandSlug == sourceBrandSlug) continue;

                double deltaE = DeltaE.Ciede2000(sourceLab, labValues[j]);
                if (deltaE <= _substituteThreshold)
                {
                    matches.Add((j, deltaE));
                }
            }

            if (matches.Count == 0) continue;

            // Take best match per brand, sorted by Delta E
            var bestPerBrand = matches
                .GroupBy(m => allPaints[m.Index].BrandSlug)
                .Select(g => g.OrderBy(m => m.DeltaE).First())
                .OrderBy(m => m.DeltaE)
                .Take(_maxMatchesPerPaint)
                .ToList();

            if (bestPerBrand.Count == 0) continue;

            var paintMatches = bestPerBrand.Select(m =>
            {
                var (targetPaint, targetBrand, targetBrandSlug) = allPaints[m.Index];
                string tier = m.DeltaE <= _closeThreshold ? "close" : "substitute";

                return new PaintMatch
                {
                    Paint = new PaintRef
                    {
                        Brand = targetBrand,
                        BrandSlug = targetBrandSlug,
                        Name = targetPaint.Name,
                        ProductCode = targetPaint.ProductCode,
                        Set = targetPaint.Set,
                        Hex = targetPaint.Hex
                    },
                    DeltaE = Math.Round(m.DeltaE, 2),
                    Tier = tier
                };
            }).ToList();

            entries.Add(new PaintEquivalenceEntry
            {
                Source = new PaintRef
                {
                    Brand = sourceBrand,
                    BrandSlug = sourceBrandSlug,
                    Name = sourcePaint.Name,
                    ProductCode = sourcePaint.ProductCode,
                    Set = sourcePaint.Set,
                    Hex = sourcePaint.Hex
                },
                Matches = paintMatches
            });
        }

        return new EquivalencesFile
        {
            Thresholds = new EquivalenceThresholds
            {
                Close = _closeThreshold,
                Substitute = _substituteThreshold
            },
            TotalEntries = entries.Count,
            Equivalences = entries
        };
    }
}
