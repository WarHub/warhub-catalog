using WarHub.ProductCatalog.Tool.Configuration;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Enriches raw product data by normalizing product types, statuses,
/// and applying manufacturer-specific logic.
/// </summary>
public static class ProductEnricher
{
    /// <summary>
    /// Converts a RawProduct into a fully enriched Product record.
    /// </summary>
    public static Product Enrich(RawProduct raw)
    {
        var (category, packaging) = CategoryClassifier.Classify(raw);

        return new Product
        {
            Name = raw.Name.Trim(),
            Category = category,
            Packaging = packaging,
            Status = "current",
            Availability = ManufacturerRegistry.NormalizeAvailability(raw.Status),
            FirstSeen = null, // stamped by the reconciler
            Ean = raw.Ean?.Trim(),
            Sku = raw.Sku?.Trim(),
            ProductCode = raw.ProductCode?.Trim(),
            PriceGbp = RoundPrice(raw.PriceGbp),
            PriceUsd = RoundPrice(raw.PriceUsd),
            PriceEur = RoundPrice(raw.PriceEur),
            Url = raw.Url?.Trim(),
            ImageUrl = raw.ImageUrl?.Trim(),
            ReleaseDate = raw.ReleaseDate?.Trim(),
            Description = raw.Description?.Trim(),
            Contents = raw.Contents,
        };
    }

    /// <summary>
    /// Classifies product type based on name and other attributes.
    /// </summary>
    internal static string ClassifyProductType(RawProduct raw)
    {
        if (!string.IsNullOrWhiteSpace(raw.ProductType))
        {
            string normalized = ManufacturerRegistry.NormalizeProductType(raw.ProductType);
            if (normalized != "unknown")
                return normalized;
        }

        string name = raw.Name.ToLowerInvariant();

        if (name.Contains("combat patrol"))
            return "combat_patrol";
        if (name.Contains("battleforce"))
            return "battleforce";
        if (name.Contains("army set") || name.Contains("army box"))
            return "army_box";
        if (name.Contains("starter set") || name.Contains("starter edition") || name.Contains("launch box"))
            return "starter_set";
        if (name.Contains("codex") || name.Contains("battletome") || name.Contains("rulebook"))
            return "book";
        if (name.Contains("paint set") || name.Contains("paint + tools"))
            return "paint_set";
        if (name.Contains("terrain") || name.Contains("scenery") || name.Contains("battlefield"))
            return "terrain";

        // Check price heuristic: higher-priced items are likely box sets
        if (raw.PriceGbp.HasValue)
        {
            if (raw.PriceGbp.Value >= 100)
                return "box_set";
        }

        // Check contents: multiple different units = box set
        if (raw.Contents is { Count: > 1 })
            return "box_set";

        if (raw.Contents is { Count: 1 } && raw.Contents[0].Quantity == 1)
            return "character";

        return "single_kit";
    }

    /// <summary>
    /// Rounds a price to 2 decimal places to avoid floating-point artifacts in YAML output.
    /// </summary>
    private static decimal? RoundPrice(decimal? price)
        => price.HasValue ? Math.Round(price.Value, 2) : null;
}
