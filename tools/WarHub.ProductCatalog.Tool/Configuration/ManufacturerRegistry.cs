using System.Text.RegularExpressions;

namespace WarHub.ProductCatalog.Tool.Configuration;

/// <summary>
/// Registry of supported manufacturers, game systems, factions, and product types.
/// </summary>
public static partial class ManufacturerRegistry
{
    // --- Faction lists (must be declared before Manufacturers for static init order) ---

    private static readonly IReadOnlyList<string> Warhammer40kFactions =
    [
        "Space Marines", "Blood Angels", "Dark Angels", "Space Wolves",
        "Black Templars", "Deathwatch", "Grey Knights", "Imperial Knights",
        "Adeptus Mechanicus", "Adeptus Custodes", "Adepta Sororitas",
        "Astra Militarum", "Imperial Agents",
        "Chaos Space Marines", "Death Guard", "Thousand Sons",
        "World Eaters", "Chaos Daemons", "Chaos Knights",
        "Orks", "Tyranids", "Genestealer Cults",
        "Aeldari", "Drukhari", "Harlequins", "Ynnari",
        "Necrons", "T'au Empire", "Leagues of Votann",
        "Adeptus Titanicus",
    ];

    private static readonly IReadOnlyList<string> AgeOfSigmarFactions =
    [
        "Stormcast Eternals", "Cities of Sigmar", "Fyreslayers",
        "Idoneth Deepkin", "Kharadron Overlords", "Lumineth Realm-lords",
        "Seraphon", "Sylvaneth", "Daughters of Khaine",
        "Blades of Khorne", "Disciples of Tzeentch", "Hedonites of Slaanesh",
        "Maggotkin of Nurgle", "Skaven", "Slaves to Darkness",
        "Flesh-eater Courts", "Nighthaunt", "Ossiarch Bonereapers",
        "Soulblight Gravelords", "Ogor Mawtribes", "Orruk Warclans",
        "Gloomspite Gitz", "Sons of Behemat",
    ];

    private static readonly IReadOnlyList<string> HorusHeresyFactions =
    [
        "Legiones Astartes", "Solar Auxilia", "Mechanicum",
    ];

    private static readonly IReadOnlyList<string> MiddleEarthFactions =
    [
        "Good", "Evil",
    ];

    private static readonly IReadOnlyList<string> OtherGamesFactions =
    [
        "Necromunda", "Blood Bowl", "Legions Imperialis",
        "Warhammer Underworlds", "Adeptus Titanicus",
        "Aeronautica Imperialis",
    ];

    private static readonly IReadOnlyList<string> TheOldWorldFactions =
    [
        "The Empire of Man", "Bretonnia", "Dwarfen Mountain Holds",
        "High Elf Realms", "Wood Elf Realms", "Tomb Kings of Khemri",
        "Orc & Goblin Tribes", "Warriors of Chaos", "Beastmen Brayherds",
        "Kingdom of Bretonnia",
    ];

    // --- Corvus Belli ---

    private static readonly IReadOnlyList<string> InfinityFactions =
    [
        "PanOceania", "Yu Jing", "Ariadna", "Haqqislam",
        "Nomads", "Combined Army", "ALEPH", "Tohaa",
        "O-12", "NA2",
    ];

    private static readonly IReadOnlyList<string> WarcrowFactions =
    [
        "Northern Tribes", "Hegemony of Embersig", "Ahlwardt Ice Bears",
        "Varank Nasai", "Scions of Yaldabaoth",
    ];

    // --- Para Bellum ---

    private static readonly IReadOnlyList<string> ConquestFactions =
    [
        "Hundred Kingdoms", "Spires", "Dweghom", "Nords",
        "Old Dominion", "W'adrhŭn", "City States",
        "Sorcerer Kings", "Yoroni", "Weaver Courts",
    ];

    // --- Warlord Games ---

    private static readonly IReadOnlyList<string> BoltActionFactions =
    [
        "British", "American", "Soviet", "German",
        "Japanese", "Italian", "French", "Finnish",
        "Hungarian", "Polish", "Chinese", "Partisan",
    ];

    private static readonly IReadOnlyList<string> BlackPowderFactions =
    [
        "British", "French", "Prussian", "Austrian",
        "Russian", "American", "Confederate", "Zulu",
    ];

    private static readonly IReadOnlyList<string> HailCaesarFactions =
    [
        "Roman", "Celtic", "Greek", "Macedonian",
        "Persian", "Carthaginian", "Germanic",
    ];

    private static readonly IReadOnlyList<string> PikeAndShotteFactions =
    [
        "English Civil War", "Thirty Years War",
        "Royalist", "Parliamentarian",
    ];

