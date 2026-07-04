using WarHub.PaintCatalog.Tool.Equivalence;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Tests.Equivalence;

public class EquivalenceFinderTests
{
    private static BrandCatalog MakeCatalog(string brand, string slug, params (string Name, int R, int G, int B)[] paints)
    {
        var paintList = paints.Select(p => new Paint
        {
            Name = p.Name,
            Set = "Base",
            R = p.R,
            G = p.G,
            B = p.B,
            Hex = $"#{p.R:X2}{p.G:X2}{p.B:X2}"
        }).ToList();

        return new BrandCatalog
        {
            Brand = brand,
            BrandSlug = slug,
            PaintCount = paintList.Count,
            Paints = paintList
        };
    }

    [Fact]
    public void FindEquivalences_IdenticalColors_ZeroDeltaE()
    {
        var catalogs = new List<BrandCatalog>
        {
            MakeCatalog("Brand A", "brand-a", ("White", 255, 255, 255)),
            MakeCatalog("Brand B", "brand-b", ("White Too", 255, 255, 255))
        };

        var finder = new EquivalenceFinder();
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        Assert.Equal(2, result.TotalEntries); // One from each direction
        PaintEquivalenceEntry entry = result.Equivalences.First(e => e.Source.Name == "White");
        Assert.Single(entry.Matches);
        Assert.Equal(0, entry.Matches[0].DeltaE);
        Assert.Equal("close", entry.Matches[0].Tier);
    }

    [Fact]
    public void FindEquivalences_OnlyCrossBrand()
    {
        var catalogs = new List<BrandCatalog>
        {
            MakeCatalog("Brand A", "brand-a",
                ("Red", 255, 0, 0),
                ("Also Red", 250, 5, 5)),
            MakeCatalog("Brand B", "brand-b", ("Blue", 0, 0, 255))
        };

        var finder = new EquivalenceFinder(closeThreshold: 5, substituteThreshold: 10);
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        // Red and Also Red are same brand — should NOT match each other
        foreach (PaintEquivalenceEntry entry in result.Equivalences)
        {
            foreach (PaintMatch match in entry.Matches)
            {
                Assert.NotEqual(entry.Source.BrandSlug, match.Paint.BrandSlug);
            }
        }
    }

    [Fact]
    public void FindEquivalences_ExcludesDiscontinued()
    {
        var catalogs = new List<BrandCatalog>
        {
            new BrandCatalog
            {
                Brand = "Brand A",
                BrandSlug = "brand-a",
                PaintCount = 1,
                Paints = [new Paint
                {
                    Name = "Old Red",
                    Set = "Base (discontinued)",
                    R = 255, G = 0, B = 0,
                    Hex = "#FF0000",
                    IsDiscontinued = true
                }]
            },
            MakeCatalog("Brand B", "brand-b", ("New Red", 255, 0, 0))
        };

        var finder = new EquivalenceFinder();
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        // Old Red is discontinued — should not appear as source
        Assert.DoesNotContain(result.Equivalences, e => e.Source.Name == "Old Red");
        // New Red has no matches because Old Red is excluded
        Assert.DoesNotContain(result.Equivalences, e => e.Source.Name == "New Red");
    }

    [Fact]
    public void FindEquivalences_TierClassification()
    {
        var catalogs = new List<BrandCatalog>
        {
            MakeCatalog("Brand A", "brand-a", ("Red", 200, 50, 50)),
            MakeCatalog("Brand B", "brand-b",
                ("Close Red", 205, 48, 53),   // Very close
                ("Far Red", 180, 80, 30))      // Noticeable difference
        };

        var finder = new EquivalenceFinder(closeThreshold: 5, substituteThreshold: 15);
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        PaintEquivalenceEntry? entry = result.Equivalences.FirstOrDefault(e => e.Source.Name == "Red");
        Assert.NotNull(entry);

        PaintMatch? closeMatch = entry.Matches.FirstOrDefault(m => m.Paint.Name == "Close Red");
        Assert.NotNull(closeMatch);
        Assert.Equal("close", closeMatch.Tier);
    }

