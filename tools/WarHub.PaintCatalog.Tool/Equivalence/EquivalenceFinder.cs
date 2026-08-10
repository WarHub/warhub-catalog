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
    /// Finds equivalences across all brands. For each colour-bearing paint (including
    /// discontinued ones — see below), finds the best cross-brand matches within the threshold.
    /// </summary>
    public EquivalencesFile FindEquivalences(
        IReadOnlyList<BrandCatalog> catalogs)
    {
        // Build flat list of (paint, brand info) pairs, excluding only paints with no known colour
        // (harvested additions carry Hex = "" until an override or swatch-extraction pass fills it
        // — their R/G/B of 0 would otherwise make them match every genuinely black paint).
        //
        // DISCONTINUED PAINTS ARE INCLUDED, deliberately. They used to be filtered out here with no
        // stated reason, which had it exactly backwards for an archival catalog: somebody holding a
        // pot GW stopped making is the single most likely person to need "what can I replace this
        // with", and they were the only people guaranteed to get no answer. Retiring 33 Citadel
        // paints made the cost visible — 7 sources lost their entry and 35 matches vanished purely
        // because the paints became correct about their own status.
        //
        // Kept in BOTH roles rather than source-only, so the relation stays symmetric: if a retired
        // paint matches a current one, the current one matches it back. Every published record
        // carries `status`, so a consumer that only wants buyable substitutes can filter, whereas
        // information dropped here could not be recovered downstream. Measured cost of including
        // them: 133 of 8,270 colour-bearing paints, i.e. 1.03x on an O(n^2) pass.
        var allPaints = catalogs
            .SelectMany(c => c.Paints
                .Where(p => !string.IsNullOrEmpty(p.Hex))
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
