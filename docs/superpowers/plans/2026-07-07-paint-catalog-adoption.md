# Paint Catalog Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the shared `WarHub.CatalogStore` library (built in Plan 1) in `WarHub.PaintCatalog.Tool`, giving paints append-only reconciliation, a liveness ledger, forced quoting, deterministic order, and a one-time idempotent migration — with a paint-specific payload.

**Architecture:** The existing flat `Paint` record stays the **working model** (parser, enrichers, scrapers, equivalence — all untouched). A new archival **`PaintRecord`** (shared core + nested `details`) is built from the enriched working `Paint` right before reconciliation, and is the only shape written to disk / reconciled / ledgered. Reconciliation happens per **brand file** (the reconciled set). This is a direct paint-side mirror of Plan 1's product adoption; the shared library already exists and is fully tested.

**Tech Stack:** C# / .NET 10, records, YamlDotNet 18.1.0, xUnit 2.9.3, central package management, `.slnx` solution.

## Global Constraints

- Build clean under `dotnet build WarHub.Catalog.slnx -warnaserror` — 0 warnings, 0 errors.
- All **existing** paint tests stay green; add new tests TDD-first. Do not touch the product tool or `WarHub.CatalogStore` library sources (they are frozen by Plan 1); this plan only adds to `WarHub.PaintCatalog.Tool` (+ its test project) and `data/paints/`.
- **Never drop archival data.** Reconciliation is append-only/backfill-only; removal only via explicit `retract:`.
- **Headline guarantee:** identical input → byte-identical output; re-running the migration twice yields zero diff.
- Paint **identity key** = `NameNormalizer.Normalize(set) | Normalize(name) | Normalize(productCode) | Normalize(hex)` (`|`-joined; empty segment where a value is absent). Ledger key = `{brandSlug}/{identityKey}`.
- **Field order (top-level):** `name, category, status, availability, firstSeen, productCode, ean, imageUrl, details`. **`details` order:** `set, r, g, b, hex, volumeMl, container, type, finish`.
- `category` is the constant `"paint"`. Lifecycle map: `isDiscontinued=true → status "discontinued", availability "out_of_stock"`; `false → status "current", availability "unknown"`.
- Design of record: `docs/superpowers/specs/2026-07-07-paint-adoption-addendum.md` (authoritative for all values above).
- Reuse the shared library exactly as the product tool does: `CatalogSerializer`, `NameNormalizer`, `CatalogReconciler<T>`, `ICatalogRecordAdapter<T>`, `LivenessLedger`/`LedgerStore`/`LivenessUpdater`.

---

## File Structure

- `tools/WarHub.PaintCatalog.Tool/WarHub.PaintCatalog.Tool.csproj` — add `ProjectReference` to `WarHub.CatalogStore`.
- `tools/WarHub.PaintCatalog.Tool/Models/PaintRecord.cs` — **new** archival record + `PaintDetails` + `BrandArchive`.
- `tools/WarHub.PaintCatalog.Tool/Reconcile/PaintRecordMapper.cs` — **new** flat `Paint` → `PaintRecord`.
- `tools/WarHub.PaintCatalog.Tool/Reconcile/PaintRecordAdapter.cs` — **new** `ICatalogRecordAdapter<PaintRecord>`.
- `tools/WarHub.PaintCatalog.Tool/Output/BrandArchiveWriter.cs` — **new** write/load brand archive files via `CatalogSerializer`.
- `tools/WarHub.PaintCatalog.Tool/Enrichment/PaintOverrideAliases.cs` — **new** aliases/retract loader scoped by brand.
- `tools/WarHub.PaintCatalog.Tool/Migration/PaintMigrator.cs` — **new** idempotent legacy→new migration.
- `tools/WarHub.PaintCatalog.Tool/Program.cs` — **modify**: add `migrate` subcommand; restructure the write path to enrich→map→reconcile→ledger→write per brand; drop derived counts from manifest.
- Test files under `tools/WarHub.PaintCatalog.Tool.Tests/{Models,Reconcile,Output,Enrichment,Migration}/`.
- `data/paints/brands/*.yaml`, `data/paints/manifest.yaml`, `data/paints/_liveness.yaml` — migrated (Task 8).

The **flat `Paint`, `BrandCatalog`, `Manifest` models, `MarkdownPaintParser`, all `Enrichment/*` classes, all `Scraping/*` sources, `EquivalenceFinder`, and `YamlCatalogWriter.WriteEquivalencesAsync`** are the working/equivalence path and stay **unchanged**.

---

### Task 1: CatalogStore reference + archival `PaintRecord` model

**Files:**
- Modify: `tools/WarHub.PaintCatalog.Tool/WarHub.PaintCatalog.Tool.csproj`
- Create: `tools/WarHub.PaintCatalog.Tool/Models/PaintRecord.cs`
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Models/PaintRecordSchemaTests.cs`

**Interfaces:**
- Produces: `PaintRecord`, `PaintDetails`, `BrandArchive` records (consumed by every later task).

- [ ] **Step 1: Add the project reference.** In the `.csproj`, inside the existing `<ItemGroup>` that holds `ProjectReference`s (or add one), add:

```xml
    <ProjectReference Include="..\WarHub.CatalogStore\WarHub.CatalogStore.csproj" />
