using System.Text.RegularExpressions;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>
/// Derives <see cref="Paint.Role"/> -- WHAT THE PRODUCT IS FOR -- from brand, range and name.
///
/// `category: paint` was redrawn on 2026-09-02 to mean anything a maker's paint chart lists: a
/// liquid, paste, powder or aerosol sold inside a painting range, colour or not. The finer grain
/// of a colour (wash, contrast, metallic, spray) stays in <see cref="Paint.Type"/> and
/// <see cref="Paint.Finish"/>; this facet never duplicates them. It answers the one question those
/// two cannot: is this pot a colour at all, or the varnish, thinner, primer, texture or pigment
/// sold on the same shelf.
///
/// THE ORDER OF THE RULES IS THE DESIGN. A range whose every member is one thing decides its
/// members (Vallejo's `Pigment FX`, AK's `Auxiliary (3rd Gen)`, Green Stuff World's `Varnish`),
/// then a small set of name patterns decides the utilities scattered through colour ranges
/// (Citadel's `Technical`, Tamiya's `Lacquer Paint`), and `colour` is the default -- because
/// 8,097 of the 8,521 archived records (measured 2026-09-02) are colours, and a default that
/// needs no evidence is the one that is right 95% of the time.
///
/// THE TRAPS, every one of them measured before the rule that avoids it was written:
/// <list type="bullet">
/// <item>MEDIUM is a colour word. `Medium Sea Grey`, `Medium Gunship Grey`, `Oxide Brown Medium`,
///   `Sea Grey Medium RAF WWII BS 637`, `Medium Earth`, `Medium Rust` -- 60+ records. So `Medium`
///   only counts after a closed list of QUALIFIERS (`Glaze Medium`, `Mixing Medium`, `Wash
///   Medium`...) or as the whole name; a bare `\bmedium\b` sweep was two-thirds colours.</item>
/// <item>PRIMER is a colour name. AK's AFV modulation sets carry `Red Primer Base`, `Red Primer
///   Shadow`, `Red Primer Shine`; AMMO's `Primers` range carries the same six colours beside its
///   six real `One Shot Primer`s; Vallejo's Panzer Aces has `Track Primer`, Scale75's Warfront
///   `Rotbraun Primer`, Mr Color `Chromate Yellow Primer Fs33481`. A primer is a NAME ENDING in
///   the noun with only finish/colour/application words before it, or a range that is primers.</item>
/// <item>RUST, DUST, SAND, EARTH, MUD are colour names (`Zandri Dust`, `Fairy Dust`, `Desert
///   Sand`, `Stirland Mud` is a TEXTURE but `Wet Mud` is a colour) -- no generic rule reads them;
///   only a range rule may (Vallejo `Pigment FX`, Scale75 `Soil Works`).</item>
/// <item>CLEAR is a tint. `Clear Smoke`, `Clear Red`, `Angron Red Clear` are colours; the Mr
///   Hobby / Tamiya varnish family is `Clear`, `Flat Clear`, `Semi-gloss Super Clear`, `Super
///   Smooth Clear`, `Pearl Clear` -- the WHOLE name, sheen words only.</item>
/// <item>PIGMENTS in a RANGE name is not a pigment: Army Painter's `D&amp;D Nolzur's Marvelous
///   Pigments`, Kimera's `Pure Pigments` and Mr Hobby's `Primary Color Pigments` are paints, and
///   Green Stuff World's `Liquid Pigments` are washes. Only Vallejo's `Pigment FX` is powder.</item>
/// </list>
///
/// The vocabulary is closed and shared with the product catalog (data/catalog/taxonomy). A role
/// that HAS no colour -- varnish, medium, cleaner -- must travel with `colourless: true`; that is
/// <see cref="RoleInvariant"/>'s job, and the tool refuses to write an archive that breaks it.
/// </summary>
public static partial class RoleClassifier
{
    public const string Colour = "colour";
    public const string Primer = "primer";
    public const string Varnish = "varnish";
    public const string Medium = "medium";
    public const string Cleaner = "cleaner";
    public const string Texture = "texture";
    public const string Pigment = "pigment";
    public const string Applicator = "applicator";
    public const string Tool = "tool";
    public const string Basing = "basing";
    public const string Build = "build";

    /// <summary>The closed vocabulary, in the order the taxonomy lists it.</summary>
    public static readonly IReadOnlyList<string> Roles =
        [Colour, Primer, Varnish, Medium, Cleaner, Texture, Pigment, Applicator, Tool, Basing, Build];

