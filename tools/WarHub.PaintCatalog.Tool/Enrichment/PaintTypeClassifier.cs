using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Derives paint type from (Brand, Set) classification.
/// Paint type is the primary category (Base, Layer, Shade, etc.) that powers
/// search, filtering, and recipe features in the UI.
/// </summary>
public static class PaintTypeClassifier
{
    /// <summary>
    /// Returns a new Paint with the Type field populated based on brand and set.
    /// </summary>
    public static Paint Enrich(Paint paint, string brandDisplayName)
    {
        string? type = Classify(brandDisplayName, paint.Set, paint.Name);
        if (type is null)
            return paint;

        return paint with { Type = type };
    }

    /// <summary>
    /// Classifies a paint into a type based on brand, set, and name.
    /// Returns null if no classification can be made.
    /// </summary>
    internal static string? Classify(string brandDisplayName, string set, string name)
    {
        string cleanSet = StripDiscontinued(set);

        // Brand-specific classification first
        string? result = brandDisplayName switch
        {
            "Citadel Colour" => ClassifyCitadel(cleanSet),
            "Vallejo" => ClassifyVallejo(cleanSet),
            "Army Painter" => ClassifyArmyPainter(cleanSet),
            "AK Interactive" => ClassifyAkInteractive(cleanSet),
            "AK Real Color" => ClassifyAkRealColor(cleanSet),
            "Scale75" => ClassifyScale75(cleanSet),
            "Monument (Pro Acryl)" => ClassifyMonument(cleanSet),
            "Kimera Kolors" => ClassifyKimeraKolors(cleanSet),
            "Turbo Dork" => ClassifyTurboDork(cleanSet, name),
            "Reaper" => ClassifyReaper(cleanSet),
            "P3 (Privateer Press)" => ClassifyP3(cleanSet),
            "Tamiya" => ClassifyTamiya(cleanSet),
            "Humbrol" => ClassifyHumbrol(cleanSet),
            "Coat D'Armes" => ClassifyCoatDArmes(cleanSet),
            "Foundry" => ClassifyFoundry(cleanSet),
            "Green Stuff World" => ClassifyGreenStuffWorld(cleanSet, name),
            "Mr Hobby" => ClassifyMrHobby(cleanSet),
            "Warcolours" => ClassifyWarcolours(cleanSet),
            "Mission Models" => ClassifyMissionModels(cleanSet),
            "AMMO by Mig Jimenez" => ClassifyAmmo(cleanSet),
            "Two Thin Coats" => ClassifyTwoThinCoats(cleanSet, name),
            _ => null
        };

        // Fallback: try generic set name matching
        return result ?? ClassifyGeneric(cleanSet, name);
    }

    private static string ClassifyCitadel(string set) => set switch
    {
        "Base" => "Base",
        "Layer" => "Layer",
        "Shade" => "Shade",
        "Contrast" => "Contrast",
        "Dry" => "Dry",
        "Air" => "Air",
        "Technical" => "Technical",
        "Edge" => "Layer",
        "Spray" => "Spray",
        "Glaze" => "Glaze",
        "Foundation" => "Base",
        _ => "Standard"
    };

    private static string ClassifyVallejo(string set) => set switch
    {
        "Model Color" => "Standard",
        "Game Color" => "Standard",
        "Game Color Special FX" => "Technical",
        "Model Air" => "Air",
        "Game Air" => "Air",
        "Mecha Color" => "Standard",
        "Metal Color" => "Metallic",
        "Liquid Gold" => "Metallic",
        "Panzer Aces" => "Standard",
        "Xpress Color" => "Contrast",
        "Surface Primer" => "Primer",
        "Premium Airbrush Color" => "Air",
        "Hobby Paint" => "Standard",
        "Nocturna Models" => "Standard",
        "Arte Deco" => "Standard",
        _ => "Standard"
    };

    private static string ClassifyArmyPainter(string set) => set switch
    {
        "Warpaints" => "Standard",
        "Warpaints Fanatic" => "Standard",
        "Speedpaint" => "Speedpaint",
        "Washes" => "Wash",
        _ => "Standard"
    };