```

- [ ] **Step 2: Write the failing schema test** (`PaintRecordSchemaTests.cs`):

```csharp
using System.Linq;
using WarHub.PaintCatalog.Tool.Models;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Models;

public class PaintRecordSchemaTests
{
    [Fact]
    public void PaintRecord_TopLevel_FieldOrder()
    {
        string[] expected =
            ["Name", "Category", "Status", "Availability", "FirstSeen", "ProductCode", "Ean", "ImageUrl", "Details"];
        string[] actual = typeof(PaintRecord).GetProperties().Select(p => p.Name).ToArray();
        Assert.Equal(expected, actual);
    }

    [Fact]
    public void PaintDetails_FieldOrder()
    {
        string[] expected =
            ["Set", "R", "G", "B", "Hex", "VolumeMl", "Container", "Type", "Finish"];
        string[] actual = typeof(PaintDetails).GetProperties().Select(p => p.Name).ToArray();
        Assert.Equal(expected, actual);
    }
}
```

- [ ] **Step 3: Run test to verify it fails** — `dotnet test tools/WarHub.PaintCatalog.Tool.Tests --filter PaintRecordSchemaTests` → FAIL (type not found).

- [ ] **Step 4: Create `PaintRecord.cs`:**

```csharp
namespace WarHub.PaintCatalog.Tool.Models;

/// <summary>
/// Archival paint record: shared storage core at top level, paint-specific
/// color/physical fields nested under <see cref="Details"/>. This is the only
/// shape written to disk / reconciled / ledgered. Built from the flat working
/// <see cref="Paint"/> by PaintRecordMapper. Property order drives YAML order.
/// </summary>
public record PaintRecord
{
    public required string Name { get; init; }
    /// <summary>Constant "paint" for this catalog.</summary>
    public required string Category { get; init; }
    /// <summary>Archival lifecycle: current | suspected-discontinued | discontinued | delisted.</summary>
    public required string Status { get; init; }
    /// <summary>Volatile purchasability: in_stock | out_of_stock | pre_order | limited | unknown.</summary>
    public required string Availability { get; init; }
    /// <summary>Write-once, immutable.</summary>
    public string? FirstSeen { get; init; }
    public string? ProductCode { get; init; }
    public string? Ean { get; init; }
    public string? ImageUrl { get; init; }
    public required PaintDetails Details { get; init; }
}

/// <summary>Paint-specific color/physical fields (the category extension block).</summary>
public record PaintDetails
{
    public required string Set { get; init; }
    public required int R { get; init; }
    public required int G { get; init; }
    public required int B { get; init; }
    public required string Hex { get; init; }
    public int? VolumeMl { get; init; }
    /// <summary>Bottle type (dropper | pot | spray | ...). Was the legacy `packaging` field.</summary>
    public string? Container { get; init; }
    public string? Type { get; init; }
    public string? Finish { get; init; }
}

/// <summary>Per-brand archival file envelope. No derived counts (recomputed at publish).</summary>
public record BrandArchive
{
    public required string Brand { get; init; }
    public required string BrandSlug { get; init; }
    public string Source { get; init; } = "Arcturus5404/miniature-paints";
    public string License { get; init; } = "MIT";
    public required List<PaintRecord> Paints { get; init; }
}
```

- [ ] **Step 5: Run tests to verify pass** — `dotnet test tools/WarHub.PaintCatalog.Tool.Tests --filter PaintRecordSchemaTests` → PASS. Then `dotnet build WarHub.Catalog.slnx -warnaserror` → clean.

- [ ] **Step 6: Commit** — `git commit -am "feat(paints): add archival PaintRecord model + CatalogStore reference"`

---

### Task 2: `PaintRecordMapper` — flat `Paint` → archival `PaintRecord`

**Files:**
- Create: `tools/WarHub.PaintCatalog.Tool/Reconcile/PaintRecordMapper.cs`
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Reconcile/PaintRecordMapperTests.cs`

**Interfaces:**
- Consumes: `Paint` (flat working model — fields `Name, ProductCode, Set, R, G, B, Hex, VolumeMl, Packaging, Ean, IsDiscontinued, Type, Finish, ImageUrl`).
- Produces: `static PaintRecord PaintRecordMapper.ToRecord(Paint p)` — used by Program (Task 6) and migration is independent.

- [ ] **Step 1: Write failing tests** (`PaintRecordMapperTests.cs`):

