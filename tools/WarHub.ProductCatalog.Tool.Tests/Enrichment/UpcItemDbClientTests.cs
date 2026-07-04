using WarHub.ProductCatalog.Tool.Enrichment;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class UpcItemDbClientTests
{
    [Fact]
    public void IsRateLimited_IsFalse_Initially()
    {
        using var client = new UpcItemDbClient(apiKey: null, verbose: false);

        Assert.False(client.IsRateLimited);
    }
}
