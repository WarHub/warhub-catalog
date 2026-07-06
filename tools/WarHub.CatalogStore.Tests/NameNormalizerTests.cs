namespace WarHub.CatalogStore.Tests;

public class NameNormalizerTests
{
    [Theory]
    [InlineData("Baratheon: Wardens", "baratheon: wardens")]
    [InlineData("  Space   Marines  ", "space marines")]
    [InlineData("'Quoted Name'", "quoted name")]
    [InlineData("\"Double Quoted\"", "double quoted")]
    [InlineData("Tabs\tand\nnewlines", "tabs and newlines")]
    public void Normalize_ProducesStableLowercaseKey(string input, string expected)
    {
        Assert.Equal(expected, NameNormalizer.Normalize(input));
    }

    [Fact]
    public void Normalize_IsIdempotent()
    {
        string once = NameNormalizer.Normalize("  The  Old  World  ");
        string twice = NameNormalizer.Normalize(once);
        Assert.Equal(once, twice);
    }

    [Fact]
    public void Normalize_AppliesNfkcSoCompatibilityFormsCollapse()
    {
        // Fullwidth 'A' (U+FF21) normalizes to ASCII 'a' under NFKC.
        Assert.Equal("a", NameNormalizer.Normalize("Ａ"));
    }
}
