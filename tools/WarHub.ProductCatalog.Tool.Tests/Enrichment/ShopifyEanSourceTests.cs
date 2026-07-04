using WarHub.ProductCatalog.Tool.Enrichment;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class ShopifyEanSourceTests
{
    [Theory]
    [InlineData("99120113100", "99120113100")]         // GW numeric — pass through
    [InlineData("99120113100-restock", "99120113100")] // GW numeric with retailer suffix — strip
    [InlineData("99120113100-1", "99120113100")]       // GW numeric with index suffix — strip
    [InlineData("99070102001-2024", "99070102001")]    // GW numeric with year suffix — strip
    public void NormalizeSku_GwNumeric_StripsSuffixes(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("SFIK-CRG430", "SFIK-CRG430")]       // Steamforged — preserve as-is
    [InlineData("SFIK-MER477", "SFIK-MER477")]        // Steamforged — preserve as-is
    [InlineData("WYR24103", "WYR24103")]              // Wyrd — preserve as-is
    [InlineData("WYR23813", "WYR23813")]              // Wyrd — preserve as-is
    [InlineData("WGR-START-01", "WGR-START-01")]      // Warlord — preserve as-is
    [InlineData("303214071", "303214071")]            // Warlord numeric — preserve as-is
    [InlineData("HEL0850", "HEL0850")]               // Warlord Hail Caesar — preserve as-is
    [InlineData("A06015A", "A06015A")]                // Airfix (via Warlord) — preserve as-is
    [InlineData("CP217", "CP217")]                    // Atomic Mass Games — preserve as-is
    [InlineData("AMGSWQ90", "AMGSWQ90")]            // AMG via Asmodee UK — preserve as-is
    [InlineData("CMNDMDPR05", "DMDPR05")]            // CMON via Asmodee UK — CMN prefix stripped
    [InlineData("MGHAU102", "MGHAU102")]            // Mantic via Asmodee UK — preserve as-is
    [InlineData("MGKWNS107", "MGKWNS107")]          // Mantic Kings of War via Asmodee UK — preserve as-is
    [InlineData("PBW6573", "PBW6573")]              // Para Bellum via Elrik's — preserve as-is
    [InlineData("PBSK405", "PBSK405")]              // Para Bellum Sorcerer Kings via Elrik's — preserve as-is
    [InlineData("PBW1077", "PBW1077")]              // Para Bellum via Elrik's — preserve as-is
    [InlineData("PBYR309", "PBYR309")]              // Para Bellum Yoroni via Elrik's — preserve as-is
    public void NormalizeSku_Alphanumeric_PreservesAsIs(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("CP103EN", "CP103")]                // AMG MCP with EN suffix — strip
    [InlineData("CPE03EN", "CPE03")]                // AMG MCP event pack with EN suffix — strip
    [InlineData("CP56EN", "CP56")]                  // AMG MCP with EN suffix — strip
    [InlineData("CP139EN", "CP139")]                // AMG MCP with EN suffix — strip
    [InlineData("CP271EN", "CP271")]                // AMG MCP with EN suffix — strip
    [InlineData("FFGSWP48en", "FFGSWP48")]          // AMG Shatterpoint with lowercase en — strip
    public void NormalizeSku_AmgEnSuffix_StripsLanguageCode(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("SFIKEN", "SFIKEN")]                // Not an EN suffix (no digit before EN) — preserve
    [InlineData("MGDZM104-FR", "MGDZM104-FR")]     // Mantic FR locale SKU — preserve as-is (FR not EN)
    [InlineData("REN-PALISADE", "REN-PALISADE")]    // Not a language suffix — preserve
    public void NormalizeSku_NotLanguageSuffix_PreservesAsIs(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("COR281646-1212", "281646")]         // Tistaminis CB: strip COR prefix → numeric base
    [InlineData("COR281361-1203", "281361")]         // Tistaminis CB: strip COR prefix → numeric base
    [InlineData("COR280784-1216", "280784")]         // Tistaminis CB: strip COR prefix → numeric base
    public void NormalizeSku_TistaminisCbFormat_StripsCORPrefix(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("CMNSIF211", "SIF211")]               // CMON ASOIAF: strip CMN prefix
    [InlineData("CMNSIF611", "SIF611")]               // CMON ASOIAF: strip CMN prefix
    [InlineData("CMNSIFFP5", "SIFFP5")]               // CMON ASOIAF faction pack: strip CMN prefix
    [InlineData("CMNSIF301", "SIF301")]               // CMON Night's Watch: strip CMN prefix
    [InlineData("CMN001", "CMN001")]                   // CMN followed by digit — keep as-is (not a prefix)
    public void NormalizeSku_CmnPrefix_StripsCMNPrefix(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("COR-INF PAN 281 236 1028", "281236")]  // Bellford CB: extract 6-digit ref
    [InlineData("COR-INF ALE 280 876 1027", "280876")]  // Bellford CB: extract 6-digit ref
    [InlineData("COR-INF ARI 281 137 1087", "281137")]  // Bellford CB: extract 6-digit ref
    [InlineData("COR-INF JSA 281 7021099", "281702")]   // Bellford CB: extract 6-digit ref
    [InlineData("COR-DIR 280 050 1030", "280050")]      // Bellford CB Dire Foes: extract ref
    public void NormalizeSku_BellfordCbFormat_ExtractsReference(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("281134-1072", "281134")]               // CB catalog SKU — strip suffix (numeric base)
    [InlineData("280888-1149", "280888")]               // CB catalog SKU — strip suffix (numeric base)
    [InlineData("280050-1030", "280050")]               // CB catalog SKU — strip suffix (numeric base)
    public void NormalizeSku_CbCatalogFormat_StripsToNumericBase(string input, string expected)
    {
        string? result = ShopifyEanSource.NormalizeSku(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("  ")]
    public void NormalizeSku_ReturnsNull_ForEmptyValues(string? input)
    {
        Assert.Null(ShopifyEanSource.NormalizeSku(input));
    }

    [Theory]
    [InlineData(" 99120113100 ", "99120113100")]       // Trims whitespace (numeric)
    [InlineData(" SFIK-CRG430 ", "SFIK-CRG430")]      // Trims whitespace (alphanumeric)
    [InlineData("99120113100", "99120113100")]          // Already clean
    public void NormalizeSku_Trims_Whitespace(string input, string expected)
    {
        Assert.Equal(expected, ShopifyEanSource.NormalizeSku(input));
    }

    [Theory]
    [InlineData("5011921226115", true)]    // GW EAN-13
    [InlineData("5061060705866", true)]    // Steamforged EAN-13
    [InlineData("812152035065", true)]     // Wyrd UPC-A (12 digits)
    [InlineData("8429551771672", true)]    // Vallejo EAN-13
    [InlineData("5060572502376", true)]    // Warlord EAN-13
    [InlineData("841333135287", true)]     // AMG UPC-A via Asmodee UK
    [InlineData("889696018762", true)]     // CMON UPC-A via Asmodee UK
    [InlineData("5060924985994", true)]    // Mantic EAN-13 via Asmodee UK
    [InlineData("8436607711100", true)]    // Corvus Belli EAN-13 via Bellford/Tistaminis
    [InlineData("8436607712299", true)]    // Corvus Belli EAN-13 via Bellford
    [InlineData("5213009016407", true)]    // Para Bellum EAN-13 via Bellford/Elrik's
    [InlineData("5213009019187", true)]    // Para Bellum EAN-13 via Elrik's
    [InlineData(null, false)]
    [InlineData("", false)]
    [InlineData("  ", false)]
    [InlineData("12345", false)]           // Too short
    [InlineData("12345678901234", false)]  // Too long (14 digits)
    [InlineData("e3ad9cfe-738a", false)]   // UUID fragment
    [InlineData("abc1234567890", false)]   // Contains letters
    public void IsValidBarcode_ValidatesCorrectly(string? input, bool expected)
    {
        Assert.Equal(expected, ShopifyEanSource.IsValidBarcode(input));
    }

    [Theory]
    [InlineData("Stark Sworn Swords", "stark sworn swords")]
    [InlineData("A Song of Ice and Fire: Stark Sworn Swords", "stark sworn swords")]
    [InlineData("A Song of Ice & Fire: Night's Watch Heroes Box 1", "night s watch heroes box 1")]
    [InlineData("ASOIAF: Targaryen Starter Set", "targaryen starter set")]
    [InlineData("ASOIAF - Bolton Cutthroats", "bolton cutthroats")]
    [InlineData("Brotherhood Without Banners: Starter Set", "brotherhood without banners starter set")]
    // "House" prefix stripping — retailer uses "House X:" but manufacturer uses "X:"
    [InlineData("House Baratheon: Starter Set", "baratheon starter set")]
    [InlineData("House Greyjoy: Ironmakers", "greyjoy ironmakers")]
    [InlineData("House Bolton: Bolton Cutthroats", "bolton bolton cutthroats")]
    [InlineData("House Stark: Starter Set", "stark starter set")]
    // Without "House" prefix — should match manufacturer names directly
    [InlineData("Baratheon: Starter Set", "baratheon starter set")]
    [InlineData("Greyjoy: Ironmakers", "greyjoy ironmakers")]
    [InlineData("Free Folk: Starter Set", "free folk starter set")]
    [InlineData("Night's Watch: Starter Set", "night s watch starter set")]
    public void NormalizeTitle_NormalizesGamePrefixes(string input, string expected)
    {
        Assert.Equal(expected, ShopifyEanSource.NormalizeTitle(input));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("  ")]
    [InlineData("AB")]  // Too short after normalization
    public void NormalizeTitle_ReturnsNull_ForEmptyValues(string? input)
    {
        Assert.Null(ShopifyEanSource.NormalizeTitle(input));
    }

    [Theory]
    [InlineData("Conquest: Two Player Starter Set", "conquest two player starter set")]
    [InlineData("Marvel Crisis Protocol: Core Set", "marvel crisis protocol core set")]
    [InlineData("Bolt Action (3rd Edition) - US Army", "bolt action 3rd edition us army")]
    public void NormalizeTitle_PreservesNonAsoiafTitles(string input, string expected)
    {
        Assert.Equal(expected, ShopifyEanSource.NormalizeTitle(input));
    }
}
