using WarHub.ProductCatalog.Tool.Scraping;

namespace WarHub.ProductCatalog.Tool.Tests.Scraping;

public class GamesWorkshopScraperTests
{
    [Fact]
    public void ParseProductListing_JsonLdProduct_ExtractsData()
    {
        string html = """
            <html>
            <head>
            <script type="application/ld+json">
            {
                "@type": "Product",
                "name": "Intercessors",
                "sku": "99120101283",
                "url": "https://www.games-workshop.com/en-GB/intercessors",
                "image": "https://www.games-workshop.com/img/intercessors.jpg",
                "gtin13": "5011921142439",
                "description": "10 Primaris Intercessors",
                "offers": {
                    "price": "35.00",
                    "priceCurrency": "GBP"
                }
            }
            </script>
            </head>
            <body></body>
            </html>
            """;

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", "Space Marines");

        Assert.Single(products);
        Assert.Equal("Intercessors", products[0].Name);
        Assert.Equal("99120101283", products[0].Sku);
        Assert.Equal("5011921142439", products[0].Ean);
        Assert.Equal(35.00m, products[0].PriceGbp);
        Assert.Equal("https://www.games-workshop.com/en-GB/intercessors", products[0].Url);
        Assert.Equal("https://www.games-workshop.com/img/intercessors.jpg", products[0].ImageUrl);
        Assert.Equal("Games Workshop", products[0].Manufacturer);
        Assert.Equal("Warhammer 40,000", products[0].GameSystem);
        Assert.Equal("Space Marines", products[0].Faction);
    }

    [Fact]
    public void ParseProductListing_JsonLdArray_ExtractsMultiple()
    {
        string html = """
            <html>
            <head>
            <script type="application/ld+json">
            [
                {
                    "@type": "Product",
                    "name": "Product A",
                    "sku": "SKU-A",
                    "offers": { "price": 25.00 }
                },
                {
                    "@type": "Product",
                    "name": "Product B",
                    "sku": "SKU-B",
                    "offers": { "price": 30.00 }
                }
            ]
            </script>
            </head>
            <body></body>
            </html>
            """;

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", null);

        Assert.Equal(2, products.Count);
        Assert.Equal("Product A", products[0].Name);
        Assert.Equal("Product B", products[1].Name);
    }

    [Fact]
    public void ParseProductListing_InvalidJsonLd_DoesNotThrow()
    {
        string html = """
            <html>
            <head>
            <script type="application/ld+json">
            { invalid json here }
            </script>
            </head>
            <body></body>
            </html>
            """;

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", null);

        Assert.Empty(products);
    }

    [Fact]
    public void ParseProductListing_NoJsonLd_ReturnsEmpty()
    {
        string html = "<html><head></head><body><p>No products</p></body></html>";

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", null);

        Assert.Empty(products);
    }

    [Fact]
    public void ParseProductListing_NonProductJsonLd_Ignored()
    {
        string html = """
            <html>
            <head>
            <script type="application/ld+json">
            {
                "@type": "WebPage",
                "name": "Not a product"
            }
            </script>
            </head>
            <body></body>
            </html>
            """;

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", null);

        Assert.Empty(products);
    }

    [Fact]
    public void ParseProductListing_ImageArray_TakesFirst()
    {
        string html = """
            <html>
            <head>
            <script type="application/ld+json">
            {
                "@type": "Product",
                "name": "Test Product",
                "image": ["https://img1.jpg", "https://img2.jpg"]
            }
            </script>
            </head>
            <body></body>
            </html>
            """;

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", null);

        Assert.Single(products);
        Assert.Equal("https://img1.jpg", products[0].ImageUrl);
    }

    [Fact]
    public void ParseProductListing_GtinField_UsedAsEan()
    {
        string html = """
            <html>
            <head>
            <script type="application/ld+json">
            {
                "@type": "Product",
                "name": "Product with GTIN",
                "gtin": "5011921142439"
            }
            </script>
            </head>
            <body></body>
            </html>
            """;

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", null);

        Assert.Single(products);
        Assert.Equal("5011921142439", products[0].Ean);
    }

    [Fact]
    public void ParseProductListing_OffersArray_ParsesFirstPrice()
    {
        string html = """
            <html>
            <head>
            <script type="application/ld+json">
            {
                "@type": "Product",
                "name": "Multi-offer Product",
                "offers": [
                    { "price": "42.50", "priceCurrency": "GBP" },
                    { "price": "55.00", "priceCurrency": "USD" }
                ]
            }
            </script>
            </head>
            <body></body>
            </html>
            """;

        var products = GamesWorkshopScraper.ParseProductListing(html, "Warhammer 40,000", null);

        Assert.Single(products);
        Assert.Equal(42.50m, products[0].PriceGbp);
    }
}