    private static readonly IReadOnlyList<string> VictoryAtSeaFactions =
    [
        "Royal Navy", "Kriegsmarine", "US Navy",
        "Imperial Japanese Navy", "Regia Marina",
    ];

    private static readonly IReadOnlyList<string> BloodRedSkiesFactions =
    [
        "RAF", "Luftwaffe", "USAAF",
        "Soviet Air Force", "Imperial Japanese",
    ];

    // --- Wyrd Games ---

    private static readonly IReadOnlyList<string> MalifauxFactions =
    [
        "Guild", "Resurrectionists", "Arcanists", "Neverborn",
        "Outcasts", "Bayou", "Ten Thunders", "Explorer's Society",
    ];

    private static readonly IReadOnlyList<string> TheOtherSideFactions =
    [
        "Abyssinia", "Cult of the Burning Man",
        "Gibbering Hordes", "King's Empire", "Kimon",
    ];

    // --- Mantic Games ---

    private static readonly IReadOnlyList<string> KingsOfWarFactions =
    [
        "Basileans", "Forces of Nature", "Dwarfs", "Elves",
        "Empire of Dust", "Forces of the Abyss", "Abyssal Dwarfs",
        "Goblins", "Nightstalkers", "Ogres",
        "Orcs", "Ratkin", "Undead", "Northern Alliance",
        "Free Dwarfs", "Salamanders", "Sylvan Kin",
        "Twilight Kin", "Riftforged Orcs", "Order of the Green Lady",
        "Xirkaali", "Halflings", "Matsudan",
    ];

    private static readonly IReadOnlyList<string> DeadzoneFactions =
    [
        "Enforcers", "Forge Fathers", "Marauders", "Plague",
        "Rebs", "Asterians", "Veer-myn", "GCPS",
        "Nameless", "Mazon Labs", "Nightstalkers",
    ];

    private static readonly IReadOnlyList<string> FirefightFactions =
    [
        "Enforcers", "Forge Fathers", "Marauders", "Plague",
        "Asterians", "Veer-myn", "GCPS",
        "Nightstalkers", "Mazon Labs",
    ];

    private static readonly IReadOnlyList<string> ArmadaFactions =
    [
        "Basileans", "Empire of Dust", "Dwarfs",
        "Orcs", "Twilight Kin", "Northern Alliance",
    ];

    private static readonly IReadOnlyList<string> HaloFlashpointFactions =
    [
        "UNSC", "The Banished",
    ];

    // --- Atomic Mass Games ---

    private static readonly IReadOnlyList<string> MarvelCrisisProtocolFactions =
    [
        "Avengers", "Cabal", "Brotherhood of Mutants",
        "Black Order", "Asgard", "Web Warriors",
        "Inhumans", "X-Men", "Criminal Syndicate",
        "Defenders", "Midnight Sons", "Guardians of the Galaxy",
        "A-Force", "S.H.I.E.L.D.", "Sentinels",
    ];

    private static readonly IReadOnlyList<string> StarWarsShatterpointFactions =
    [
        "Galactic Republic", "Separatist Alliance",
        "Galactic Empire", "Rebel Alliance",
    ];

    private static readonly IReadOnlyList<string> StarWarsLegionFactions =
    [
        "Galactic Republic", "Separatist Alliance",
        "Galactic Empire", "Rebel Alliance",
    ];

    private static readonly IReadOnlyList<string> StarWarsXWingFactions =
    [
        "Galactic Republic", "Separatist Alliance",
        "Galactic Empire", "Rebel Alliance",
        "Scum and Villainy", "Resistance", "First Order",
    ];

    private static readonly IReadOnlyList<string> StarWarsArmadaFactions =
    [
        "Galactic Republic", "Separatist Alliance",
        "Galactic Empire", "Rebel Alliance",
    ];

    // --- CMON ---

    private static readonly IReadOnlyList<string> AsoiafFactions =
    [
        "Stark", "Lannister", "Night's Watch",
        "Free Folk", "Baratheon", "Targaryen",
        "Greyjoy", "Martell", "Bolton",
        "Neutral",
    ];

    // --- Steamforged Games ---

    private static readonly IReadOnlyList<string> WarmachineFactions =
    [
        "Cygnar", "Khador", "Cryx", "Orgoth",
        "Dusk", "Southern Kriels", "Khymaera",
        "Old Umbrey", "Storm Legion", "Gravediggers",
        "Crucible Guard", "Mercenary",
    ];