    public static readonly IReadOnlySet<string> Vocabulary = Roles.ToHashSet(StringComparer.Ordinal);

    /// <summary>
    /// The roles whose bearer deposits no colour. A record carrying one must also carry
    /// `colourless: true` -- the two are one fact stated twice, and <see cref="RoleInvariant"/>
    /// holds them together. `primer` is NOT here: a primer is usually a colour (Chaos Black) and
    /// only sometimes clear (Mission Models' `Clear Primer (Transparent)`, the one flagged one).
    /// </summary>
    public static readonly IReadOnlySet<string> ColourlessRoles =
        new HashSet<string>(StringComparer.Ordinal) { Varnish, Medium, Cleaner };

    /// <summary>Returns a new Paint with <see cref="Paint.Role"/> populated. Never null.</summary>
    public static Paint Enrich(Paint paint, string brandDisplayName) =>
        paint with { Role = Classify(brandDisplayName, paint.Set, paint.Name, paint.ProductCode) };

    /// <summary>
    /// Classifies by brand-and-range first, then by name, then `colour`. Always returns a value
    /// from <see cref="Roles"/>. Also used to backfill archived records a source no longer
    /// asserts, which is why it takes the bare strings rather than a <see cref="Paint"/>.
    ///
    /// The product code is read by exactly one rule (Vallejo's primer block) and is optional
    /// because most brands' codes say nothing about kind; see <see cref="ClassifyVallejo"/> for
    /// why a name cannot do that job there.
    /// </summary>
    public static string Classify(string brandDisplayName, string set, string name, string? productCode = null)
    {
        string cleanSet = Whitespace().Replace(StripDiscontinued(set), " ").Trim();
        string cleanName = name.Trim();
        return ClassifyByBrand(brandDisplayName, cleanSet, cleanName, productCode?.Trim() ?? "")
            ?? ClassifyByName(cleanName);
    }

    private static string? ClassifyByBrand(string brandDisplayName, string set, string name, string productCode) => brandDisplayName switch
    {
        "AK Interactive" => ClassifyAkInteractive(set, name),
        "AK Real Color" => ClassifyAkRealColor(name),
        "AMMO by Mig Jimenez" => ClassifyAmmo(set, name),
        "Army Painter" => ClassifyArmyPainter(set, name),
        "Citadel Colour" => ClassifyCitadel(set, name),
        "Coat D'Armes" => set == "Brushscape Range" ? Texture : null,
        "Green Stuff World" => ClassifyGreenStuffWorld(set),
        "Kimera Kolors" => Colour,
        "Mission Models" => set == "Mission Models Primer" ? Primer : null,
        "Monument (Pro Acryl)" => set == "Monument Pro Acrylic Primer" ? Primer : null,
        "Mr Hobby" => set == "Primary Color Pigments" ? Colour : null,
        "Reaper" => set == "Master Series Paints Core Colors Primer" ? Primer : null,
        "Scale75" => ClassifyScale75(set, name),
        "Vallejo" => ClassifyVallejo(set, name, productCode),
        "Warcolours" => set == "Paints for undercoating" ? Primer : Colour,
        _ => null,
    };

    // Auxiliary (3rd Gen) is six mediums and a retarder, all flagged colourless by hand. Primer
    // (3rd Gen) holds AK's three varnishes beside eleven primers -- the range name is right for
    // 11 of 14, so the varnish name wins inside it. The colour ranges are listed so that their
    // `Red Primer Base`, `Dust`, `Sand`, `Mud`, `Wood Base` stay colours whatever a name pattern
    // would say; only a medium name (Figures' `Glaze Medium -90-`) may leave one. Weathering
    // Effects (78 enamel washes, filters and streaking fluids) falls through to the name rules,
    // which catch exactly one: the `Oxidizing Agent`, a catalyst brushed over the Iron and Bronze
    // Effect paints, colourless and a medium.
    private static string? ClassifyAkInteractive(string set, string name) => set switch
    {
        "Auxiliary (3rd Gen)" => Medium,
        "Primer (3rd Gen)" => VarnishName().IsMatch(name) ? Varnish : Primer,
        "AFV" or "AFV (3rd Gen)" or "Figures" or "Figures (3rd Gen)" or "Air" or "Air (3rd Gen)" or "Naval" or "General"
            => MediumName().IsMatch(name) ? Medium : Colour,
        _ => null,
    };

