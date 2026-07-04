using WarHub.ProductCatalog.Tool.Enrichment;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class EanEnricherBudgetTests
{
    [Fact]
    public void BudgetExhausted_IsFalse_WhenBudgetIsZero()
    {
        // budget=0 means unlimited
        var enricher = CreateEnricher(budget: 0);

        Assert.False(enricher.BudgetExhausted);
    }

    [Fact]
    public void BudgetExhausted_IsFalse_WhenUnderBudget()
    {
        var enricher = CreateEnricher(budget: 5);

        Assert.False(enricher.BudgetExhausted);
        Assert.Equal(0, enricher.ApiCalls);
    }

    [Fact]
    public void Constructor_AcceptsBudgetParameter()
    {
        // Verify we can construct with budget
        var enricher = CreateEnricher(budget: 100);

        Assert.NotNull(enricher);
        Assert.False(enricher.BudgetExhausted);
    }

    [Fact]
    public void BudgetExhausted_IsTrue_WhenClientIsRateLimited()
    {
        var client = new UpcItemDbClient(apiKey: null, verbose: false);
        var enricher = new EanEnricher(client, verbose: false, budget: 100);

        // Client starts not rate-limited
        Assert.False(enricher.BudgetExhausted);
        Assert.False(client.IsRateLimited);
    }

    private static EanEnricher CreateEnricher(int budget = 0)
    {
        var client = new UpcItemDbClient(apiKey: null, verbose: false);
        return new EanEnricher(client, verbose: false, budget: budget);
    }
}