    private static readonly IReadOnlyList<string> GuildBallFactions =
    [
        "Alchemists", "Blacksmiths", "Brewers", "Butchers",
        "Cooks", "Engineers", "Farmers", "Fishermen",
        "Hunters", "Masons", "Miners", "Morticians",
        "Navigators", "Order", "Ratcatchers",
        "Shepherds", "Union",
    ];

    private static readonly IReadOnlyList<string> GodtearFactions =
    [
        "Slayer", "Guardian", "Maelstrom", "Shaper",
    ];

    /// <summary>
    /// Known manufacturers with their game systems and factions.
    /// </summary>
    public static IReadOnlyDictionary<string, ManufacturerInfo> Manufacturers { get; } =
        new Dictionary<string, ManufacturerInfo>(StringComparer.OrdinalIgnoreCase)
        {
            ["Games Workshop"] = new ManufacturerInfo(
                "Games Workshop",
                "games-workshop",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Warhammer 40,000"] = new("Warhammer 40,000", "warhammer-40k", Warhammer40kFactions),
                    ["Age of Sigmar"] = new("Age of Sigmar", "age-of-sigmar", AgeOfSigmarFactions),
                    ["Horus Heresy"] = new("Horus Heresy", "horus-heresy", HorusHeresyFactions),
                    ["Middle-earth"] = new("Middle-earth", "middle-earth", MiddleEarthFactions),
                    ["The Old World"] = new("The Old World", "the-old-world", TheOldWorldFactions),
                    ["Other Games"] = new("Other Games", "other-games", OtherGamesFactions),
                }),
            ["Corvus Belli"] = new ManufacturerInfo(
                "Corvus Belli",
                "corvus-belli",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Infinity"] = new("Infinity", "infinity", InfinityFactions),
                    ["Warcrow"] = new("Warcrow", "warcrow", WarcrowFactions),
                    ["Aristeia!"] = new("Aristeia!", "aristeia", []),
                }),
            ["Para Bellum"] = new ManufacturerInfo(
                "Para Bellum",
                "para-bellum",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Conquest"] = new("Conquest", "conquest", ConquestFactions),
                }),
            ["Atomic Mass Games"] = new ManufacturerInfo(
                "Atomic Mass Games",
                "atomic-mass-games",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Star Wars Shatterpoint"] = new("Star Wars Shatterpoint", "star-wars-shatterpoint", StarWarsShatterpointFactions),
                    ["Marvel Crisis Protocol"] = new("Marvel Crisis Protocol", "marvel-crisis-protocol", MarvelCrisisProtocolFactions),
                    ["Star Wars Legion"] = new("Star Wars Legion", "star-wars-legion", StarWarsLegionFactions),
                    ["Star Wars X-Wing"] = new("Star Wars X-Wing", "star-wars-x-wing", StarWarsXWingFactions),
                    ["Star Wars Armada"] = new("Star Wars Armada", "star-wars-armada", StarWarsArmadaFactions),
                }),
            ["Warlord Games"] = new ManufacturerInfo(
                "Warlord Games",
                "warlord-games",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Bolt Action"] = new("Bolt Action", "bolt-action", BoltActionFactions),
                    ["Black Powder"] = new("Black Powder", "black-powder", BlackPowderFactions),
                    ["Hail Caesar"] = new("Hail Caesar", "hail-caesar", HailCaesarFactions),
                    ["Pike & Shotte"] = new("Pike & Shotte", "pike-and-shotte", PikeAndShotteFactions),
                    ["Victory at Sea"] = new("Victory at Sea", "victory-at-sea", VictoryAtSeaFactions),
                    ["Blood Red Skies"] = new("Blood Red Skies", "blood-red-skies", BloodRedSkiesFactions),
                    ["Konflikt '47"] = new("Konflikt '47", "konflikt-47", BoltActionFactions),
                    ["Beyond the Gates of Antares"] = new("Beyond the Gates of Antares", "gates-of-antares", []),
                    ["Black Seas"] = new("Black Seas", "black-seas", []),
                    ["Cruel Seas"] = new("Cruel Seas", "cruel-seas", []),
                    ["Achtung Panzer!"] = new("Achtung Panzer!", "achtung-panzer", []),
                    ["Warlords of Erehwon"] = new("Warlords of Erehwon", "warlords-of-erehwon", []),
                    ["Judge Dredd"] = new("Judge Dredd", "judge-dredd", []),
                    ["SPQR"] = new("SPQR", "spqr", []),
                    ["Stargrave"] = new("Stargrave", "stargrave", []),
                    ["Epic Black Powder"] = new("Epic Black Powder", "epic-black-powder", []),
                    ["Epic Hail Caesar"] = new("Epic Hail Caesar", "epic-hail-caesar", []),
                    ["Epic Pike & Shotte"] = new("Epic Pike & Shotte", "epic-pike-and-shotte", []),
                }),
            ["Wyrd Games"] = new ManufacturerInfo(
                "Wyrd Games",
                "wyrd-games",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Malifaux"] = new("Malifaux", "malifaux", MalifauxFactions),
                    ["The Other Side"] = new("The Other Side", "the-other-side", TheOtherSideFactions),
                }),
            ["Mantic Games"] = new ManufacturerInfo(
                "Mantic Games",
                "mantic-games",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Kings of War"] = new("Kings of War", "kings-of-war", KingsOfWarFactions),
                    ["Deadzone"] = new("Deadzone", "deadzone", DeadzoneFactions),
                    ["Firefight"] = new("Firefight", "firefight", FirefightFactions),
                    ["Armada"] = new("Armada", "armada", ArmadaFactions),
                    ["DreadBall"] = new("DreadBall", "dreadball", []),
                    ["Halo: Flashpoint"] = new("Halo: Flashpoint", "halo-flashpoint", HaloFlashpointFactions),
                    ["The Walking Dead: All Out War"] = new("The Walking Dead: All Out War", "walking-dead-all-out-war", []),
                }),
            ["CMON"] = new ManufacturerInfo(
                "CMON",
                "cmon",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["A Song of Ice and Fire"] = new("A Song of Ice and Fire", "asoiaf", AsoiafFactions),
                }),
            ["Steamforged Games"] = new ManufacturerInfo(
                "Steamforged Games",
                "steamforged-games",
                new Dictionary<string, GameSystemInfo>(StringComparer.OrdinalIgnoreCase)
                {
                    ["Warmachine"] = new("Warmachine", "warmachine", WarmachineFactions),
                    ["Guild Ball"] = new("Guild Ball", "guild-ball", GuildBallFactions),
                    ["Godtear"] = new("Godtear", "godtear", GodtearFactions),
                    ["Epic Encounters"] = new("Epic Encounters", "epic-encounters", []),
                }),
        };

    public static ManufacturerInfo? GetManufacturer(string name)
    {
        return Manufacturers.GetValueOrDefault(name);
    }

    public static string Slugify(string value)
    {
        string slug = value.ToLowerInvariant();
        slug = SlugifyCommaRegex().Replace(slug, "");
        slug = SlugifyWhitespaceRegex().Replace(slug, "-");
        slug = SlugifyMultiDashRegex().Replace(slug, "-");
        return slug.Trim('-');
    }

    [GeneratedRegex(@"[^a-z0-9\s-]")]
    private static partial Regex SlugifyCommaRegex();

    [GeneratedRegex(@"\s+")]
    private static partial Regex SlugifyWhitespaceRegex();

    [GeneratedRegex(@"-{2,}")]
    private static partial Regex SlugifyMultiDashRegex();

    /// <summary>
    /// Known product types for classification.
    /// </summary>
    public static readonly IReadOnlySet<string> ProductTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "single_kit",
        "box_set",
        "combat_patrol",
        "army_box",
        "starter_set",
        "battleforce",
        "character",
        "vehicle",
        "terrain",
        "accessory",
        "book",
        "paint_set",
        "tools",
        "unknown",
    };

    public static string NormalizeProductType(string? productType)
    {
        if (string.IsNullOrWhiteSpace(productType))
            return "unknown";
        string normalized = productType.Trim().ToLowerInvariant().Replace(' ', '_');
        return ProductTypes.Contains(normalized) ? normalized : "unknown";
    }

    public static string NormalizeStatus(string? status)
    {
        return status?.Trim().ToLowerInvariant() switch
        {
            "current" or "available" or "in stock" => "current",
            "discontinued" or "no longer available" => "discontinued",
            "pre-order" or "preorder" or "pre order" => "pre_order",
            "limited" or "limited edition" or "made to order" => "limited",
            "out of stock" or "temporarily out of stock" => "out_of_stock",
            _ => "current",
        };
    }

    public static string NormalizeAvailability(string? status)
    {
        return status?.Trim().ToLowerInvariant() switch
        {
            "current" or "available" or "in stock" => "in_stock",
            "pre-order" or "preorder" or "pre order" => "pre_order",
            "limited" or "limited edition" or "made to order" => "limited",
            "out of stock" or "temporarily out of stock" => "out_of_stock",
            "discontinued" or "no longer available" => "out_of_stock",
            _ => "unknown",
        };
    }
}

public record ManufacturerInfo(
    string Name,
    string Slug,
    IReadOnlyDictionary<string, GameSystemInfo> GameSystems);

public record GameSystemInfo(
    string Name,
    string Slug,
    IReadOnlyList<string> Factions);