```csharp
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Reconcile;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Reconcile;

public class PaintRecordMapperTests
{
    private static Paint P(bool discontinued = false) => new()
    {
        Name = "Retributor Armour", ProductCode = "AURIC-1", Set = "Base",
        R = 138, G = 110, B = 62, Hex = "#8A6E3E", VolumeMl = 12,
        Packaging = "pot", Ean = "5011921027330", IsDiscontinued = discontinued,
        Type = "Base", Finish = "Metallic", ImageUrl = "https://img/x.jpg",
    };

    [Fact]
    public void ToRecord_SetsSharedCore_AndNestsDetails()
    {
        PaintRecord r = PaintRecordMapper.ToRecord(P());
        Assert.Equal("Retributor Armour", r.Name);
        Assert.Equal("paint", r.Category);
        Assert.Equal("current", r.Status);
        Assert.Equal("unknown", r.Availability);
        Assert.Null(r.FirstSeen);                 // reconciler stamps it
        Assert.Equal("AURIC-1", r.ProductCode);
        Assert.Equal("5011921027330", r.Ean);
        Assert.Equal("https://img/x.jpg", r.ImageUrl);
        Assert.Equal("Base", r.Details.Set);
        Assert.Equal(12, r.Details.VolumeMl);
        Assert.Equal("pot", r.Details.Container);  // renamed from Packaging
        Assert.Equal("Metallic", r.Details.Finish);
    }

    [Fact]
    public void ToRecord_Discontinued_MapsLifecycle()
    {
        PaintRecord r = PaintRecordMapper.ToRecord(P(discontinued: true));
        Assert.Equal("discontinued", r.Status);
        Assert.Equal("out_of_stock", r.Availability);
    }
}
```

- [ ] **Step 2: Run to verify fail** — `--filter PaintRecordMapperTests` → FAIL.

- [ ] **Step 3: Create `PaintRecordMapper.cs`:**

```csharp
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Reconcile;

/// <summary>Builds the archival <see cref="PaintRecord"/> from the flat working <see cref="Paint"/>.</summary>
public static class PaintRecordMapper
{
    public static PaintRecord ToRecord(Paint p) => new()
    {
        Name = p.Name,
        Category = "paint",
        Status = p.IsDiscontinued ? "discontinued" : "current",
        Availability = p.IsDiscontinued ? "out_of_stock" : "unknown",
        FirstSeen = null, // reconciler stamps write-once firstSeen
        ProductCode = p.ProductCode,
        Ean = p.Ean,
        ImageUrl = p.ImageUrl,
        Details = new PaintDetails
        {
            Set = p.Set,
            R = p.R,
            G = p.G,
            B = p.B,
            Hex = p.Hex,
            VolumeMl = p.VolumeMl,
            Container = p.Packaging,
            Type = p.Type,
            Finish = p.Finish,
        },
    };
}
```

- [ ] **Step 4: Run to verify pass** — `--filter PaintRecordMapperTests` → PASS; `dotnet build ... -warnaserror` clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(paints): map flat Paint to archival PaintRecord"`

---

### Task 3: `PaintRecordAdapter` — identity, merge, rename

**Files:**
- Create: `tools/WarHub.PaintCatalog.Tool/Reconcile/PaintRecordAdapter.cs`
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Reconcile/PaintRecordAdapterTests.cs`

**Interfaces:**
- Consumes: `ICatalogRecordAdapter<T>` (shared), `NameNormalizer` (shared), `PaintRecord`.
- Produces: `PaintRecordAdapter : ICatalogRecordAdapter<PaintRecord>` with `IdentityKey` = `Normalize(set)|Normalize(name)|Normalize(code)|Normalize(hex)`; `Url` returns `null`.

- [ ] **Step 1: Write failing tests** (`PaintRecordAdapterTests.cs`):

```csharp
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Reconcile;
using Xunit;

namespace WarHub.PaintCatalog.Tool.Tests.Reconcile;

public class PaintRecordAdapterTests
{
    private static PaintRecord R(string name = "Black", string set = "Base", string? code = "C1",
        string hex = "#000000", string status = "current", string availability = "unknown",
        int? vol = 12, string? finish = "Matte", string? ean = null, string? firstSeen = "2026-01-01") => new()
    {
        Name = name, Category = "paint", Status = status, Availability = availability,
        FirstSeen = firstSeen, ProductCode = code, Ean = ean, ImageUrl = null,
        Details = new PaintDetails { Set = set, R = 0, G = 0, B = 0, Hex = hex, VolumeMl = vol, Container = "pot", Type = "Base", Finish = finish },
    };

    private readonly PaintRecordAdapter _a = new();

    [Fact]
    public void IdentityKey_CombinesSetNameCodeHex_Normalized()
        => Assert.Equal("base|black|c1|#000000", _a.IdentityKey(R(name: "  Black ", set: "Base", code: "C1", hex: "#000000")));

    [Fact]
    public void IdentityKey_DistinguishesSameNameDifferentHex()
        => Assert.NotEqual(_a.IdentityKey(R(hex: "#010101", code: "A")), _a.IdentityKey(R(hex: "#000000", code: "B")));

    [Fact]
    public void Url_IsNull() => Assert.Null(_a.Url(R()));

