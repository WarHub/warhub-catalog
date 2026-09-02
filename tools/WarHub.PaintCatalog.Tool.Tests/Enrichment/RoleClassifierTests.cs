using WarHub.PaintCatalog.Tool.Enrichment;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class RoleClassifierTests
{
    private static Paint MakePaint(string set, string name) => new()
    {
        Name = name,
        Set = set,
        R = 100,
        G = 100,
        B = 100,
        Hex = "#646464",
    };

    /// <summary>A whole range that is one thing decides its members, whatever the name says.</summary>
    [Theory]
    [InlineData("Vallejo", "Pigment FX", "Rust", "pigment")]
    [InlineData("Vallejo", "Pigment FX", "Titanium White", "pigment")]
    [InlineData("Vallejo", "Surface Primer", "Black", "primer")]
    [InlineData("Vallejo", "Surface Primer", "German Dark Yellow", "primer")]
    [InlineData("AK Interactive", "Auxiliary (3rd Gen)", "Retarder", "medium")]
    [InlineData("AK Interactive", "Auxiliary (3rd Gen)", "Crackle Medium", "medium")]
    [InlineData("AK Interactive", "Primer (3rd Gen)", "Rust Surface Primer", "primer")]
    [InlineData("AK Interactive", "Primer (3rd Gen)", "Dunkelgelb Ral 7028 Dark Yellow", "primer")]
    [InlineData("AK Interactive", "Primer (3rd Gen)", "Varnish Gloss", "varnish")]
    [InlineData("Green Stuff World", "Varnish", "Chrome Clear Coat 17 ml", "varnish")]
    [InlineData("Green Stuff World", "Matt Surface", "Primer Black", "primer")]
    [InlineData("Green Stuff World", "Spray Primer", "Black Gloss Spray Paint 400ml", "primer")]
    [InlineData("Green Stuff World", "Primer", "Foam Primer and Coat - Black 250gr", "primer")]
    [InlineData("Citadel Colour", "Spray", "Chaos Black", "primer")]
    [InlineData("Citadel Colour", "Spray", "Mephiston Red", "primer")]
    [InlineData("Citadel Colour", "Spray", "Munitorum Varnish", "varnish")]
    [InlineData("Citadel Colour", "Foundation Primer (discontinued)", "Smelly Primer", "primer")]
    [InlineData("Coat D'Armes", "Brushscape Range", "Dark Earth", "texture")]
    [InlineData("Warcolours", "Paints for undercoating", "Black", "primer")]
    [InlineData("Monument (Pro Acryl)", "Monument Pro Acrylic Primer", "PRIME Black", "primer")]
    [InlineData("Monument (Pro Acryl)", "Monument Pro Acrylic Primer", "AdeptiCon Spray-Team Red Oxide", "primer")]
    [InlineData("Reaper", "Master Series Paints Core Colors Primer", "Brush-On Black Primer", "primer")]
    [InlineData("Scale75", "Primers", "Primer Surface Black", "primer")]
    [InlineData("Mission Models", "Mission Models Primer", "Red Oxide Primer", "primer")]
    [InlineData("Army Painter", "Warpaints Primer", "Alien Purple", "primer")]
    [InlineData("Army Painter", "Warpaints Primer", "Matt Black", "primer")]
    [InlineData("Army Painter", "D&D Nolzur's Marvelous Pigments Primer", "Grey Primer", "primer")]
    [InlineData("AMMO by Mig Jimenez", "Primers", "One Shot Primer - Grey", "primer")]
    [InlineData("Vallejo", "Diorama FX", "Still Water", "texture")]
    [InlineData("Vallejo", "Diorama FX", "Atlantic Blue", "texture")]
    [InlineData("Vallejo", "Diorama FX", "Terrain Fixer", "medium")]
    [InlineData("Vallejo", "Diorama FX", "Alkaline White 0.5-1 mm", "basing")]
    [InlineData("Vallejo", "Diorama FX", "Vulcan Black 2-5 mm", "basing")]
    [InlineData("Vallejo", "Weathering FX", "Brown Thick Mud", "texture")]
    [InlineData("Vallejo", "Weathering FX", "Crushed Grass", "texture")]
    [InlineData("Vallejo", "Weathering FX", "Rust Texture", "texture")]
    [InlineData("Vallejo", "Weathering FX", "Snow", "texture")]
    [InlineData("Vallejo", "Weathering FX", "Wet Effects", "medium")]
    [InlineData("Vallejo", "Weathering FX", "Brown Splash Mud", "colour")]
    [InlineData("Vallejo", "Weathering FX", "Engine Grime", "colour")]
    [InlineData("Scale75", "Soil Works", "City Dust", "pigment")]
    [InlineData("Scale75", "Soil Works", "Dust In Summertime", "pigment")]
    [InlineData("Scale75", "Soil Works", "Mid Ground / Earth", "pigment")]
    [InlineData("Scale75", "Soil Works", "Light Rust", "colour")]
    [InlineData("Scale75", "Soil Works", "Fuel And Grease", "colour")]
    [InlineData("Scale75", "Soil Works", "Medium Wet", "medium")]
    [InlineData("Scale75", "Soil Works", "Odorless Thinner", "medium")]
    public void Classify_RangeDecidesItsMembers(string brand, string set, string name, string expected)
    {
        Assert.Equal(expected, RoleClassifier.Classify(brand, set, name));
    }

    /// <summary>The utilities scattered through colour ranges are found by name.</summary>
    [Theory]
    [InlineData("Citadel Colour", "Technical", "'Ardcoat", "varnish")]
    [InlineData("Citadel Colour", "Technical", "Stormshield", "varnish")]
    [InlineData("Citadel Colour", "Technical", "Lahmian Medium", "medium")]
    [InlineData("Citadel Colour", "Technical", "Contrast Medium", "medium")]
    [InlineData("Citadel Colour", "Technical", "Stirland Mud", "texture")]
    [InlineData("Citadel Colour", "Technical", "Astrogranite Debris", "texture")]
    [InlineData("Citadel Colour", "Technical", "Valhallan Blizzard", "texture")]
    [InlineData("Citadel Colour", "Technical", "Blood For The Blood God", "colour")]
    [InlineData("Citadel Colour", "Technical", "Nihilakh Oxide", "colour")]
    [InlineData("Citadel Colour", "Air", "Air Caste Thinner", "medium")]
    [InlineData("Vallejo", "Auxiliaries", "Airbrush Cleaner", "cleaner")]
    [InlineData("Vallejo", "Auxiliaries", "Brush Restorer", "cleaner")]
    [InlineData("Vallejo", "Auxiliaries", "Black Gesso", "primer")]
    [InlineData("Vallejo", "Auxiliaries", "Plastic Putty", "build")]
    [InlineData("Vallejo", "Auxiliaries", "Bookbinding Glue", "build")]
    [InlineData("Vallejo", "Auxiliaries", "Sandy Paste", "texture")]
    [InlineData("Vallejo", "Auxiliaries", "Extra Heavy Coarse Pumice", "texture")]
    [InlineData("Vallejo", "Auxiliaries", "Heavy Gel Gloss", "texture")]
    [InlineData("Vallejo", "Auxiliaries", "Black Lava", "texture")]
    [InlineData("Vallejo", "Auxiliaries", "Gel Medium", "medium")]
    [InlineData("Vallejo", "Auxiliaries", "Liquid Mask", "medium")]
    [InlineData("Vallejo", "Auxiliaries", "Decal Fix", "medium")]
    [InlineData("Vallejo", "Auxiliaries", "Pigment Binder", "medium")]
    [InlineData("Vallejo", "Auxiliaries", "Acrylic Matt Spray Varnish", "varnish")]
    [InlineData("Vallejo", "Auxiliaries", "Gloss Removable Acrylic Varnish", "varnish")]
    [InlineData("Vallejo", "Premium Airbrush Color", "Clear Base", "medium")]
    [InlineData("Vallejo", "Premium Airbrush Color", "Reducer", "medium")]
    [InlineData("Vallejo", "Premium Airbrush Color", "Cleaner", "cleaner")]
    [InlineData("Vallejo", "Premium Airbrush Color", "White Primer", "primer")]
    [InlineData("Vallejo", "Xpress Color", "Medium Xpress", "medium")]
    [InlineData("Vallejo", "Metal Color", "Gloss Metal Varnish", "varnish")]
    [InlineData("Mr Hobby", "Mr Color", "Clear", "varnish")]
    [InlineData("Mr Hobby", "Mr Color", "Flat Clear", "varnish")]
    [InlineData("Mr Hobby", "Mr Color", "Semi-gloss Super Clear", "varnish")]
    [InlineData("Mr Hobby", "Mr Color GX", "Super Smooth Clear", "varnish")]
    [InlineData("Mr Hobby", "Mr Color GX", "Super Clear III", "varnish")]
    [InlineData("Mr Hobby", "Mr Color", "Flat Base Rough", "medium")]
    [InlineData("Tamiya", "Lacquer Paint", "Pearl clear", "varnish")]
    [InlineData("Tamiya", "Lacquer Paint", "Semi gloss clear", "varnish")]
    [InlineData("Tamiya", "Lacquer Paint", "Lacquer thinner", "medium")]
    [InlineData("Tamiya", "Acrylics Mini Gloss", "Flat base", "medium")]
    [InlineData("Reaper", "Master Series Paints Core Colors", "Brush-on Sealer", "varnish")]
    [InlineData("Reaper", "Master Series Paints Core Colors", "Anti-Shine Additive", "medium")]
    [InlineData("Reaper", "Master Series Paints Core Colors", "Flow Improver", "medium")]
    [InlineData("Army Painter", "Warpaints Air", "Anti-shine Varnish, 100 ml", "varnish")]
    [InlineData("Army Painter", "Warpaints Air", "Matt Black Primer, 100 ml", "primer")]
    [InlineData("Army Painter", "Warpaints Fanatic Wash", "Brush-On Primer", "primer")]
    [InlineData("Army Painter", "Warpaints Fanatic", "Warpaints Stabilizer", "medium")]
    [InlineData("Army Painter", "Warpaints Wash", "Quickshade Wash Mixing Medium", "medium")]
    [InlineData("AK Interactive", "Weathering Effects", "Oxidizing Agent", "medium")]
    [InlineData("AK Interactive", "Figures", "Glaze Medium -90-", "medium")]
    [InlineData("AK Real Color", "Real Colors - Standard", "Flat Varnish", "varnish")]
    [InlineData("AMMO by Mig Jimenez", "Acrylics", "Matt Varnish", "varnish")]
    [InlineData("Humbrol", "Humbrol Aerosol Sprays", "Primer", "primer")]
    [InlineData("Humbrol", "Humbrol Acrylics - Gloss", "Satin Varnish", "varnish")]
    [InlineData("P3 (Privateer Press)", "P3 Paints", "Mixing Medium", "medium")]
    [InlineData("Monument (Pro Acryl)", "Monument Pro Acrylic Paints", "Metallic Medium", "medium")]
    [InlineData("Mission Models", "Mission Models", "Transparent Medium", "medium")]
    [InlineData("Coat D'Armes", "Fantasy Range", "Grey Primer", "primer")]
    public void Classify_NameDecidesTheUtilitiesInsideColourRanges(string brand, string set, string name, string expected)
    {
        Assert.Equal(expected, RoleClassifier.Classify(brand, set, name));
    }

    /// <summary>
    /// The traps, each one measured before its rule was written: MEDIUM, PRIMER, DUST, SAND, MUD,
    /// RUST, CLEAR and PIGMENT(S) as colour words or range words. Every one is a colour.
    /// </summary>
    [Theory]
    [InlineData("AK Interactive", "AFV", "Red Primer Base")]
    [InlineData("AK Interactive", "AFV", "Red Primer Shine")]
    [InlineData("AMMO by Mig Jimenez", "Primers", "Red Primer  High Lights")]
    [InlineData("AMMO by Mig Jimenez", "Primers", "Red Primer Base")]
    [InlineData("Vallejo", "Panzer Aces", "Track Primer")]
    [InlineData("Scale75", "Warfront  Range", "Rotbraun Primer")]
    [InlineData("Mr Hobby", "Mr Color", "Chromate Yellow Primer Fs33481")]
    [InlineData("AK Interactive", "Air (3rd Gen)", "Wwi German Grey-green Primer")]
    [InlineData("AK Interactive", "Air", "FS 36118 Medium Gunship Grey")]
    [InlineData("Humbrol", "Humbrol Aerosol Sprays - Satin", "Medium Sea Grey")]
    [InlineData("Kimera Kolors", "Kimera Kolors Expansion Set 1", "Oxide Brown Medium")]
    [InlineData("Mission Models", "Mission Models", "Sea Grey Medium RAF WWII BS 637")]
    [InlineData("Green Stuff World", "Liquid Pigments", "Medium Earth")]
    [InlineData("AMMO by Mig Jimenez", "Acrylics", "Medium Rust")]
    [InlineData("AK Real Color", "Real Colors - Standard", "Clear Smoke")]
    [InlineData("AK Real Color", "Real Colors - Standard", "Clear Red")]
    [InlineData("Mr Hobby", "Mr Clear Color GX", "Clear Black")]
    [InlineData("Citadel Colour", "Air", "Angron Red Clear")]
    [InlineData("Citadel Colour", "Base", "Zandri Dust")]
    [InlineData("Citadel Colour", "Dry", "Ryza Rust")]
    [InlineData("Army Painter", "Warpaints Air", "Fairy Dust")]
    [InlineData("Army Painter", "Skin Tones Paint Set", "Pearl Pigment Toner")]
    [InlineData("Army Painter", "D&D Nolzur's Marvelous Pigments", "Abyssal Black")]
    [InlineData("Army Painter", "Warpaints", "Wet Mud")]
    [InlineData("Army Painter", "Warpaints Fanatic", "Lava Orange")]
    [InlineData("Kimera Kolors", "Kimera Kolors Pure Pigments", "Carbon Black")]
    [InlineData("Mr Hobby", "Primary Color Pigments", "Cyan")]
    [InlineData("Mr Hobby", "Aqueous Hobby Color", "Cement Gray")]
    [InlineData("Vallejo", "Game Color Special FX", "Rust")]
    [InlineData("Vallejo", "Wash FX", "Desert Dust")]
    [InlineData("Vallejo", "Model Color", "Black Glaze")]
    [InlineData("AK Interactive", "General", "Varnished Wood")]
    [InlineData("AK Interactive", "General", "Dust")]
    [InlineData("AK Interactive", "General", "Wood Base")]
    [InlineData("AK Interactive", "Standard (3rd Gen)", "Snow Blue")]
    [InlineData("AK Interactive", "Weathering Effects", "Streaking Grime")]
    [InlineData("AK Interactive", "Weathering Effects", "Dust Effects")]
    [InlineData("AK Interactive", "Xtreme Metal", "Xtreme Metal Black Base 30ml")]
    [InlineData("Green Stuff World", "Dry Brush", "Metallic Dry Brush - Cursed Gold 30 ml")]
    [InlineData("Green Stuff World", "Effects", "Blood effect - True Blood")]
    [InlineData("Green Stuff World", "Chrome", "Airbrush")]
    [InlineData("Mission Models", "Mission Models", "Gloss Black Base for Chrome")]
    [InlineData("Two Thin Coats", "Acrylic", "Bone Wash")]
    [InlineData("Foundry", "Foundry Paint System", "Base Sand")]
    [InlineData("Turbo Dork", "Turbo Dork", "Ground Is Lava")]
    [InlineData("Scale75", "Inktensity Range", "Inktense Black")]
    public void Classify_TheTrapsStayColour(string brand, string set, string name)
    {
        Assert.Equal("colour", RoleClassifier.Classify(brand, set, name));
    }

    /// <summary>
    /// Hobby hardware a chart should never list but a harvest can. No archived record matches
    /// today; the rule exists so the first dropper bottle a harvest brings gets the honest role
    /// rather than `colour`.
    /// </summary>
    [Theory]
    [InlineData("Vallejo", "Auxiliaries", "Mixing Balls", "tool")]
    [InlineData("AK Interactive", "Weathering Effects", "Empty Dropper Bottle 17ml", "tool")]
    [InlineData("Vallejo", "Auxiliaries", "Plastic Palette", "tool")]
    public void Classify_HardwareGetsTheHonestRole(string brand, string set, string name, string expected)
    {
        Assert.Equal(expected, RoleClassifier.Classify(brand, set, name));
    }

    [Fact]
    public void Enrich_AlwaysWritesARole_AndColourIsTheDefault()
    {
        Paint enriched = RoleClassifier.Enrich(MakePaint("Some Set", "Some Paint"), "Unknown Brand");
        Assert.Equal("colour", enriched.Role);

        // And it preserves everything else.
        Paint paint = MakePaint("Model Color", "Black") with { ProductCode = "70.950", VolumeMl = 18, Type = "Standard" };
        Paint result = RoleClassifier.Enrich(paint, "Vallejo");
        Assert.Equal("70.950", result.ProductCode);
        Assert.Equal(18, result.VolumeMl);
        Assert.Equal("Standard", result.Type);
        Assert.Equal("colour", result.Role);
    }

    [Fact]
    public void Vocabulary_IsClosed_AndTheColourlessRolesAreInsideIt()
    {
        Assert.Equal(
            ["colour", "primer", "varnish", "medium", "cleaner", "texture", "pigment", "applicator", "tool", "basing", "build"],
            RoleClassifier.Roles);
        Assert.All(RoleClassifier.ColourlessRoles, r => Assert.Contains(r, RoleClassifier.Vocabulary));
        Assert.Equal(new HashSet<string> { "varnish", "medium", "cleaner" }, RoleClassifier.ColourlessRoles);
    }
}
