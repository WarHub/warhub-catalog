using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// Publishes a tiny hand-authored dataset once and exposes the resulting dist/ tree.
/// Fixtures mirror the exact YAML the two tools emit.
/// </summary>
public sealed class PublishFixture : IDisposable
{
    public string Root { get; }
    public string Dist { get; }
    internal PublishResult Result { get; }

    public PublishFixture()
    {
        Root = Path.Combine(Path.GetTempPath(), "warhub-catalog-tests", Guid.NewGuid().ToString("N"));
        Dist = Path.Combine(Root, "dist");
        string products = Path.Combine(Root, "data", "products");
        string paints = Path.Combine(Root, "data", "paints");

        WriteFile(Path.Combine(products, "manufacturers", "test-mfg", "test-system", "general.yaml"), """
            manufacturer: Test Manufacturer
            manufacturerSlug: test-mfg
            gameSystem: Test System
            gameSystemSlug: test-system
            faction: General
            factionSlug: general
            products:
            - name: Alpha Box
              category: miniatures
              packaging: single
              status: current
              availability: in_stock
              firstSeen: '2026-07-07'
              ean: '5011921142361'
              productCode: PRODA
            - name: Beta Box
              category: miniatures
              packaging: box
              status: discontinued
              availability: out_of_stock
              firstSeen: '2026-07-07'
              sku: SKUB
            """);

        WriteFile(Path.Combine(paints, "brands", "citadel.yaml"), """
            brand: Citadel
            brandSlug: citadel
            paintCount: 2
            paints:
            - name: Abaddon Black
              productCode: C1
              set: Base
              r: 35
              g: 31
              b: 32
              hex: '#231F20'
            - name: Mephiston Red
              productCode: C2
              set: Base
              r: 154
              g: 17
              b: 21
              hex: '#9A1115'
            """);

        WriteFile(Path.Combine(paints, "brands", "vallejo.yaml"), """
            brand: Vallejo
            brandSlug: vallejo
            paintCount: 1
            paints:
            - name: Black
              productCode: V1
              set: Model Color
              r: 35
              g: 35
              b: 35
              hex: '#232323'
            """);

        WriteFile(Path.Combine(paints, "equivalences.yaml"), """
            thresholds:
              close: 5
              substitute: 10
            totalEntries: 1
            equivalences:
            - source:
                brand: Citadel
                brandSlug: citadel
                name: Abaddon Black
                productCode: C1
                set: Base
                hex: '#231F20'
              matches:
              - paint:
                  brand: Vallejo
                  brandSlug: vallejo
                  name: Black
                  productCode: V1
                  set: Model Color
                  hex: '#232323'
                deltaE: 1.1
                tier: close
            """);

        var prov = new Provenance
        {
            Version = "2026.7.4",
            GeneratedAt = "2026-07-04T00:00:00Z",
            GitCommit = "deadbeef",
            Repo = "WarHub/warhub-catalog",
            Release = new ReleaseRef("v2026.7.4", "https://github.com/WarHub/warhub-catalog/releases/tag/v2026.7.4"),
            PageBaseUrl = "https://warhub.github.io/warhub-catalog",
        };

        string schemaDir = Path.Combine(AppContext.BaseDirectory, "schema");
        Result = Publisher.Run(new PublishOptions(products, paints, Dist, schemaDir, prov));
    }

    public string ReadDist(string relPath) => File.ReadAllText(Path.Combine(Dist, relPath.Replace('/', Path.DirectorySeparatorChar)));

    private static void WriteFile(string path, string content)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, content);
    }

    public void Dispose()
    {
        try { Directory.Delete(Root, recursive: true); } catch { /* best effort */ }
    }
}
