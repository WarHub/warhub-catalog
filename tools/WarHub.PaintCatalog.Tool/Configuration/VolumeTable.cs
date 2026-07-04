namespace WarHub.PaintCatalog.Tool.Configuration;

/// <summary>
/// Deterministic volume and packaging lookup from (brand, set).
/// </summary>
public static class VolumeTable
{
    private static readonly List<VolumeRule> Rules =
    [
        // Citadel Colour
        new("Citadel Colour", ["Base", "Layer", "Air", "Dry", "Glaze", "Edge", "Foundation"], 12, "pot"),
        new("Citadel Colour", ["Shade", "Contrast"], 18, "pot"),
        new("Citadel Colour", ["Technical"], 24, "pot"),
        new("Citadel Colour", ["Spray"], 400, "spray"),

        // Vallejo — various ranges
        new("Vallejo", ["Model Color", "Game Color", "Game Color Special FX", "Xpress Color"], 18, "dropper"),
        new("Vallejo", ["Model Air", "Game Air", "Mecha Color", "Surface Primer", "Panzer Aces", "Nocturna Models"], 17, "dropper"),
        new("Vallejo", ["Metal Color"], 32, "dropper"),
        new("Vallejo", ["Liquid Gold"], 35, "dropper"),
        new("Vallejo", ["Premium Airbrush Color"], 60, "dropper"),
        new("Vallejo", ["Hobby Paint"], 18, "dropper"),
        new("Vallejo", ["Arte Deco"], 60, "dropper"),

        // Army Painter
        new("Army Painter", ["Warpaints", "Warpaints Fanatic", "Speedpaint", "Washes"], 18, "dropper"),

        // AK Interactive
        new("AK Interactive", null, 17, "dropper"),

        // AK Real Color
        new("AK Real Color", null, 10, "jar"),

        // Scale75
        new("Scale75", null, 17, "dropper"),

        // Monument (Pro Acryl)
        new("Monument (Pro Acryl)", null, 22, "dropper"),

        // Kimera Kolors
        new("Kimera Kolors", null, 30, "dropper"),

        // Turbo Dork
        new("Turbo Dork", null, 20, "dropper"),

        // Reaper
        new("Reaper", null, 15, "dropper"),

        // P3
        new("P3 (Privateer Press)", null, 18, "pot"),

        // Tamiya
        new("Tamiya", null, 10, "jar"),

        // Humbrol
        new("Humbrol", null, 14, "tin"),

        // Coat D'Armes
        new("Coat D'Armes", null, 18, "dropper"),

        // Foundry
        new("Foundry", null, 20, "pot"),

        // Green Stuff World
        new("Green Stuff World", null, 17, "dropper"),

        // Mr Hobby
        new("Mr Hobby", null, 10, "jar"),

        // Warcolours
        new("Warcolours", null, 15, "dropper"),

        // Mission Models
        new("Mission Models", null, 30, "dropper"),

        // Two Thin Coats
        new("Two Thin Coats", null, 15, "dropper"),

        // AMMO by Mig Jimenez
        new("AMMO by Mig Jimenez", null, 17, "dropper"),
    ];

    /// <summary>
    /// Looks up volume and packaging for a brand/set combination.
    /// Returns null if no match found.
    /// </summary>
    public static (int VolumeMl, string Packaging)? Lookup(string brandDisplayName, string set)
    {
        foreach (VolumeRule rule in Rules)
        {
            if (!string.Equals(rule.BrandDisplayName, brandDisplayName, StringComparison.OrdinalIgnoreCase))
                continue;

            // If rule has specific sets, match against them
            if (rule.Sets is not null)
            {
                // Match set name, handling discontinued suffix
                string cleanSet = set.Contains("(discontinued)", StringComparison.OrdinalIgnoreCase)
                    ? set[..set.IndexOf('(')].Trim()
                    : set;

                if (rule.Sets.Any(s => string.Equals(s, cleanSet, StringComparison.OrdinalIgnoreCase)))
                {
                    return (rule.VolumeMl, rule.Packaging);
                }
            }
            else
            {
                // Brand-wide default (no specific set filter)
                return (rule.VolumeMl, rule.Packaging);
            }
        }

        return null;
    }

    private record VolumeRule(string BrandDisplayName, IReadOnlyList<string>? Sets, int VolumeMl, string Packaging);
}
