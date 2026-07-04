namespace WarHub.PaintCatalog.Tool.Configuration;

/// <summary>
/// Registry of miniature paint brands with metadata for filtering and mapping.
/// </summary>
public static class BrandRegistry
{
    private static readonly Dictionary<string, BrandInfo> Brands = new(StringComparer.OrdinalIgnoreCase)
    {
        ["AK"] = new("AK Interactive", "ak-interactive", "AK.md"),
        ["AKRC"] = new("AK Real Color", "ak-real-color", "AKRC.md"),
        ["Army_Painter"] = new("Army Painter", "army-painter", "Army_Painter.md"),
        ["Citadel_Colour"] = new("Citadel Colour", "citadel-colour", "Citadel_Colour.md"),
        ["CoatDArmes"] = new("Coat D'Armes", "coat-darmes", "CoatDArmes.md"),
        ["Foundry"] = new("Foundry", "foundry", "Foundry.md"),
        ["GreenStuffWorld"] = new("Green Stuff World", "green-stuff-world", "GreenStuffWorld.md"),
        ["Humbrol"] = new("Humbrol", "humbrol", "Humbrol.md"),
        ["KimeraKolors"] = new("Kimera Kolors", "kimera-kolors", "KimeraKolors.md"),
        ["Mig"] = new("AMMO by Mig Jimenez", "ammo-mig", "Mig.md"),
        ["MissionModels"] = new("Mission Models", "mission-models", "MissionModels.md"),
        ["Monument"] = new("Monument (Pro Acryl)", "monument-pro-acryl", "Monument.md"),
        ["MrHobby"] = new("Mr Hobby", "mr-hobby", "MrHobby.md"),
        ["P3"] = new("P3 (Privateer Press)", "p3", "P3.md"),
        ["Reaper"] = new("Reaper", "reaper", "Reaper.md"),
        ["Scale75"] = new("Scale75", "scale75", "Scale75.md"),
        ["Tamiya"] = new("Tamiya", "tamiya", "Tamiya.md"),
        ["TurboDork"] = new("Turbo Dork", "turbo-dork", "TurboDork.md"),
        ["Vallejo"] = new("Vallejo", "vallejo", "Vallejo.md"),
        ["Warcolours"] = new("Warcolours", "warcolours", "Warcolours.md"),
    };

    // Craft/art brands to exclude
    private static readonly HashSet<string> ExcludedFileNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "Acrilex.md", "AppleBarrel.md", "Arteza.md", "Creature.md",
        "Duncan.md", "FolkArt.md", "Golden.md", "Italeri.md",
        "Liquitex.md", "MrPaint.md", "Pantone.md",
        "RAL.md", "Revell.md", "TomColor.md"
    };

    /// <summary>
    /// Gets all registered miniature paint brands.
    /// </summary>
    public static IReadOnlyList<BrandInfo> AllBrands => Brands.Values.ToList();

    /// <summary>
    /// Gets all registered miniature paint brands as a dictionary.
    /// </summary>
    public static IReadOnlyDictionary<string, BrandInfo> GetAll() => Brands;

    /// <summary>
    /// Tries to get brand info from a file name (without path).
    /// </summary>
    public static BrandInfo? GetByFileName(string fileName)
    {
        string key = Path.GetFileNameWithoutExtension(fileName);
        return Brands.GetValueOrDefault(key);
    }

    /// <summary>
    /// Returns true if the file should be excluded (craft/art brand).
    /// </summary>
    public static bool IsExcluded(string fileName) =>
        ExcludedFileNames.Contains(Path.GetFileName(fileName));

    /// <summary>
    /// Returns true if the file is a known miniature paint brand.
    /// </summary>
    public static bool IsMiniatureBrand(string fileName)
    {
        string key = Path.GetFileNameWithoutExtension(fileName);
        return Brands.ContainsKey(key);
    }
}

public record BrandInfo(string DisplayName, string Slug, string FileName);