    [Fact]
    public void Merge_UpdatesPresent_KeepsOnEmpty()
    {
        PaintRecord existing = R(ean: "111", vol: 12, finish: "Matte");
        PaintRecord fresh = R(ean: null, vol: 18, finish: null); // empty ean/finish kept; vol updated
        PaintRecord merged = _a.Merge(existing, fresh);
        Assert.Equal("111", merged.Ean);
        Assert.Equal(18, merged.Details.VolumeMl);
        Assert.Equal("Matte", merged.Details.Finish);
        Assert.Equal("2026-01-01", merged.FirstSeen); // immutable
    }

    [Fact]
    public void Merge_Status_StickyDiscontinued_AgainstFreshCurrent()
    {
        PaintRecord merged = _a.Merge(R(status: "discontinued"), R(status: "current"));
        Assert.Equal("discontinued", merged.Status);
    }

    [Fact]
    public void Merge_Status_FreshDiscontinuedWins()
    {
        PaintRecord merged = _a.Merge(R(status: "current"), R(status: "discontinued"));
        Assert.Equal("discontinued", merged.Status);
    }

    [Fact]
    public void WithFirstSeen_StampsOnlyWhenAbsent()
    {
        Assert.False(_a.HasFirstSeen(R(firstSeen: null)));
        Assert.Equal("2026-07-07", _a.WithFirstSeen(R(firstSeen: null), "2026-07-07").FirstSeen);
        Assert.True(_a.HasFirstSeen(R(firstSeen: "2026-01-01")));
    }
}
```

- [ ] **Step 2: Run to verify fail** — `--filter PaintRecordAdapterTests` → FAIL.

- [ ] **Step 3: Create `PaintRecordAdapter.cs`** (mirrors `ProductRecordAdapter`; identity components joined with `|`, all normalized; `Url` null; details merged field-by-field):

```csharp
using WarHub.CatalogStore;
using WarHub.CatalogStore.Reconcile;
using WarHub.PaintCatalog.Tool.Models;

namespace WarHub.PaintCatalog.Tool.Reconcile;

/// <summary>Adapts <see cref="PaintRecord"/> to the generic reconciler.</summary>
public sealed class PaintRecordAdapter : ICatalogRecordAdapter<PaintRecord>
{
    public string IdentityKey(PaintRecord r) => string.Join('|',
        NameNormalizer.Normalize(r.Details.Set),
        NameNormalizer.Normalize(r.Name),
        NameNormalizer.Normalize(r.ProductCode ?? ""),
        NameNormalizer.Normalize(r.Hex()));

    // Composite key is strong; product codes / image URLs are non-unique/empty in paint data,
    // so URL-based rename detection is disabled. Genuine renames use aliases: overrides.
    public string? Url(PaintRecord r) => null;

    public PaintRecord Merge(PaintRecord existing, PaintRecord fresh) => existing with
    {
        // Name, FirstSeen, Category, and the identity components (Set/Hex/ProductCode) are immutable.
        Status = fresh.Status is "discontinued" or "delisted" ? fresh.Status : existing.Status,
        Availability = Pick(fresh.Availability, existing.Availability) ?? "unknown",
        Ean = Pick(fresh.Ean, existing.Ean),
        ImageUrl = Pick(fresh.ImageUrl, existing.ImageUrl),
        Details = existing.Details with
        {
            VolumeMl = fresh.Details.VolumeMl ?? existing.Details.VolumeMl,
            Container = Pick(fresh.Details.Container, existing.Details.Container),
            Type = Pick(fresh.Details.Type, existing.Details.Type),
            Finish = Pick(fresh.Details.Finish, existing.Details.Finish),
        },
    };

    public PaintRecord WithFirstSeen(PaintRecord r, string isoDate) => r with { FirstSeen = isoDate };

    public bool HasFirstSeen(PaintRecord r) => !string.IsNullOrWhiteSpace(r.FirstSeen);

    public PaintRecord ApplyRename(PaintRecord existing, PaintRecord fresh) =>
        Merge(existing, fresh) with { Name = fresh.Name };

    private static string? Pick(string? fresh, string? existing) =>
        string.IsNullOrWhiteSpace(fresh) ? existing : fresh;
}

internal static class PaintRecordHexExtensions
{
    public static string Hex(this PaintRecord r) => r.Details.Hex;
}
```

Note: the `Hex()` helper keeps the `IdentityKey` line readable; inline `r.Details.Hex` directly if preferred — either is fine, no separate test needed for the helper.

- [ ] **Step 4: Run to verify pass** — `--filter PaintRecordAdapterTests` → PASS; build `-warnaserror` clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(paints): PaintRecordAdapter (set|name|code|hex identity, merge rules)"`

---

### Task 4: `BrandArchiveWriter` — deterministic write + load