    // Three varnishes (RC500-RC502, flagged) in Real Colors - Standard; everything else in the
    // three Real Colors ranges is a colour, including `Clear Smoke` and the five other tinted
    // clears, and `Medium Gunship Grey Fs 36118 10ml`.
    private static string ClassifyAkRealColor(string name) =>
        VarnishName().IsMatch(name) ? Varnish : MediumName().IsMatch(name) ? Medium : Colour;

    // AMMO's `Primers` range is six `One Shot Primer - <colour>` pots and the six colours of the
    // Red Primer modulation set (`Red Primer Base`, `Red Primer  High Lights`...). The
    // modulation words are the tell; the range name is right for the other half.
    private static string? ClassifyAmmo(string set, string name) => set switch
    {
        "Primers" => RedPrimerModulation().IsMatch(name) ? Colour : Primer,
        _ => null,
    };

    // Varnishes and mediums sit in almost every Army Painter range (`Warpaints`, `Fanatic`,
    // `Air`, `Wash`, `Primer`, the boxed sets), so the name decides first. `Warpaints Primer` is
    // the Colour Primer spray range -- 29 coloured undercoats -- and its two `Brush-On Primer`
    // twins live in `Warpaints Fanatic` and `Warpaints Fanatic Wash`. Everything else is a colour:
    // `Fairy Dust`, `Cosmic Dust`, `Howling Sand`, the three `Pigment Toner`s and the whole
    // `D&D Nolzur's Marvelous Pigments` range (41 paints, not one pigment).
    private static string ClassifyArmyPainter(string set, string name)
    {
        if (VarnishName().IsMatch(name)) return Varnish;
        if (MediumName().IsMatch(name)) return Medium;
        if (set is "Warpaints Primer" or "D&D Nolzur's Marvelous Pigments Primer") return Primer;
        return PrimerWord().IsMatch(name) ? Primer : Colour;
    }

    // Technical is the mixed shelf: 12 basing pastes (the Agrellan/Armageddon/Astrogranite/
    // Stirland/Martian/Mordant/Valhallan families), two mediums, two varnishes, and effect
    // paints (`Blood For The Blood God`, `Nihilakh Oxide`, `Typhus Corrosion`) that are colours.
    // Spray is GW's undercoat range -- every one is sold as "an undercoat", Chaos Black and Corax
    // White explicitly so -- plus `Munitorum Varnish`; Foundation Primer (discontinued) is the
    // old `Smelly Primer`.
    private static string? ClassifyCitadel(string set, string name) => set switch
    {
        "Technical" => CitadelTexture().IsMatch(name) ? Texture : null,
        "Spray" => VarnishName().IsMatch(name) ? Varnish : Primer,
        "Foundation Primer" => Primer,
        _ => null,
    };

    // Green Stuff World names its shelves: `Varnish` (9, all flagged), four primer shelves
    // (`Primer`, `Spray Primer`, `Matt Surface`, `Gloss Surface`; 26 records, including the two
    // foam-primer tubs sold by weight). `Liquid Pigments` are washes, `Dry Brush` holds
    // `Metallic Dry Brush - Cursed Gold 30 ml` (a paint, not a brush), `Effects` the blood and
    // bile gels, `Flexible` the 240 ml foam paints and `Chrome` a record named just `Airbrush`.
    private static string? ClassifyGreenStuffWorld(string set) => set switch
    {
        "Varnish" => Varnish,
        "Primer" or "Spray Primer" or "Matt Surface" or "Gloss Surface" => Primer,
        "Liquid Pigments" or "Dry Brush" or "Effects" or "Flexible" or "Chrome" => Colour,
        _ => null,
    };

    // `Primers` is three surface primers. `Warfront Range` holds `Rotbraun Primer` and
    // `Rotbraun Primer Red`, RAL 8012 as a colour. `Soil Works` carries no product codes in the
    // archive, so pigment against oil wash rests on the name: the dust/sand/mud/moss/earth names
    // Scale75 sells as 30 ml Soilworks pigment jars are pigments (7); `Light Rust`, `Dark Rust`,
    // `Grease`, `Fuel And Grease`, `Dark Stains` are the oil effects and stay colour; `Medium
    // Wet` and `Odorless Thinner` are the range's two flagged mediums.
    private static string? ClassifyScale75(string set, string name) => set switch
    {
        "Primers" => Primer,
        "Warfront Range" => Colour,
        "Soil Works" => MediumName().IsMatch(name) ? Medium : SoilWorksPigment().IsMatch(name) ? Pigment : Colour,
        _ => null,
    };

