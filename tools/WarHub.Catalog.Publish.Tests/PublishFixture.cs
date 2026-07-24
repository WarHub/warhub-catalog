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
        string catalog = Path.Combine(Root, "data", "catalog");
        string paints = Path.Combine(Root, "data", "paints");

        WriteFile(Path.Combine(catalog, "products", "test-mfg.yaml"), """
            manufacturer: test-mfg
            products:
              - id: test-mfg/alpha
                name: Alpha Box
                manufacturer: test-mfg
                productCode: PRODA
                ean: '5011921142361'
                eanConfidence: provisional
                gameSystem: test-system
                faction: general
                category: miniatures
                quantity: 2
                status: current
                availability: in_stock
                firstSeen: '2026-07-07'
              - id: test-mfg/beta
                name: Beta Box
                manufacturer: test-mfg
                sku: SKUB
                gameSystem: test-system
                faction: general
                category: miniatures
                status: discontinued
                availability: out_of_stock
                firstSeen: '2026-07-07'
            """);

        WriteFile(Path.Combine(catalog, "taxonomy", "game-systems.yaml"), """
            gameSystems:
              - slug: test-system
                label: Test System
            """);

        WriteFile(Path.Combine(catalog, "taxonomy", "factions.yaml"), """
            factions:
              - slug: general
                label: General
            """);

        WriteFile(Path.Combine(paints, "brands", "citadel.yaml"), """
            brand: Citadel
            brandSlug: citadel
            source: Arcturus5404/miniature-paints
            license: MIT
            paints:
            - name: Abaddon Black
              category: paint
              status: current
              availability: unknown
              firstSeen: '2026-07-07'
              productCode: C1
              details:
                set: Base
                r: 35
                g: 31
                b: 32
                hex: '#231F20'
                volumeMl: 12
                container: pot
                type: Base
                finish: Matte
            - name: Mephiston Red
              category: paint
              status: discontinued
              availability: out_of_stock
              firstSeen: '2026-07-07'
              productCode: C2
              details:
                set: Base
                r: 154
                g: 17
                b: 21
                hex: '#9A1115'
                volumeMl: 12
                container: pot
            """);

        WriteFile(Path.Combine(paints, "brands", "vallejo.yaml"), """
            brand: Vallejo
            brandSlug: vallejo
            source: Arcturus5404/miniature-paints
            license: MIT
            paints:
            - name: Black
              category: paint
              status: current
              availability: unknown
              firstSeen: '2026-07-07'
              productCode: V1
              details:
                set: Model Color
                r: 35
                g: 35
                b: 35
                hex: '#232323'
                volumeMl: 17
                container: dropper
            - name: Old Copper
              category: paint
              status: current
              availability: unknown
              firstSeen: '2026-07-24'
              productCode: '77.703'
              details:
                set: True Metallic Metal
                r: 0
                g: 0
                b: 0
                hex: ''
                volumeMl: 18
                container: dropper
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
        Result = Publisher.Run(new PublishOptions(catalog, paints, Dist, schemaDir, prov));
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