**Files:**
- Create: `tools/WarHub.PaintCatalog.Tool/Output/BrandArchiveWriter.cs`
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Output/BrandArchiveWriterTests.cs`

**Interfaces:**
- Consumes: `CatalogSerializer` (shared), `BrandArchive`, `PaintRecord`.
- Produces: `Task WriteAsync(BrandArchive, string outputDir, CancellationToken)` → `brands/{brandSlug}.yaml`; `Task<IReadOnlyList<PaintRecord>> LoadAsync(string filePath, CancellationToken)` (empty list if file missing).

- [ ] **Step 1: Write failing tests** (`BrandArchiveWriterTests.cs`): assert (a) round-trip write→load preserves records; (b) a numeric-looking `ean`/`hex`/`productCode` is emitted **quoted** (contains `ean: '5011921027330'` and `hex: '#000000'` — hex already quotes via `#`, ean via QuotingEventEmitter); (c) null `firstSeen`/`ean` are omitted (OmitNull); (d) records are written sorted by identity key. Use a temp dir under the system temp path. Example core assertion:

```csharp
[Fact]
public async Task Write_QuotesNumericEan()
{
    var archive = new BrandArchive
    {
        Brand = "Citadel", BrandSlug = "citadel-colour",
        Paints = [ new PaintRecord {
            Name = "Abaddon Black", Category = "paint", Status = "current", Availability = "unknown",
            FirstSeen = "2026-07-07", ProductCode = "0605", Ean = "5011921027330", ImageUrl = null,
            Details = new PaintDetails { Set = "Base", R = 0, G = 0, B = 0, Hex = "#000000",
                VolumeMl = 12, Container = "pot", Type = "Base", Finish = "Matte" } } ],
    };
    string dir = Path.Combine(Path.GetTempPath(), "warhub-paint-test", Guid.NewGuid().ToString("N"));
    await BrandArchiveWriter.WriteAsync(archive, dir, default);
    string yaml = await File.ReadAllTextAsync(Path.Combine(dir, "brands", "citadel-colour.yaml"));
    Assert.Contains("ean: '5011921027330'", yaml);
    Assert.Contains("productCode: '0605'", yaml);
    Directory.Delete(dir, recursive: true);
}
```

Add a `WriteThenLoad_RoundTrips` test and a `Write_SortsByIdentityKey` test (two records inserted out of order come back sorted). Follow the product tool's `YamlCatalogWriter` + `LoadExistingFactionProductsAsync` for the exact serializer usage.

- [ ] **Step 2: Run to verify fail** — `--filter BrandArchiveWriterTests` → FAIL.

- [ ] **Step 3: Create `BrandArchiveWriter.cs`:**

```csharp
using WarHub.CatalogStore;
using WarHub.CatalogStore.Reconcile;
using WarHub.PaintCatalog.Tool.Models;
using WarHub.PaintCatalog.Tool.Reconcile;

namespace WarHub.PaintCatalog.Tool.Output;

/// <summary>Writes/loads per-brand archival YAML files with the shared deterministic serializer.</summary>
public static class BrandArchiveWriter
{
    private static readonly PaintRecordAdapter Adapter = new();

    public static async Task WriteAsync(BrandArchive archive, string outputDir, CancellationToken ct = default)
    {
        string brandsDir = Path.Combine(outputDir, "brands");
        Directory.CreateDirectory(brandsDir);

        var sorted = archive with
        {
            Paints = archive.Paints
                .OrderBy(p => Adapter.IdentityKey(p), StringComparer.Ordinal)
                .ToList(),
        };

        string yaml = CatalogSerializer.CreateSerializer().Serialize(sorted);
        await File.WriteAllTextAsync(Path.Combine(brandsDir, $"{archive.BrandSlug}.yaml"), yaml, ct);
    }

    public static async Task<IReadOnlyList<PaintRecord>> LoadAsync(string filePath, CancellationToken ct = default)
    {
        if (!File.Exists(filePath))
            return [];
        string yaml = await File.ReadAllTextAsync(filePath, ct);
        BrandArchive? archive = CatalogSerializer.CreateDeserializer().Deserialize<BrandArchive>(yaml);
        return archive?.Paints ?? [];
    }
}
```

- [ ] **Step 4: Run to verify pass** — `--filter BrandArchiveWriterTests` → PASS; build clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(paints): deterministic brand-archive writer/loader"`

---

### Task 5: `PaintOverrideAliases` — aliases + retract, scoped by brand

**Files:**
- Create: `tools/WarHub.PaintCatalog.Tool/Enrichment/PaintOverrideAliases.cs`
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Enrichment/PaintOverrideAliasesTests.cs`

**Interfaces:**
- Mirrors the product tool's `OverrideAliases`, but scoped by `brandSlug` (paints have no gs/faction).
- Produces: `static (IReadOnlyDictionary<string,string> Aliases, ISet<string> Retracted) Load(string? overridesPath, string brandSlug)`. Keys/values normalized via `NameNormalizer` — but the identity key is composite, so an alias/retract entry is the **full identity key** string; normalize with `NameNormalizer.Normalize` applied to the whole value (callers author full `set|name|code|hex` keys). Store aliases as `Normalize(newKey) → Normalize(oldKey)`, retracted as `Normalize(key)`.

- [ ] **Step 1: Write failing tests** — parse a temp overrides file:

```yaml
aliases:
  citadel-colour:
    'base|new name|c1|#000000': 'base|old name|c1|#000000'