    private static string ClassifyAkInteractive(string set)
    {
        if (set.Contains("Air", StringComparison.OrdinalIgnoreCase))
            return "Air";
        if (set.Contains("Primer", StringComparison.OrdinalIgnoreCase))
            return "Primer";
        if (set.Contains("Wash", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        if (set.Contains("Metallic", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        return "Standard";
    }

    private static string ClassifyAkRealColor(string set)
    {
        if (set.Contains("Air", StringComparison.OrdinalIgnoreCase))
            return "Air";
        return "Standard";
    }

    private static string ClassifyScale75(string set)
    {
        if (set.Contains("Metal", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        if (set.Contains("Ink", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        return "Standard";
    }

    private static string ClassifyMonument(string set)
    {
        if (set.Contains("Dark", StringComparison.OrdinalIgnoreCase) ||
            set.Contains("Bold Titanium White", StringComparison.OrdinalIgnoreCase))
            return "Standard";
        return "Standard";
    }

    private static string ClassifyKimeraKolors(string set) => "Standard";

    private static string ClassifyTurboDork(string set, string name)
    {
        if (set.Contains("Metallic", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        if (set.Contains("Turboshift", StringComparison.OrdinalIgnoreCase))
            return "Colorshift";
        if (set.Contains("Flourish", StringComparison.OrdinalIgnoreCase))
            return "Colorshift";
        if (set.Contains("Ground", StringComparison.OrdinalIgnoreCase))
            return "Technical";
        return "Standard";
    }

    private static string ClassifyReaper(string set) => "Standard";

    private static string ClassifyP3(string set)
    {
        if (set.Contains("Wash", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        if (set.Contains("Ink", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        return "Standard";
    }

    private static string ClassifyTamiya(string set)
    {
        if (set.Contains("Spray", StringComparison.OrdinalIgnoreCase))
            return "Spray";
        return "Standard";
    }

    private static string ClassifyHumbrol(string set) => "Standard";

    private static string ClassifyCoatDArmes(string set)
    {
        if (set.Contains("Wash", StringComparison.OrdinalIgnoreCase) ||
            set.Contains("Ink", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        return "Standard";
    }

    private static string ClassifyFoundry(string set) => "Standard";

    private static string ClassifyGreenStuffWorld(string set, string name)
    {
        if (set.Contains("Metallic", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        if (set.Contains("Wash", StringComparison.OrdinalIgnoreCase) ||
            set.Contains("Ink", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        if (set.Contains("Colorshift", StringComparison.OrdinalIgnoreCase) ||
            set.Contains("Chameleon", StringComparison.OrdinalIgnoreCase))
            return "Colorshift";
        return "Standard";
    }

    private static string ClassifyMrHobby(string set) => "Standard";

    private static string ClassifyWarcolours(string set)
    {
        if (set.Contains("Metallic", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        return "Standard";
    }

    private static string ClassifyMissionModels(string set) => "Standard";

    private static string ClassifyAmmo(string set)
    {
        if (set.Contains("Wash", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        if (set.Contains("Metallic", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        if (set.Contains("Primer", StringComparison.OrdinalIgnoreCase))
            return "Primer";
        return "Standard";
    }

    private static string ClassifyTwoThinCoats(string set, string name)
    {
        if (name.Contains("Wash", StringComparison.OrdinalIgnoreCase))
            return "Wash";
        if (name.Contains("Glaze", StringComparison.OrdinalIgnoreCase))
            return "Glaze";
        if (set.Contains("Metallic", StringComparison.OrdinalIgnoreCase))
            return "Metallic";
        if (set.Contains("Varnish", StringComparison.OrdinalIgnoreCase))
            return "Varnish";
        if (set.Contains("Bright", StringComparison.OrdinalIgnoreCase))
            return "Layer";
        return "Standard";
    }

    /// <summary>
    /// Generic fallback classification based on common set/name patterns.
    /// </summary>
    private static string? ClassifyGeneric(string set, string name)
    {
        string setLower = set.ToLowerInvariant();
        string nameLower = name.ToLowerInvariant();

        if (setLower.Contains("wash") || setLower.Contains("shade"))
            return "Wash";
        if (setLower.Contains("contrast") || setLower.Contains("speed") || setLower.Contains("xpress"))
            return "Contrast";
        if (setLower.Contains("air"))
            return "Air";
        if (setLower.Contains("spray") || setLower.Contains("primer"))
            return "Primer";
        if (setLower.Contains("technical") || setLower.Contains("texture") || setLower.Contains("effect"))
            return "Technical";
        if (setLower.Contains("metallic") || setLower.Contains("metal color"))
            return "Metallic";
        if (setLower.Contains("ink"))
            return "Wash";
        if (setLower.Contains("glaze"))
            return "Glaze";
        if (setLower.Contains("dry"))
            return "Dry";

        return null;
    }

    private static string StripDiscontinued(string set)
    {
        int idx = set.IndexOf("(discontinued)", StringComparison.OrdinalIgnoreCase);
        return idx >= 0 ? set[..idx].Trim() : set;
    }
}
