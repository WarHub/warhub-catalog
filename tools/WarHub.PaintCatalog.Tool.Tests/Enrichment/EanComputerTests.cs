using WarHub.PaintCatalog.Tool.Enrichment;

namespace WarHub.PaintCatalog.Tool.Tests.Enrichment;

public class EanComputerTests
{
    [Theory]
    [InlineData("70.950", "8429551709507")]  // Black
    [InlineData("70.916", "8429551709163")]  // Sand Yellow (verified via UPCitemdb)
    [InlineData("72.001", "8429551720014")]  // Dead White
    public void ComputeVallejoEan_KnownCodes_ReturnsCorrectEan(string code, string expectedEan)
    {
        string? ean = EanComputer.ComputeVallejoEan(code);

        Assert.NotNull(ean);
        Assert.Equal(expectedEan, ean);
        Assert.Equal(13, ean.Length);
    }

    [Fact]
    public void ComputeVallejoEan_NullCode_ReturnsNull()
    {
        string? ean = EanComputer.ComputeVallejoEan(null);

        Assert.Null(ean);
    }

    [Theory]
    [InlineData("")]
    [InlineData("ABC")]
    [InlineData("12345")]
    [InlineData("70.95")]      // Too short
    [InlineData("70.9500")]    // Too long
    [InlineData("70-950")]     // Wrong separator
    public void ComputeVallejoEan_InvalidCodes_ReturnsNull(string code)
    {
        string? ean = EanComputer.ComputeVallejoEan(code);

        Assert.Null(ean);
    }

    [Theory]
    [InlineData("842955170950", 7)]  // 70.950 → check digit 7
    [InlineData("842955170916", 3)]  // 70.916 → check digit 3
    public void ComputeCheckDigit_KnownValues_ReturnsCorrectDigit(string first12, int expectedCheckDigit)
    {
        int checkDigit = EanComputer.ComputeCheckDigit(first12);

        Assert.Equal(expectedCheckDigit, checkDigit);
    }

    [Fact]
    public void ComputeVallejoEan_AllEansAre13Digits()
    {
        string[] validCodes = ["70.950", "72.001", "70.916", "71.281", "69.001"];

        foreach (string code in validCodes)
        {
            string? ean = EanComputer.ComputeVallejoEan(code);
            Assert.NotNull(ean);
            Assert.Equal(13, ean.Length);
            Assert.True(ean.All(char.IsDigit), $"EAN for {code} contains non-digit characters: {ean}");
        }
    }

    [Fact]
    public void ComputeVallejoEan_AllEansStartWith8429551()
    {
        string? ean = EanComputer.ComputeVallejoEan("70.950");

        Assert.NotNull(ean);
        Assert.StartsWith("8429551", ean);
    }
}