retract:
  citadel-colour:
    - 'base|bad paint|x|#ffffff'
```

Assert the scoped brand returns the alias mapping and the retracted set; a different brand returns empty; a null/missing path returns empty. (Note: because identity keys are already normalized-lowercase, `Normalize` on them is idempotent — assert an entry authored in mixed case still matches.)

- [ ] **Step 2: Run to verify fail** — FAIL.

- [ ] **Step 3: Create `PaintOverrideAliases.cs`** (copy the structure of `tools/WarHub.ProductCatalog.Tool/Enrichment/OverrideAliases.cs`, replacing the `{mfg}/{gs}/{faction}` scope with `brandSlug`, and normalizing whole keys):

```csharp
using WarHub.CatalogStore;

namespace WarHub.PaintCatalog.Tool.Enrichment;

/// <summary>Loads rename aliases and retractions from overrides.yaml, scoped to one brand.</summary>
public static class PaintOverrideAliases
{
    private sealed class OverridesFile
    {
        public Dictionary<string, Dictionary<string, string>>? Aliases { get; init; }
        public Dictionary<string, List<string>>? Retract { get; init; }
    }

    public static (IReadOnlyDictionary<string, string> Aliases, ISet<string> Retracted) Load(
        string? overridesPath, string brandSlug)
    {
        var aliases = new Dictionary<string, string>(StringComparer.Ordinal);
        var retracted = new HashSet<string>(StringComparer.Ordinal);

        if (string.IsNullOrWhiteSpace(overridesPath) || !File.Exists(overridesPath))
            return (aliases, retracted);

        OverridesFile? parsed = CatalogSerializer.CreateDeserializer()
            .Deserialize<OverridesFile>(File.ReadAllText(overridesPath));
        if (parsed is null)
            return (aliases, retracted);

        if (parsed.Aliases is not null && parsed.Aliases.TryGetValue(brandSlug, out var scopedAliases))
            foreach (var (newKey, oldKey) in scopedAliases)
                aliases[NameNormalizer.Normalize(newKey)] = NameNormalizer.Normalize(oldKey);

        if (parsed.Retract is not null && parsed.Retract.TryGetValue(brandSlug, out var scopedRetract))
            foreach (string key in scopedRetract)
                retracted.Add(NameNormalizer.Normalize(key));

        return (aliases, retracted);
    }
}
```

Caveat for the reviewer: `NameNormalizer.Normalize` collapses whitespace and lowercases the **whole** key string including the `|` separators, which is consistent with how `PaintRecordAdapter.IdentityKey` builds keys from already-normalized segments — verify a hand-authored key round-trips to the same string the adapter produces (the test above covers this).

- [ ] **Step 4: Run to verify pass** — PASS; build clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(paints): brand-scoped aliases/retract loader"`

---

### Task 6: Program integration — enrich → map → reconcile → ledger → write

