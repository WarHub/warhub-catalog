namespace WarHub.PaintCatalog.Tool.Configuration;

/// <summary>
/// Deterministic volume and packaging lookup from (brand, set).
/// </summary>
public static class VolumeTable
{
    private static readonly List<VolumeRule> Rules =
    [
        // Citadel Colour
        new("Citadel Colour", ["Base", "Layer", "Dry", "Glaze", "Edge", "Foundation"], 12, "pot"),
        // Air ships at 24 ml, not 12. It was lumped in with Base/Layer above from this repo's first
        // commit, which made all 78 Air paints 12 ml -- a value with no support anywhere in the
        // data. Measured 2026-07-31 over the committed trade extract: of 926 rows across all 20
        // workbooks whose description names an `AIR:` paint with a size, 926 say `(24ML)` and ZERO
        // say 12; GW's own SIZE column agrees 47/47 on the barcode workbook, and 211 Citadel-Air
        // product names across five independent sources (three retailers, a barcode DB and the
        // trade sheets) all say 24.
        //
        // 24 is era-dependent, and this matters: Citadel Air LAUNCHED in September 2015 at 12 ml
        // and moved to 24 ml in June 2019 (GW's own webstore copy, "usable straight from the 12ml
        // pot", against its June-2019 catalogue listing all 78 Air products as `(24ml) (2019)` with
        // "now in a larger pot"). So a 12 ml Air pot really existed -- it is simply not what any
        // record here describes. Every Air paint in this catalog is post-2019: 30 of the 33 that
        // this rule newly corrects carry a GW-authored `(24ML)` in their own trade-register
        // description (the other 3 only miss an exact name match), and the catalog's 78 Air paints
        // map exactly onto the post-2019 SSC block 28-01..28-80.
        //
        // A PRE-2019 12 ml pot is therefore a different product with its own code and barcode, and
        // must NOT inherit this constant -- give it the manufacturer bridge or an override. That is
        // also why this stays a per-(brand, set) constant rather than becoming a claim about the
        // range for all time.
        //
        // This is a TABLE fix rather than 33 bridge entries because the bridge reads RESOLVED
        // observations, which only hold live SKUs: 31 of the 33 stragglers were culled from GW's
        // register on 2022-06-13 and can never be reached by it. The 2022 event is a re-code plus a
        // cull, NOT a repack -- every one of the 30 Air rows in the `Code Changes` register carries
        // the same `(24ML)` description on both sides with its SSC preserved, while both the
        // product code and the barcode change. So the generations are distinct products of
        // identical volume, and the pre-2022 pots were 24 ml too.
        new("Citadel Colour", ["Air"], 24, "pot"),
        new("Citadel Colour", ["Shade", "Contrast"], 18, "pot"),
        new("Citadel Colour", ["Technical"], 24, "pot"),
        new("Citadel Colour", ["Spray"], 400, "spray"),

        // Vallejo — various ranges
        new("Vallejo", ["Model Color", "Game Color", "Game Color Special FX", "Xpress Color"], 18, "dropper"),
        new("Vallejo", ["Model Air", "Game Air", "Mecha Color", "Surface Primer", "Panzer Aces", "Nocturna Models"], 17, "dropper"),
        new("Vallejo", ["Metal Color"], 32, "dropper"),
        new("Vallejo", ["True Metallic Metal"], 18, "dropper"),
        new("Vallejo", ["Pigment FX"], 30, "jar"),
        // AK promoted ranges (2026-07-24): Quick Gen bottles are 18 ml ("79 COLORS + 1 MEDIUM
        // 18ML" full-range listing); Color Punch ships in the standard 3rd-gen 17 ml dropper.
        new("AK Interactive", ["Quick Gen"], 18, "dropper"),
        new("AK Interactive", ["Color Punch (3rd Gen)"], 17, "dropper"),
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
