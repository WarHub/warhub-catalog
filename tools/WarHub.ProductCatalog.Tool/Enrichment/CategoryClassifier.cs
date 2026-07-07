using WarHub.ProductCatalog.Tool.Configuration;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Classifies a raw product into the two orthogonal axes:
/// category (what it is) and packaging (how it is sold).
/// </summary>
public static class CategoryClassifier
{
    public static (string Category, string Packaging) Classify(RawProduct raw)
    {
        string legacyType = ProductEnricher.ClassifyProductType(raw);
        return legacyType switch
        {
            "terrain" => ("terrain", "single"),
            "book" => ("book", "single"),
            "paint_set" => ("paint", "bundle"),
            "combat_patrol" or "battleforce" or "army_box" or "box_set" => ("miniatures", "box"),
            "starter_set" => ("miniatures", "starter"),
            _ => ("miniatures", "single"),
        };
    }
}
