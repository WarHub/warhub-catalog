using WarHub.Catalog.Publish;

namespace WarHub.Catalog.Publish.Tests;

/// <summary>
/// Publishes a tiny hand-authored dataset once and exposes the resulting dist/ tree.
/// Fixtures mirror the exact YAML the two tools emit.
///
/// The barcodes are deliberately arranged to exercise the cross-catalog seam:
///   5011921142361 -- product test-mfg/alpha (primary) AND paint citadel/abaddon-black
///   8429551724838 -- product test-mfg/alpha (additionalEans) AND paint vallejo/black
///   5011921142378 -- paint citadel/mephiston-red only, no product side
/// so alpha links to TWO paints (plural on both sides), mephiston-red links to nothing, and
/// test-mfg/beta carries no barcode at all.
///
/// The boxed-set relation is arranged to exercise all three contents claims and both refusal
/// paths: alpha is `stated` with a quantity, a statedName resolution and one upstream refusal,
/// beta is `description` with a refusal, gamma is `sku` with the single member that shape has.
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
                additionalEans: ['8429551724838']
                eanConfidence: provisional
                gameSystems:
                  - test-system
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
                gameSystems:
                  - test-system
                faction: general
                category: miniatures
                status: discontinued
                availability: out_of_stock
                firstSeen: '2026-07-07'
              - id: test-mfg/gamma
                name: Gamma Powder (Pack of 6)
                manufacturer: test-mfg
                productCode: GAMMA
                gameSystems:
                  - test-system
                faction: general
                category: paint
                role: pigment
                roleBasis: lexicon
                status: current
                availability: in_stock
                firstSeen: '2026-07-07'
            """);

        // The boxed-set relation, in the shape gen_set_contents.py emits: one file per
        // manufacturer, one top-level key, a counts block the publisher re-derives and checks.
        // All three `from` values appear, because they are three different claims and the
        // document keeps them apart. `ref` is deliberately unlike the resolved productCode on the
        // first member ('0C1' -> 'C1') to prove the source's own string survives publication.
        WriteFile(Path.Combine(catalog, "set-contents", "test-mfg.yaml"), """
            test-mfg:
              counts:
                sets: 3
                refs: 7
                members: 5
                unresolved: 2
                quantified: 1
              sets:
                test-mfg/alpha:
                  name: Alpha Box
                  brand: citadel, vallejo
                  from: stated
                  members:
                    - ref: '0C1'
                      brand: citadel
                      paint: Abaddon Black|Base
                      productCode: C1
                      quantity: 2
                    - ref: V1
                      brand: vallejo
                      paint: Black|Model Color
                      productCode: V1
                    - ref: C2
                      brand: citadel
                      paint: Mephiston Red|Base
                      productCode: C2
                      resolvedBy: statedName
                      statedName: MEPHISTON RED
                  unresolved:
                    - ref: NOSUCH
                      reason: no paint in brand(s) 'citadel' carries this product code
                test-mfg/beta:
                  name: Beta Box
                  brand: citadel
                  from: description
                  members:
                    - ref: C3
                      brand: citadel
                      paint: Ghost Ash|Technical
                      productCode: C3
                  unresolved:
                    - ref: AMBIG
                      reason: 2 paints in brand(s) 'citadel' carry this product code
                test-mfg/gamma:
                  name: Gamma Powder (Pack of 6)
                  brand: citadel
                  from: sku
                  members:
                    - ref: GAMMA-S
                      brand: citadel
                      paint: Weathering Powder Rust|Weathering
                      productCode: WP1
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
              role: colour
              firstSeen: '2026-07-07'
              productCode: C1
              ean: '5011921142361'
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
            - name: Weathering Powder Rust
              category: paint
              status: current
              availability: unknown
              role: pigment
              firstSeen: '2026-07-07'
              productCode: WP1
              details:
                set: Weathering
                r: 140
                g: 70
                b: 20
                hex: '#8C4614'
                weightG: 35
                container: jar
            - name: Mephiston Red
              category: paint
              status: discontinued
              availability: out_of_stock
              role: colour
              firstSeen: '2026-07-07'
              productCode: C2
              ean: '5011921142378'
              details:
                set: Base
                r: 154
                g: 17
                b: 21
                hex: '#9A1115'
                volumeMl: 12
                container: pot
            - name: Hexwraith Flame
              category: paint
              status: discontinued
              availability: out_of_stock
              role: colour
              firstSeen: '2026-07-07'
              supersededBy: Hexwraith Flame|Contrast
              details:
                set: Technical
                r: 41
                g: 162
                b: 54
                hex: '#29A236'
                volumeMl: 24
                container: pot
            - name: Hexwraith Flame
              category: paint
              status: current
              availability: unknown
              role: colour
              firstSeen: '2026-07-07'
              productCode: '99189960060'
              supersedes:
                - Hexwraith Flame|Technical
              details:
                set: Contrast
                r: 0
                g: 0
                b: 0
                hex: ''
                volumeMl: 18
                container: pot
            - name: Ghost Ash
              category: paint
              status: discontinued
              availability: out_of_stock
              role: texture
              firstSeen: '2026-07-07'
              productCode: C3
              supersededBy: Nothing At All|Contrast
              details:
                set: Technical
                r: 1
                g: 2
                b: 3
                hex: '#010203'
                volumeMl: 24
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
              role: colour
              firstSeen: '2026-07-07'
              productCode: V1
              ean: '8429551724838'
              imageUrl: https://img.example/vallejo-black.jpg
              priceGbp: 2.75
              priceUsd: 3.99
              priceEur: 3.20
              priceCad: 4.50
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
              role: colour
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
