using WarHub.ProductCatalog.Tool.Enrichment;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class EanEnricherTests
{
    [Theory]
    [InlineData("Combat Patrol: Kroot", "Games Workshop Combat Patrol Kroot", 1.0)]
    [InlineData("Intercessors", "Games Workshop Warhammer 40K Intercessors (B08ZJSRZ47)", 1.0)]
    [InlineData("Combat Patrol: Drukhari", "Games Workshop Warhammer 40K Combat Patrol Drukhari (B08ZJSRZ47)", 1.0)]
    public void CalculateMatchScore_WithMatchingNames_ReturnsHighScore(
        string productName, string candidateTitle, double minExpectedScore)
    {
        string normalized = EanEnricher.NormalizeName(productName);
        string[] tokens = normalized.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        string normalizedCandidate = EanEnricher.NormalizeName(candidateTitle);

        double score = EanEnricher.CalculateMatchScore(tokens, normalizedCandidate);

        Assert.True(score >= minExpectedScore,
            $"Score {score} is below minimum {minExpectedScore} for '{productName}' vs '{candidateTitle}'");
    }

    [Theory]
    [InlineData("Combat Patrol: Kroot", "Space Marines Tactical Squad")]
    [InlineData("Intercessors", "Necron Warriors")]
    public void CalculateMatchScore_WithUnrelatedNames_ReturnsLowScore(
        string productName, string candidateTitle)
    {
        string normalized = EanEnricher.NormalizeName(productName);
        string[] tokens = normalized.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        string normalizedCandidate = EanEnricher.NormalizeName(candidateTitle);

        double score = EanEnricher.CalculateMatchScore(tokens, normalizedCandidate);

        Assert.True(score < 0.5, $"Score {score} unexpectedly high for unrelated names");
    }

    [Fact]
    public void NormalizeName_RemovesAmazonAsin()
    {
        string result = EanEnricher.NormalizeName("Combat Patrol Drukhari (B08ZJSRZ47)");
        Assert.DoesNotContain("B08ZJSRZ47", result);
        Assert.Contains("combat", result);
        Assert.Contains("patrol", result);
        Assert.Contains("drukhari", result);
    }

    [Fact]
    public void NormalizeName_RemovesGwBranding()
    {
        string result = EanEnricher.NormalizeName("Games Workshop Warhammer 40,000 Combat Patrol");
        Assert.DoesNotContain("games workshop", result);
        Assert.DoesNotContain("warhammer 40,000", result);
        Assert.Contains("combat", result);
        Assert.Contains("patrol", result);
    }

    [Fact]
    public void FindBestNameMatch_WithSingleCandidate_ReturnsIt()
    {
        var candidates = new List<UpcItem>
        {
            new() { Ean = "5011921139217", Title = "Combat Patrol: Drukhari" }
        };

        UpcItem? result = EanEnricher.FindBestNameMatch("Combat Patrol: Drukhari", candidates);

        Assert.NotNull(result);
        Assert.Equal("5011921139217", result.Ean);
    }

    [Fact]
    public void FindBestNameMatch_WithMultipleCandidates_ReturnsBestMatch()
    {
        var candidates = new List<UpcItem>
        {
            new() { Ean = "5011921111111", Title = "Games Workshop Combat Patrol Space Marines" },
            new() { Ean = "5011921222222", Title = "Games Workshop Combat Patrol Drukhari (B08ZJSRZ47)" },
            new() { Ean = "5011921333333", Title = "Games Workshop Warhammer Age of Sigmar Starter Set" },
        };

        UpcItem? result = EanEnricher.FindBestNameMatch("Combat Patrol: Drukhari", candidates);

        Assert.NotNull(result);
        Assert.Equal("5011921222222", result.Ean);
    }

    [Fact]
    public void FindBestNameMatch_WithNoGoodMatch_ReturnsNull()
    {
        var candidates = new List<UpcItem>
        {
            new() { Ean = "5011921111111", Title = "Completely Unrelated Product About Bicycles" },
        };

        UpcItem? result = EanEnricher.FindBestNameMatch("Combat Patrol: Kroot", candidates);

        Assert.Null(result);
    }

    [Fact]
    public void FindBestNameMatch_WithEmptyCandidates_ReturnsNull()
    {
        UpcItem? result = EanEnricher.FindBestNameMatch("Anything", []);
        Assert.Null(result);
    }
}