    // The largest brand and the most shelves. `Pigment FX` is 29 powders; `Surface Primer` is
    // 26 primers under colour names (`Black`, `German Dark Yellow`). `Diorama FX` is textures
    // (muds, waters, pumices, `Snow`) around one medium (`Terrain Fixer`) and 20 jars of loose
    // ballast sold by grain size (`Alkaline White 0.5-1 mm`) -- basing material the chart lists,
    // given the honest role. `Weathering FX` is muds of every consistency (six `Thick Mud`s, six
    // `Splash Mud`s, `Light Brown Mud`, `Mud and Grass`), `Crushed Grass`, `Moss and Lichen`,
    // `Rust Texture` and `Snow` -- 17 textures -- around ten effect liquids that are colours
    // (`Engine Grime`, `Oil Stains`, `Petrol Spills`, `Rain Marks`, the two `Slimy Grime`s,
    // `Streaking Grime`, `Brown Engine Soot`, `Diesel Stains`, `Fuel Stains`) and `Wet Effects`,
    // a transparent gloss medium. `Auxiliaries` (53) falls through to the name rules, which
    // place all of it. Panzer Aces keeps `Track Primer` a colour; Special FX and Wash FX are
    // colours (`Rust`, `Frost`, `Desert Dust`).
    //
    // THE CODE BLOCK COMES FIRST, because Vallejo files five primers where no name can find
    // them. Its numbering is systematic: 70.6xx is the primer block -- 70.600-70.632 are the
    // Surface Primers, 70.640-70.644 the five Mecha primers (white, grey, black, ivory, sand),
    // with 73.6xx and 74.6xx the same primers in 200 ml and 60 ml -- while 69.0xx is Mecha
    // Color and 71.xxx Model Air. The chart lists the Mecha primers under the Mecha Color range
    // as bare `White`, `Grey`, `Black`, `Ivory`, `Sand`, and the SAME name in the SAME range is
    // a colour one row over: `Grey|Mecha Color` is the primer at 70.641 and the colour at
    // 69.037. Measured 2026-09-03 over the archive: 30 records carry a 70.6xx code, 25 of them
    // already `primer` by the Surface Primer range and the other 5 exactly these; no record
    // carries a 73.6xx or 74.6xx code yet. Model Air 71.097 is NOT one of them: Vallejo's own
    // page and Rad Addel both call it `Medium Gunship Gray` (FS 36118), and only one retailer
    // lists it as a "Medium Grey Primer" -- a store's mislabel, which the code block correctly
    // leaves a colour.
    private static string? ClassifyVallejo(string set, string name, string productCode)
    {
        if (VallejoPrimerCode().IsMatch(productCode))
            return Primer;

        return set switch
        {
            "Pigment FX" => Pigment,
            "Surface Primer" => Primer,
            "Diorama FX" => Ballast().IsMatch(name) ? Basing : MediumName().IsMatch(name) ? Medium : Texture,
            "Weathering FX" => MediumName().IsMatch(name) ? Medium : WeatheringFxTexture().IsMatch(name) ? Texture : Colour,
            "Panzer Aces" or "Game Color Special FX" or "Wash FX" => Colour,
            _ => null,
        };
    }

    /// <summary>
    /// The name rules, in precedence order. Cleaner before varnish before medium because
    /// `Airbrush Cleaner` must not read as a thinner and `Gloss Varnish` must not read as a gloss
    /// medium; tool and build before primer and texture because they are whole-name nouns that
    /// nothing else claims; texture last of the specific ones because `paste`, `pumice`, `gel`
    /// and `texture` are safe words but `Gel Medium` is a medium.
    /// </summary>
    private static string ClassifyByName(string name)
    {
        if (CleanerName().IsMatch(name)) return Cleaner;
        if (VarnishName().IsMatch(name)) return Varnish;
        if (MediumName().IsMatch(name)) return Medium;
        if (ToolName().IsMatch(name)) return Tool;
        if (BuildName().IsMatch(name)) return Build;
        if (PrimerName().IsMatch(name)) return Primer;
        if (TextureName().IsMatch(name)) return Texture;
        return Colour;
    }

    private static string StripDiscontinued(string set)
    {
        int idx = set.IndexOf("(discontinued)", StringComparison.OrdinalIgnoreCase);
        return idx >= 0 ? set[..idx].Trim() : set;
    }

    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();