**Files:**
- Modify: `tools/WarHub.PaintCatalog.Tool/Program.cs`
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Integration/ReconcileIntegrationTests.cs` (new); keep `Integration/SampleModeTests.cs` green.

**Interfaces:**
- Consumes: everything from Tasks 1–5, plus shared `CatalogReconciler<PaintRecord>`, `LedgerStore`, `LivenessUpdater`.

**Context (current flow):** `Program.cs` parses markdown per brand → enriches (`VolumeEnricher`, `PaintTypeClassifier`, `FinishClassifier`, Vallejo EAN, `OverrideApplier`) → builds a flat `BrandCatalog` → writes it with `YamlCatalogWriter.WriteBrandAsync`. A second scraping phase adds Scalemates brands and Shopify-enriches existing catalogs, re-writing files. This task **replaces the write path** while keeping the working/enrichment/equivalence path intact.

**Required restructure (per brand, once all working `Paint`s for that brand are final — i.e. after Shopify enrichment):**

1. Collect the brand's final flat `List<Paint>` (as today, into `allCatalogs` for equivalence — unchanged).
2. Map: `List<PaintRecord> fresh = paints.Select(PaintRecordMapper.ToRecord).ToList();`
3. Load archive: `var existing = await BrandArchiveWriter.LoadAsync(brandFilePath, ct);` where `brandFilePath = Path.Combine(outputDir, "brands", $"{brandSlug}.yaml")`.
4. Reconcile:
```csharp
var adapter = new PaintRecordAdapter();
var reconciler = new CatalogReconciler<PaintRecord>(adapter);
(var aliases, var retracted) = PaintOverrideAliases.Load(overridesPath, brandSlug);
ReconcileResult<PaintRecord> reconciled = reconciler.Reconcile(existing, fresh, aliases, retracted, today);
```
5. Ledger (gated on `authoritativeRun`, source key = `brandSlug`), mirroring `Program.cs:442-482` of the product tool — seen/known/currentlyFlagged ledger keys are `{brandSlug}/{adapter.IdentityKey(p)}`; apply flag/reactivation transitions onto the records (`suspected-discontinued`/`current`, and set `Availability = "unknown"` on a fresh flag).
6. Write: build `BrandArchive` and `await BrandArchiveWriter.WriteAsync(archive, outputDir, ct);` (drop the old `YamlCatalogWriter.WriteBrandAsync` call).
7. After all brands: `if (authoritativeRun) await LedgerStore.SaveAsync(Path.Combine(outputDir, "_liveness.yaml"), ledger, ct);`

**Definitions:**
- `string today = DateTime.UtcNow.ToString("yyyy-MM-dd");`
- `bool authoritativeRun = sample == 0;` (a `--sample` run must not drive the ledger; `--brand` only touches its own source, so it is safe).
- **Source-success signal:** for a markdown brand, `succeeded = true` when its `.md` parsed without throwing and yielded ≥1 paint; for a scraped brand, `succeeded = scrapedPaints.Count > 0` (a failed/empty scrape flags nothing — same rule the product tool uses). Track a `bool` per processed brand and pass it as `sourceSucceeded`.
- **Manifest cleanup:** drop `TotalPaints` from `Manifest` and `PaintCount` from `BrandSummary` (derived; recomputed at publish). This requires editing `Models/Manifest.cs` (remove those two `required` properties) and their construction sites. Keep `Name`, `Slug`, `HasProductCodes`. (If removing `TotalPaints` ripples into the console summary line, compute the total locally for the log message only — do not serialize it.)

**Ordering note:** because a brand's file is written exactly once (after Shopify enrichment), move the per-brand write out of the markdown loop and the Scalemates loop into a single finalization pass keyed by brand. The simplest structure: accumulate a `Dictionary<string,(BrandMeta meta, List<Paint> paints, bool succeeded)>` across both phases, then a single `foreach` brand does map→load→reconcile→ledger→write. Preserve existing verbose logging.

- [ ] **Step 1: Write a failing integration test** (`ReconcileIntegrationTests.cs`): run the tool twice against a tiny fixture `--source` dir (or reuse the sample-mode harness) into a temp `--output`; assert (a) first run creates `brands/*.yaml` + `_liveness.yaml`; (b) **second run against identical input produces byte-identical brand files** (read both, `Assert.Equal`); (c) a record present in the archive but absent from a filtered second run (`--brand` other) is **not dropped**. Model it on the product tool's integration tests if present; otherwise assert the byte-identical guarantee on at least one brand file.

- [ ] **Step 2: Run to verify fail** — FAIL (tool still uses old writer / no ledger).

- [ ] **Step 3: Implement the restructure** described above. Reference `tools/WarHub.ProductCatalog.Tool/Program.cs:380-559` for the exact ledger wiring and transition logic; adapt keys to `{brandSlug}/{identityKey}`.

- [ ] **Step 4: Run tests** — `dotnet test tools/WarHub.PaintCatalog.Tool.Tests` → all pass (existing + new). Build `-warnaserror` clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(paints): append-only reconcile + liveness ledger in the paint tool"`

---

### Task 7: `PaintMigrator` — idempotent legacy → new schema

**Files:**
- Create: `tools/WarHub.PaintCatalog.Tool/Migration/PaintMigrator.cs`
- Modify: `tools/WarHub.PaintCatalog.Tool/Program.cs` — add a `migrate` subcommand.
- Test: `tools/WarHub.PaintCatalog.Tool.Tests/Migration/PaintMigratorTests.cs`

**Interfaces:**
- Produces: `static Task<int> PaintMigrator.MigrateAsync(string dataDir, string migrationDate, CancellationToken ct)`. `dataDir` = `data/paints`; reads `brands/*.yaml`, writes them in the new shape, seeds `_liveness.yaml`.

**Legacy shape (tolerant):** a `LegacyBrand { Brand, BrandSlug, Source, License, List<LegacyPaint> Paints }` (ignore `generatedAt`, `paintCount` via `IgnoreUnmatchedProperties` — already set on the shared deserializer). `LegacyPaint { Name, ProductCode, Set, R, G, B, Hex, VolumeMl, Packaging, Ean, IsDiscontinued, Type, Finish, ImageUrl, Category?, Status?, Availability?, Container?, Details? }`. Because the shared deserializer ignores unmatched properties, model the legacy paint with **both** the flat legacy fields **and** the optional new fields so a re-run reads its own output.

**Idempotency strategy (critical — the plan's headline proof):** to guarantee running twice yields zero diff, the migrator must read a file it already wrote and reproduce it exactly. Two sub-cases per paint:
- **Not yet migrated** (no `category`/`details` present, flat fields populated): map exactly as `PaintRecordMapper.ToRecord` does, then set `FirstSeen = migrationDate` (backfill).
- **Already migrated** (a `details` block + `category` present): reconstruct the `PaintRecord` from the new fields verbatim, **preserving** existing `firstSeen`, `status`, `availability`, and `details.container` (do not re-derive from `isDiscontinued`, so a human/ledger lifecycle edit survives re-migration).

Implement by deserializing into a legacy record that carries **both** shapes and branching on `legacy.Details is not null`. Backfill `firstSeen` only when absent. Sort by identity key with `PaintRecordAdapter`. Seed ledger key `{brandSlug}/{identityKey}` only-if-absent with `{ LastSeen = migrationDate, MissStreak = 0 }`. Model the whole file on `tools/WarHub.ProductCatalog.Tool/Migration/ProductMigrator.cs` (same idempotency guards).

- [ ] **Step 1: Write failing tests** (`PaintMigratorTests.cs`):
  - `Migrate_MapsLegacyPaint_ToNewShape` — write a legacy brand file (flat, with `packaging`, `isDiscontinued: true`, exploded `generatedAt`, `paintCount`), run migrate, load via `BrandArchiveWriter.LoadAsync`, assert `category == "paint"`, `status == "discontinued"`, `availability == "out_of_stock"`, `details.container == <old packaging>`, `firstSeen == migrationDate`, and that `generatedAt`/`paintCount` are gone from the file text.
  - `Migrate_IsIdempotent` — run migrate twice on a temp copy; assert the second run leaves every `brands/*.yaml` **byte-identical** and `_liveness.yaml` unchanged.
  - `Migrate_SeedsLedger_OnlyIfAbsent` — pre-seed one key with `missStreak: 5`; assert migrate leaves it at `5` (does not reset).
  - `Migrate_BackfillsFirstSeen_OnlyWhenAbsent` — a paint already carrying `firstSeen: 2020-01-01` keeps it.

- [ ] **Step 2: Run to verify fail** — FAIL.

- [ ] **Step 3: Implement `PaintMigrator.cs`** per the strategy above, and add the `migrate` subcommand to `Program.cs`:

```csharp
// after building rootCommand, before rootCommand.Parse(...).Invoke():
var migrateCommand = new Command("migrate", "One-time idempotent migration of data/paints to the new schema");
var migrateDirOption = new Option<DirectoryInfo>("--data") { Description = "Path to data/paints", Required = true };
migrateCommand.Options.Add(migrateDirOption);
migrateCommand.SetAction(async (pr, ct) =>
{
    DirectoryInfo dir = pr.GetValue(migrateDirOption)!;
    string date = DateTime.UtcNow.ToString("yyyy-MM-dd");
    return await WarHub.PaintCatalog.Tool.Migration.PaintMigrator.MigrateAsync(dir.FullName, date, ct);
});
rootCommand.Subcommands.Add(migrateCommand);
```

(Match the exact `System.CommandLine` API shape already used in this `Program.cs` and in the product tool's migrate subcommand.)

- [ ] **Step 4: Run tests** — `--filter PaintMigrator` → PASS; full `dotnet test tools/WarHub.PaintCatalog.Tool.Tests` green; build `-warnaserror` clean.

- [ ] **Step 5: Commit** — `git commit -am "feat(paints): idempotent migration to the new schema + migrate subcommand"`

---

### Task 8: Run the migration on `data/paints/` (one-time reformat)

**Files:**
- Modify (data): `data/paints/brands/*.yaml`, `data/paints/_liveness.yaml`, `data/paints/manifest.yaml` (if regenerated).

This is an execution task, not TDD — it produces the large, expected, one-time reformatting diff, exactly like Plan 1's product migration.

- [ ] **Step 1:** Ensure a clean working tree (all Task 1–7 commits in). Run:

```bash
dotnet run --project tools/WarHub.PaintCatalog.Tool -- migrate --data data/paints
```

- [ ] **Step 2: Verify no data loss.** Count paints before/after (a small script comparing the number of `- name:` entries per brand pre/post, or record counts from git). The total record count MUST be unchanged (identity key was proven collision-free → 0 merges). Investigate any delta before committing.

- [ ] **Step 3: Verify idempotency.** Run the migration a **second** time; `git diff --stat` MUST be empty. If not, fix `PaintMigrator` (Task 7) and re-run from a clean tree.

- [ ] **Step 4: Spot-check** two or three brand files (one code-full like `vallejo`, one code-less like `citadel-colour`, one scraped) for correct shape: `category: paint`, nested `details:`, quoted `ean`/`productCode`, no `generatedAt`/`paintCount`, `firstSeen` present.

- [ ] **Step 5: Commit** — `git add data/paints && git commit -m "chore(paints): migrate catalog to append-only storage model (one-time reformat)"`

---

## Notes for the executor

- The shared `WarHub.CatalogStore` library and the product tool are **frozen** — do not modify them; if a genuine gap appears, escalate rather than editing Plan-1 code.
- The flat `Paint`, `BrandCatalog`, `Manifest` (except the two dropped count fields), parser, all enrichers, all scrapers, and `EquivalenceFinder` are unchanged — equivalence still computes from the in-memory flat model.
- Re-run the full solution at the end: `dotnet test WarHub.Catalog.slnx` and `dotnet build WarHub.Catalog.slnx -warnaserror`. The final whole-branch review gates the stacked PR against `redesign-catalog-storage-model` (Plan 1), not `main`.