    [Fact]
    public void FindEquivalences_BestPerBrand()
    {
        // Brand B has two reds — should only pick the closest one per brand
        var catalogs = new List<BrandCatalog>
        {
            MakeCatalog("Brand A", "brand-a", ("Target Red", 200, 50, 50)),
            MakeCatalog("Brand B", "brand-b",
                ("Exact Red", 200, 50, 50),
                ("Near Red", 210, 45, 55))
        };

        var finder = new EquivalenceFinder();
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        PaintEquivalenceEntry? entry = result.Equivalences.FirstOrDefault(e => e.Source.Name == "Target Red");
        Assert.NotNull(entry);

        // Should only have 1 match from Brand B (the best one)
        Assert.Single(entry.Matches);
        Assert.Equal("Exact Red", entry.Matches[0].Paint.Name);
    }

    [Fact]
    public void FindEquivalences_MaxMatchesRespected()
    {
        // Create 10 brands with white paints, but limit to 5 matches
        var catalogs = Enumerable.Range(0, 10)
            .Select(i => MakeCatalog($"Brand {i}", $"brand-{i}", ($"White {i}", 255, 255, 255)))
            .ToList();

        var finder = new EquivalenceFinder(maxMatchesPerPaint: 3);
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        foreach (PaintEquivalenceEntry entry in result.Equivalences)
        {
            Assert.True(entry.Matches.Count <= 3, $"Expected max 3 matches, got {entry.Matches.Count}");
        }
    }

    [Fact]
    public void FindEquivalences_ThresholdsInOutput()
    {
        var catalogs = new List<BrandCatalog>
        {
            MakeCatalog("Brand A", "brand-a", ("Red", 200, 50, 50)),
            MakeCatalog("Brand B", "brand-b", ("Red Too", 200, 50, 50))
        };

        var finder = new EquivalenceFinder(closeThreshold: 3.0, substituteThreshold: 7.0);
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        Assert.Equal(3.0, result.Thresholds.Close);
        Assert.Equal(7.0, result.Thresholds.Substitute);
    }

    [Fact]
    public void FindEquivalences_EmptyCatalogs_ReturnsEmpty()
    {
        var finder = new EquivalenceFinder();
        EquivalencesFile result = finder.FindEquivalences([]);

        Assert.Equal(0, result.TotalEntries);
        Assert.Empty(result.Equivalences);
    }

    [Fact]
    public void FindEquivalences_SingleBrand_NoMatches()
    {
        var catalogs = new List<BrandCatalog>
        {
            MakeCatalog("Brand A", "brand-a", ("Red", 255, 0, 0), ("Blue", 0, 0, 255))
        };

        var finder = new EquivalenceFinder();
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        Assert.Equal(0, result.TotalEntries);
    }

    [Fact]
    public void FindEquivalences_PreservesSourceFields()
    {
        var catalogs = new List<BrandCatalog>
        {
            new BrandCatalog
            {
                Brand = "Vallejo",
                BrandSlug = "vallejo",
                PaintCount = 1,
                Paints = [new Paint
                {
                    Name = "Black",
                    ProductCode = "70.950",
                    Set = "Model Color",
                    R = 0, G = 0, B = 0,
                    Hex = "#000000"
                }]
            },
            MakeCatalog("Citadel", "citadel", ("Abaddon Black", 0, 0, 0))
        };

        var finder = new EquivalenceFinder();
        EquivalencesFile result = finder.FindEquivalences(catalogs);

        PaintEquivalenceEntry? vallejoEntry = result.Equivalences.FirstOrDefault(e => e.Source.Name == "Black");
        Assert.NotNull(vallejoEntry);
        Assert.Equal("Vallejo", vallejoEntry.Source.Brand);
        Assert.Equal("vallejo", vallejoEntry.Source.BrandSlug);
        Assert.Equal("70.950", vallejoEntry.Source.ProductCode);
        Assert.Equal("Model Color", vallejoEntry.Source.Set);
        Assert.Equal("#000000", vallejoEntry.Source.Hex);
    }
}