    /// <summary>
    /// A clear coat: the noun `varnish` at the END of the name (with an optional trailing size,
    /// `Anti-shine Varnish, 100 ml`), AK's inverted `Varnish Gloss`, sealers, `Clear Coat`, GW's
    /// three trade names, the Mr Hobby / Tamiya family (`Clear`, `Flat Clear`, `Semi-gloss Super
    /// Clear`, `Super Smooth Clear`, `Super Clear III`, `Pearl Clear`) as a WHOLE name with sheen
    /// words only, and top coats. `Varnished Wood` and every `Clear Red` fail on purpose.
    /// Measured 2026-09-02: 74 records, 68 of them already flagged colourless, the other 6 the
    /// invariant reported (three of which were rule gaps -- the `, 100 ml` suffix, `Semi-gloss
    /// Super Clear` -- fixed here).
    /// </summary>
    [GeneratedRegex(
        @"\bvarnish(,?\s*\d+\s*ml)?$|^varnish (gloss|matt|matte|satin)$|\bsealer\b|\bclear coat\b|^'?ardcoat$|^stormshield$" +
        @"|^((flat|matt|matte|gloss|semi[- ]?gloss|satin|pearl)\s+)?(super\s+(smooth\s+)?)?clear(\s+(iii|ii|gray tone|uv cut))?$" +
        @"|^(flat|gloss|satin|semi[- ]?gloss) (top ?coat|lacquer)$|^top ?coat\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex VarnishName();

    /// <summary>
    /// Something that goes INTO or UNDER the paint: `Medium` after a closed list of qualifiers
    /// (the list is the measured set of medium names across 21 brands; `Brown Medium`, `Grey
    /// Medium` are absent from it on purpose), thinners, reducers, retarders, flow improvers,
    /// stabilizers, additives, the flat/matt/clear `Base` flattening agents, binders, masking
    /// fluids, decal solutions, fixers, and two whole names: AK's `Oxidizing Agent` and
    /// Vallejo's `Wet Effects`. Measured 2026-09-02: 73 records, 70 flagged colourless.
    /// </summary>
    [GeneratedRegex(
        @"\b(mixing|glaze|gloss|matt|matte|satin|crackle|metal|metallic|wash|contrast|lahmian|speedpaint|transparent|textile|pearl|gel|cell|retarder|thinner|fluid|chipping|airbrush|acrylic|pouring|flow|blending|xpress|clear|pigment|drying|water|effects?|ink|oil|iridescent|glazing|shade|thinning|thickening|extender) medium\b" +
        @"|^medium (wet|xpress)$|^medium$" +
        @"|\bthinner\b|\breducer\b|\bretarder\b|\bflow (improver|aid)\b|\bstabili[sz]er\b|\badditive\b" +
        @"|^(flat|matt|matte|clear|gloss) base( rough| smooth)?$|\bbinder\b|\bliquid mask\b|\bmasking (fluid|sol|liquid)\b" +
        @"|\bdecal (fix|softener|setter|solution)\b|\bfixer\b|\bleveling\b|^oxidi[sz]ing agent$|^wet effects( fluid)?$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex MediumName();

    /// <summary>Does not go into the paint: 4 records, all Vallejo, all flagged.</summary>
    [GeneratedRegex(@"\bcleaner\b|\brestorer\b|\bstripper\b|\bremover\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex CleanerName();

    /// <summary>
    /// Pastes, gels and grounds with body: `paste`, `pumice`, `gel`, `texture`, thick muds, still
    /// water and water effects, `Snow` as a whole name (`Snow Blue` is a colour), Vallejo's
    /// `Black Lava`, `Crushed Grass`, `Mud and Grass`, `Moss and Lichen`. `Gel Medium` is caught
    /// by the medium rule first. No bare `sand`/`earth`/`mud` here -- those are colour names.
    /// </summary>
    [GeneratedRegex(
        @"\bpaste\b|\bpumice\b|\bgel\b|\btexture\b|\bthick mud\b|\bstill water\b|\bwater (texture|effects?|gel)\b|^snow$|\bcrushed grass\b|^black lava\b|\bmud and grass\b|\bmoss and lichen\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex TextureName();

    /// <summary>
    /// Hobby hardware a chart should never list but a harvest can: mixing balls, dropper and
    /// empty bottles, pipettes, palettes, stirrers. Zero records today (2026-09-02) -- the 15
    /// `tool` hits of the measurement lexicon were `Brush-On Primer`, `Metallic Dry Brush - ...`
    /// paints and `Khaki Drill`, every one a false positive of the words BRUSH and DRILL.
    /// </summary>
    [GeneratedRegex(@"\bmixing balls?\b|\bdropper bottles?\b|\bempty bottles?\b|\bpipettes?\b|\bpalettes?\b|\bstirrers?\b|\bagitators?\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex ToolName();

    /// <summary>Glue and putty: Vallejo's `Bookbinding Glue` and `Plastic Putty` (Auxiliaries).</summary>
    [GeneratedRegex(@"\bglue\b|\bputty\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex BuildName();

    /// <summary>
    /// A primer by NAME: the noun (`primer`, `gesso`, `undercoat`, `surfacer`, `microfiller`) at
    /// the end, preceded only by finish, colour and application words, optionally followed by a
    /// parenthetical or a size; or the noun leading (`Primer Black`, `One Shot Primer - Grey`,
    /// `Primer Surface White`). `Track Primer`, `Rotbraun Primer`, `Chromate Yellow Primer
    /// Fs33481`, `Red Primer Base` and `Wwi German Grey-green Primer` all fail: each is a colour
    /// named after what it depicts. Measured 2026-09-02: 146 primers in all, 117 of them by a
    /// range rule and the rest by this pattern.
    /// </summary>
    [GeneratedRegex(
        @"^((matt|matte|gloss|satin|brush-?on|spray|surface|clear|black|white|grey|gray|red|pink|tan|green|blue|brown|bone|beige|sand|desert|yellow|olive|rust|ivory|cream|colou?r|foam|filler|fine|smelly|metal|plastic|resin|acrylic|airbrush|polyurethane|one shot|universal|oxide|chaos|dark|light|flesh|silver|gold|army|magnesium|aluminium)\s+)*(primer|gesso|undercoat|surfacer|microfiller)(\s*\(.*\))?(,?\s*\d+\s*(ml|gr|g))?$" +
        @"|^(one shot |spray |brush-?on |surface |acrylic |polyurethane )?primer\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex PrimerName();

    /// <summary>Army Painter only, whose ranges are trusted not to name a colour `Primer`.</summary>
    [GeneratedRegex(@"\bprimer\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex PrimerWord();

    /// <summary>The six colours of AMMO's Red Primer modulation set, filed under `Primers`.</summary>
    [GeneratedRegex(@"^red primer\s+(base|dark base|light base|high\s*lights?|shadow|shine)\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex RedPrimerModulation();

    /// <summary>Citadel's basing pastes, by family name (12 records in `Technical`).</summary>
    [GeneratedRegex(@"^(agrellan|armageddon|astrogranite|stirland|mordant earth|valhallan blizzard|martian iron|lustrian undergrowth)", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex CitadelTexture();

    /// <summary>Scale75 Soilworks pigment names: `City Dust`, `Dust In Summertime`, `Dark Sand`, `Dark Mud`, `Green Moss`, `Mid Ground / Earth`, `Pale Dust`.</summary>
    [GeneratedRegex(@"(dust|sand|mud|moss|earth)$|^dust\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex SoilWorksPigment();

    /// <summary>Loose stones sold by grain size: `Alkaline White 0.5-1 mm`, `Vulcan Black 2-5 mm`.</summary>
    [GeneratedRegex(@"\d(\.\d+)?\s*-\s*\d(\.\d+)?\s*mm$", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex Ballast();

    /// <summary>
    /// Vallejo's primer block: 70.6xx (17 ml Surface Primers and the five Mecha primers), 73.6xx
    /// (200 ml) and 74.6xx (60 ml). See <see cref="ClassifyVallejo"/> for why a code, not a name.
    /// </summary>
    [GeneratedRegex(@"^7[034]\.6\d\d$", RegexOptions.Compiled)]
    private static partial Regex VallejoPrimerCode();

    /// <summary>
    /// What has body in Vallejo's Weathering FX: every mud (`Thick`, `Splash`, or plain `Light
    /// Brown Mud`), grass, moss, snow and `Rust Texture`. Scoped to that range on purpose --
    /// `Wet Mud` and `Desert Dust` are colours elsewhere -- and measured 2026-09-03: 17 of the
    /// range's 28 records, the other 11 being effect liquids and the `Wet Effects` medium.
    /// </summary>
    [GeneratedRegex(@"\bmud\b|\bsnow\b|\bgrass\b|\bmoss\b|\btexture\b", RegexOptions.IgnoreCase | RegexOptions.Compiled)]
    private static partial Regex WeatheringFxTexture();
}
