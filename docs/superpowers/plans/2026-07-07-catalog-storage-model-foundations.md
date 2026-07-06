# Catalog Storage Model — Foundations & Product Catalog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared, testable `WarHub.CatalogStore` library implementing append-only, backfill-only reconciliation with stable identity, deterministic serialization, and a source-health-gated liveness ledger; then route the product-catalog tool through it and migrate the existing product data — fixing the data-loss (#4) and EAN-corruption (#5) bugs.

**Architecture:** A new class-library project `WarHub.CatalogStore` owns catalog-agnostic mechanics: name normalization, a YAML serializer that force-quotes ambiguous scalars, a liveness ledger with auto-flag logic, and a generic `CatalogReconciler<T>` driven by an `ICatalogRecordAdapter<T>`. The product tool supplies a `Product` adapter and calls the reconciler per faction instead of overwriting files. A one-time migration command rewrites existing data into the new schema.

**Tech Stack:** C# / .NET 10, records, YamlDotNet 18.1.0, xUnit 2.9.3. Central package management via `Directory.Packages.props`.

## Global Constraints

- Target framework: `net10.0` (copy from existing csproj). `ImplicitUsings` enable, `Nullable` enable.
- Central package management: reference packages **without** versions (`<PackageReference Include="YamlDotNet" />`); versions live in `Directory.Packages.props`.
- YAML naming convention: `CamelCaseNamingConvention` (matches existing files).
- All dates stored as ISO `yyyy-MM-dd` **strings**, never `DateTime`/`DateOnly` — this is a hard rule; the exploded-`DateTime` serialization is one of the bugs being removed.
- Serializer must keep: `ConfigureDefaultValuesHandling(DefaultValuesHandling.OmitNull)`, `DisableAliases()`, and literal block scalars (`|`) for multi-line strings.
- Test framework: xUnit. `using Xunit;` is implicit in test projects. Assertion style: `Assert.Equal`, `Assert.True`, etc. (match existing tests).
- The stability contract: reconciling an archive against an identical scrape MUST produce byte-identical output.

---

## File Structure

**New project `tools/WarHub.CatalogStore/`:**
- `WarHub.CatalogStore.csproj` — class library, refs YamlDotNet.
- `NameNormalizer.cs` — deterministic name normalization for identity keys.
- `CatalogSerializer.cs` — serializer/deserializer factory with quoting + block-scalar emitters.
- `QuotingEventEmitter.cs` — forces quoting of ambiguous string scalars.
- `Ledger/LivenessLedger.cs` — ledger data model (`LivenessLedger`, `LedgerSource`, `LedgerRecord`).
- `Ledger/LedgerStore.cs` — load/save `_liveness.yaml`.
- `Ledger/LivenessUpdater.cs` — miss-streak + health-gate + status-transition computation.
- `Reconcile/ICatalogRecordAdapter.cs` — per-catalog hook interface.
- `Reconcile/CatalogReconciler.cs` — generic reconcile flow + `ReconcileResult<T>`.

**New test project `tools/WarHub.CatalogStore.Tests/`** mirroring the above.

**Modified in `tools/WarHub.ProductCatalog.Tool/`:**
- `Models/Product.cs` — add `Category`, `Packaging`, `FirstSeen`; remove `ProductType` (replaced by `Packaging`).
- `Models/FactionCatalog.cs` — remove `ProductCount`.
- `Models/Manifest.cs` — remove count fields.
- `Enrichment/ProductEnricher.cs` — emit `Category` + `Packaging` instead of `ProductType`.
- `Enrichment/CategoryClassifier.cs` (new) — the category/packaging mapping.
- `Reconcile/ProductRecordAdapter.cs` (new) — implements `ICatalogRecordAdapter<Product>`.
- `Output/YamlCatalogWriter.cs` — use `CatalogSerializer`; sort products; drop counts.
- `Migration/ProductMigrator.cs` (new) — one-time idempotent schema migration.
- `Program.cs` — route the enrich/write phase through the reconciler + ledger; add a `migrate` subcommand.

**Modified root:** `WarHub.Catalog.slnx` — register the two new projects.

---

## Task 1: Scaffold `WarHub.CatalogStore` library + test project

**Files:**
- Create: `tools/WarHub.CatalogStore/WarHub.CatalogStore.csproj`
- Create: `tools/WarHub.CatalogStore.Tests/WarHub.CatalogStore.Tests.csproj`
- Create: `tools/WarHub.CatalogStore.Tests/SmokeTest.cs`
- Modify: `WarHub.Catalog.slnx`

**Interfaces:**
- Produces: two compilable projects registered in the solution; namespace `WarHub.CatalogStore`.

- [ ] **Step 1: Create the library csproj**

Create `tools/WarHub.CatalogStore/WarHub.CatalogStore.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
  </PropertyGroup>

  <ItemGroup>
    <InternalsVisibleTo Include="WarHub.CatalogStore.Tests" />
  </ItemGroup>

  <ItemGroup>
    <PackageReference Include="YamlDotNet" />
  </ItemGroup>

</Project>
```

- [ ] **Step 2: Create the test csproj**

Create `tools/WarHub.CatalogStore.Tests/WarHub.CatalogStore.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <IsPackable>false</IsPackable>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="coverlet.collector" />
    <PackageReference Include="Microsoft.NET.Test.Sdk" />
    <PackageReference Include="xunit" />
    <PackageReference Include="xunit.runner.visualstudio" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\WarHub.CatalogStore\WarHub.CatalogStore.csproj" />
  </ItemGroup>

  <ItemGroup>
    <Using Include="Xunit" />
  </ItemGroup>

</Project>
```

- [ ] **Step 3: Add a smoke test**

Create `tools/WarHub.CatalogStore.Tests/SmokeTest.cs`:

```csharp
namespace WarHub.CatalogStore.Tests;

public class SmokeTest
{
    [Fact]
    public void Projects_Compile_AndTestsRun()
    {
        Assert.True(true);
    }
}
```

- [ ] **Step 4: Register both projects in the solution**

In `WarHub.Catalog.slnx`, add inside `<Folder Name="/tools/">` (keep alphabetical order):

```xml
    <Project Path="tools/WarHub.CatalogStore.Tests/WarHub.CatalogStore.Tests.csproj" />
    <Project Path="tools/WarHub.CatalogStore/WarHub.CatalogStore.csproj" />
```

- [ ] **Step 5: Build and test**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~CatalogStore"`
Expected: build succeeds, 1 test passes.

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.CatalogStore tools/WarHub.CatalogStore.Tests WarHub.Catalog.slnx
git commit -m "feat(store): scaffold WarHub.CatalogStore library and test project"
```

---

## Task 2: `NameNormalizer`

**Files:**
- Create: `tools/WarHub.CatalogStore/NameNormalizer.cs`
- Test: `tools/WarHub.CatalogStore.Tests/NameNormalizerTests.cs`

**Interfaces:**
- Produces: `static string NameNormalizer.Normalize(string name)` — NFKC → lowercase → trim → collapse internal whitespace → strip surrounding single/double quotes. Deterministic; no punctuation stripping.

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.CatalogStore.Tests/NameNormalizerTests.cs`:

```csharp
namespace WarHub.CatalogStore.Tests;

public class NameNormalizerTests
{
    [Theory]
    [InlineData("Baratheon: Wardens", "baratheon: wardens")]
    [InlineData("  Space   Marines  ", "space marines")]
    [InlineData("'Quoted Name'", "quoted name")]
    [InlineData("\"Double Quoted\"", "double quoted")]
    [InlineData("Tabs\tand\nnewlines", "tabs and newlines")]
    public void Normalize_ProducesStableLowercaseKey(string input, string expected)
    {
        Assert.Equal(expected, NameNormalizer.Normalize(input));
    }

    [Fact]
    public void Normalize_IsIdempotent()
    {
        string once = NameNormalizer.Normalize("  The  Old  World  ");
        string twice = NameNormalizer.Normalize(once);
        Assert.Equal(once, twice);
    }

    [Fact]
    public void Normalize_AppliesNfkcSoCompatibilityFormsCollapse()
    {
        // Fullwidth 'A' (U+FF21) normalizes to ASCII 'a' under NFKC.
        Assert.Equal("a", NameNormalizer.Normalize("Ａ"));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~NameNormalizerTests"`
Expected: FAIL — `NameNormalizer` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `tools/WarHub.CatalogStore/NameNormalizer.cs`:

```csharp
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace WarHub.CatalogStore;

/// <summary>
/// Produces a deterministic, conservative normalized form of a product/paint name
/// for use as the stable identity key. Intentionally does NOT strip punctuation,
/// to avoid collapsing genuinely-distinct records.
/// </summary>
public static partial class NameNormalizer
{
    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();

    public static string Normalize(string name)
    {
        string nfkc = (name ?? string.Empty).Normalize(NormalizationForm.FormKC);
        string collapsed = Whitespace().Replace(nfkc, " ").Trim();
        collapsed = collapsed.Trim('\'', '"');
        collapsed = Whitespace().Replace(collapsed, " ").Trim();
        return collapsed.ToLowerInvariant();
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~NameNormalizerTests"`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add tools/WarHub.CatalogStore/NameNormalizer.cs tools/WarHub.CatalogStore.Tests/NameNormalizerTests.cs
git commit -m "feat(store): add NameNormalizer for stable identity keys"
```

---

## Task 3: Quoting YAML serializer

**Files:**
- Create: `tools/WarHub.CatalogStore/QuotingEventEmitter.cs`
- Create: `tools/WarHub.CatalogStore/CatalogSerializer.cs`
- Test: `tools/WarHub.CatalogStore.Tests/CatalogSerializerTests.cs`

**Interfaces:**
- Produces:
  - `static ISerializer CatalogSerializer.CreateSerializer()`
  - `static IDeserializer CatalogSerializer.CreateDeserializer()`
  - Serializer force-quotes any string scalar whose plain form would round-trip as a non-string (all-digits, bool-like, null-like, date-like), and uses literal block scalars for multi-line strings.

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.CatalogStore.Tests/CatalogSerializerTests.cs`:

```csharp
namespace WarHub.CatalogStore.Tests;

public class CatalogSerializerTests
{
    private sealed record Sample
    {
        public required string Ean { get; init; }
        public string? Note { get; init; }
        public required string Plain { get; init; }
    }

    [Fact]
    public void Serialize_AllDigitString_IsQuoted_AndRoundTripsAsString()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var deserializer = CatalogSerializer.CreateDeserializer();

        var obj = new Sample { Ean = "0889696010223", Plain = "Space Marines" };
        string yaml = serializer.Serialize(obj);

        Assert.Contains("ean: '0889696010223'", yaml);
        // Plain text stays unquoted for readability.
        Assert.Contains("plain: Space Marines", yaml);

        Sample back = deserializer.Deserialize<Sample>(yaml);
        Assert.Equal("0889696010223", back.Ean);
    }

    [Fact]
    public void Serialize_MultiLineString_UsesBlockScalar()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "1", Plain = "x", Note = "line one\nline two" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains("note: |", yaml);
    }

    [Theory]
    [InlineData("true")]
    [InlineData("null")]
    [InlineData("2026-07-07")]
    [InlineData("12.5")]
    public void Serialize_AmbiguousScalars_AreQuoted(string value)
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = value, Plain = "x" };
        string yaml = serializer.Serialize(obj);
        Assert.Contains($"ean: '{value}'", yaml);
    }

    [Fact]
    public void Serialize_OmitsNulls()
    {
        var serializer = CatalogSerializer.CreateSerializer();
        var obj = new Sample { Ean = "1", Plain = "x", Note = null };
        string yaml = serializer.Serialize(obj);
        Assert.DoesNotContain("note:", yaml);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~CatalogSerializerTests"`
Expected: FAIL — `CatalogSerializer` does not exist.

- [ ] **Step 3: Write the quoting emitter**

Create `tools/WarHub.CatalogStore/QuotingEventEmitter.cs`:

```csharp
using System.Text.RegularExpressions;
using YamlDotNet.Core;
using YamlDotNet.Core.Events;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.EventEmitters;

namespace WarHub.CatalogStore;

/// <summary>
/// Forces string scalars that would otherwise round-trip as a non-string
/// (integers, floats, booleans, nulls, dates) to be emitted single-quoted,
/// and multi-line strings to use literal block style. This prevents
/// schema-less parsers from re-typing values like EAN "0889…" as numbers.
/// </summary>
public sealed partial class QuotingEventEmitter(IEventEmitter next) : ChainedEventEmitter(next)
{
    // Core-schema-ambiguous plain scalars: int, float, bool, null, and ISO-ish dates.
    [GeneratedRegex(
        @"^(-?\d+(\.\d+)?|true|false|null|~|yes|no|on|off|\d{4}-\d{2}-\d{2}([Tt].*)?)$",
        RegexOptions.IgnoreCase)]
    private static partial Regex Ambiguous();

    public override void Emit(ScalarEventInfo eventInfo, IEmitter emitter)
    {
        if (eventInfo.Source.Type == typeof(string) &&
            eventInfo.Source.Value is string text)
        {
            if (text.Contains('\n'))
                eventInfo.Style = ScalarStyle.Literal;
            else if (text.Length > 0 && Ambiguous().IsMatch(text))
                eventInfo.Style = ScalarStyle.SingleQuoted;
        }

        base.Emit(eventInfo, emitter);
    }
}
```

- [ ] **Step 4: Write the serializer factory**

Create `tools/WarHub.CatalogStore/CatalogSerializer.cs`:

```csharp
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace WarHub.CatalogStore;

/// <summary>
/// Shared YAML (de)serializer for all catalog data files. Deterministic and
/// stable: force-quotes ambiguous scalars, omits nulls, disables anchors/aliases.
/// </summary>
public static class CatalogSerializer
{
    public static ISerializer CreateSerializer() =>
        new SerializerBuilder()
            .WithNamingConvention(CamelCaseNamingConvention.Instance)
            .WithEventEmitter(next => new QuotingEventEmitter(next))
            .ConfigureDefaultValuesHandling(DefaultValuesHandling.OmitNull)
            .DisableAliases()
            .Build();

    public static IDeserializer CreateDeserializer() =>
        new DeserializerBuilder()
            .WithNamingConvention(CamelCaseNamingConvention.Instance)
            .IgnoreUnmatchedProperties()
            .Build();
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~CatalogSerializerTests"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.CatalogStore/QuotingEventEmitter.cs tools/WarHub.CatalogStore/CatalogSerializer.cs tools/WarHub.CatalogStore.Tests/CatalogSerializerTests.cs
git commit -m "feat(store): add quoting YAML serializer (fixes EAN leading-zero loss)"
```

---

## Task 4: Liveness ledger model + store

**Files:**
- Create: `tools/WarHub.CatalogStore/Ledger/LivenessLedger.cs`
- Create: `tools/WarHub.CatalogStore/Ledger/LedgerStore.cs`
- Test: `tools/WarHub.CatalogStore.Tests/LedgerStoreTests.cs`

**Interfaces:**
- Produces:
  - `record LivenessLedger { int SchemaVersion; Dictionary<string,LedgerSource> Sources; Dictionary<string,LedgerRecord> Records; }`
  - `record LedgerSource { string? LastRun; string? LastGoodRun; bool LastRunSucceeded; int ProductCount; }`
  - `record LedgerRecord { required string LastSeen; int MissStreak; }`
  - `static Task<LivenessLedger> LedgerStore.LoadAsync(string path, CancellationToken)` — returns empty ledger if file missing.
  - `static Task LedgerStore.SaveAsync(string path, LivenessLedger ledger, CancellationToken)`
- All dates are ISO `yyyy-MM-dd` strings.

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.CatalogStore.Tests/LedgerStoreTests.cs`:

```csharp
using WarHub.CatalogStore.Ledger;

namespace WarHub.CatalogStore.Tests;

public class LedgerStoreTests
{
    [Fact]
    public async Task LoadAsync_MissingFile_ReturnsEmptyLedger()
    {
        string path = Path.Combine(Path.GetTempPath(), $"missing-{Guid.NewGuid():N}.yaml");
        LivenessLedger ledger = await LedgerStore.LoadAsync(path, default);
        Assert.Equal(1, ledger.SchemaVersion);
        Assert.Empty(ledger.Sources);
        Assert.Empty(ledger.Records);
    }

    [Fact]
    public async Task SaveThenLoad_RoundTrips()
    {
        string path = Path.Combine(Path.GetTempPath(), $"ledger-{Guid.NewGuid():N}.yaml");
        try
        {
            var ledger = new LivenessLedger
            {
                Sources = { ["cmon"] = new LedgerSource { LastRun = "2026-07-07", LastGoodRun = "2026-07-07", LastRunSucceeded = true, ProductCount = 337 } },
                Records = { ["cmon/asoiaf/baratheon/baratheon-wardens"] = new LedgerRecord { LastSeen = "2026-07-07", MissStreak = 0 } },
            };
            await LedgerStore.SaveAsync(path, ledger, default);
            LivenessLedger back = await LedgerStore.LoadAsync(path, default);

            Assert.True(back.Sources["cmon"].LastRunSucceeded);
            Assert.Equal("2026-07-07", back.Records["cmon/asoiaf/baratheon/baratheon-wardens"].LastSeen);
        }
        finally { File.Delete(path); }
    }

    [Fact]
    public async Task Save_DoesNotEmitExplodedDates()
    {
        string path = Path.Combine(Path.GetTempPath(), $"ledger-{Guid.NewGuid():N}.yaml");
        try
        {
            var ledger = new LivenessLedger
            {
                Records = { ["k"] = new LedgerRecord { LastSeen = "2026-07-07", MissStreak = 2 } },
            };
            await LedgerStore.SaveAsync(path, ledger, default);
            string yaml = await File.ReadAllTextAsync(path);
            Assert.DoesNotContain("ticks", yaml);
            Assert.DoesNotContain("dayOfWeek", yaml);
            Assert.Contains("lastSeen: '2026-07-07'", yaml);
        }
        finally { File.Delete(path); }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~LedgerStoreTests"`
Expected: FAIL — types do not exist.

- [ ] **Step 3: Write the ledger model**

Create `tools/WarHub.CatalogStore/Ledger/LivenessLedger.cs`:

```csharp
namespace WarHub.CatalogStore.Ledger;

/// <summary>
/// Volatile per-run liveness state, kept in a single sidecar file per catalog
/// so the data files stay churn-free. All dates are ISO yyyy-MM-dd strings.
/// </summary>
public sealed record LivenessLedger
{
    public int SchemaVersion { get; init; } = 1;
    public Dictionary<string, LedgerSource> Sources { get; init; } = new();
    public Dictionary<string, LedgerRecord> Records { get; init; } = new();
}

/// <summary>Per-source scrape health, keyed by source slug (e.g. manufacturer slug).</summary>
public sealed record LedgerSource
{
    public string? LastRun { get; init; }
    public string? LastGoodRun { get; init; }
    public bool LastRunSucceeded { get; init; }
    public int ProductCount { get; init; }
}

/// <summary>Per-record liveness, keyed by the record's full path identity key.</summary>
public sealed record LedgerRecord
{
    public required string LastSeen { get; init; }
    public int MissStreak { get; init; }
}
```

- [ ] **Step 4: Write the ledger store**

Create `tools/WarHub.CatalogStore/Ledger/LedgerStore.cs`:

```csharp
namespace WarHub.CatalogStore.Ledger;

/// <summary>Loads and saves the liveness ledger sidecar file.</summary>
public static class LedgerStore
{
    public static async Task<LivenessLedger> LoadAsync(string path, CancellationToken ct = default)
    {
        if (!File.Exists(path))
            return new LivenessLedger();

        string yaml = await File.ReadAllTextAsync(path, ct);
        LivenessLedger? ledger = CatalogSerializer.CreateDeserializer().Deserialize<LivenessLedger>(yaml);
        return ledger ?? new LivenessLedger();
    }

    public static async Task SaveAsync(string path, LivenessLedger ledger, CancellationToken ct = default)
    {
        string? dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        string yaml = CatalogSerializer.CreateSerializer().Serialize(ledger);
        await File.WriteAllTextAsync(path, yaml, ct);
    }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~LedgerStoreTests"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.CatalogStore/Ledger tools/WarHub.CatalogStore.Tests/LedgerStoreTests.cs
git commit -m "feat(store): add liveness ledger model and sidecar store"
```

---

## Task 5: Liveness auto-flag logic

**Files:**
- Create: `tools/WarHub.CatalogStore/Ledger/LivenessUpdater.cs`
- Test: `tools/WarHub.CatalogStore.Tests/LivenessUpdaterTests.cs`

**Interfaces:**
- Consumes: `LivenessLedger`, `LedgerSource`, `LedgerRecord` (Task 4).
- Produces:
  - `record LivenessUpdate(LivenessLedger Ledger, IReadOnlySet<string> Flagged, IReadOnlySet<string> Reactivated)` — `Flagged` = record keys that crossed the miss threshold this run; `Reactivated` = record keys previously flagged that were seen again.
  - `static LivenessUpdate LivenessUpdater.Apply(LivenessLedger ledger, string sourceKey, bool sourceSucceeded, int scrapedCount, IReadOnlySet<string> seenKeys, IReadOnlyCollection<string> knownKeysForSource, string today, int missThreshold = 3, IReadOnlySet<string>? currentlyFlaggedKeys = null)`.
- Rules: if `sourceSucceeded` is false, record the run as failed and change no miss counters and flag nothing. If true: seen keys reset `MissStreak` to 0 and set `LastSeen`; unseen known keys increment `MissStreak`; a key crossing `missThreshold` is added to `Flagged`; a seen key that is in `currentlyFlaggedKeys` is added to `Reactivated`.

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.CatalogStore.Tests/LivenessUpdaterTests.cs`:

```csharp
using WarHub.CatalogStore.Ledger;

namespace WarHub.CatalogStore.Tests;

public class LivenessUpdaterTests
{
    private static LivenessLedger LedgerWith(params (string Key, int Miss)[] records)
    {
        var l = new LivenessLedger();
        foreach (var (key, miss) in records)
            l.Records[key] = new LedgerRecord { LastSeen = "2026-01-01", MissStreak = miss };
        return l;
    }

    [Fact]
    public void FailedSource_TouchesNoMissCountersAndFlagsNothing()
    {
        LivenessLedger ledger = LedgerWith(("a", 2), ("b", 0));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: false, scrapedCount: 0,
            seenKeys: new HashSet<string>(), knownKeysForSource: new[] { "a", "b" },
            today: "2026-07-07");

        Assert.Equal(2, result.Ledger.Records["a"].MissStreak);
        Assert.Equal(0, result.Ledger.Records["b"].MissStreak);
        Assert.Empty(result.Flagged);
        Assert.False(result.Ledger.Sources["cmon"].LastRunSucceeded);
        Assert.Equal("2026-07-07", result.Ledger.Sources["cmon"].LastRun);
        Assert.Null(result.Ledger.Sources["cmon"].LastGoodRun);
    }

    [Fact]
    public void SeenKey_ResetsMissStreakAndStampsLastSeen()
    {
        LivenessLedger ledger = LedgerWith(("a", 2));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 1,
            seenKeys: new HashSet<string> { "a" }, knownKeysForSource: new[] { "a" },
            today: "2026-07-07");

        Assert.Equal(0, result.Ledger.Records["a"].MissStreak);
        Assert.Equal("2026-07-07", result.Ledger.Records["a"].LastSeen);
        Assert.Equal("2026-07-07", result.Ledger.Sources["cmon"].LastGoodRun);
    }

    [Fact]
    public void UnseenKey_CrossingThreshold_IsFlagged()
    {
        LivenessLedger ledger = LedgerWith(("a", 2)); // 2 -> 3 crosses default threshold 3
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 5,
            seenKeys: new HashSet<string>(), knownKeysForSource: new[] { "a" },
            today: "2026-07-07");

        Assert.Equal(3, result.Ledger.Records["a"].MissStreak);
        Assert.Contains("a", result.Flagged);
    }

    [Fact]
    public void UnseenKey_BelowThreshold_IsNotFlagged()
    {
        LivenessLedger ledger = LedgerWith(("a", 0));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 5,
            seenKeys: new HashSet<string>(), knownKeysForSource: new[] { "a" },
            today: "2026-07-07");

        Assert.Equal(1, result.Ledger.Records["a"].MissStreak);
        Assert.Empty(result.Flagged);
    }

    [Fact]
    public void PreviouslyFlaggedKey_SeenAgain_IsReactivated()
    {
        LivenessLedger ledger = LedgerWith(("a", 5));
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 5,
            seenKeys: new HashSet<string> { "a" }, knownKeysForSource: new[] { "a" },
            today: "2026-07-07",
            currentlyFlaggedKeys: new HashSet<string> { "a" });

        Assert.Contains("a", result.Reactivated);
        Assert.Equal(0, result.Ledger.Records["a"].MissStreak);
    }

    [Fact]
    public void NewSeenKey_NotPreviouslyKnown_IsRecorded()
    {
        var ledger = new LivenessLedger();
        LivenessUpdate result = LivenessUpdater.Apply(
            ledger, "cmon", sourceSucceeded: true, scrapedCount: 1,
            seenKeys: new HashSet<string> { "new" }, knownKeysForSource: Array.Empty<string>(),
            today: "2026-07-07");

        Assert.Equal(0, result.Ledger.Records["new"].MissStreak);
        Assert.Equal("2026-07-07", result.Ledger.Records["new"].LastSeen);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~LivenessUpdaterTests"`
Expected: FAIL — `LivenessUpdater` does not exist.

- [ ] **Step 3: Write the implementation**

Create `tools/WarHub.CatalogStore/Ledger/LivenessUpdater.cs`:

```csharp
namespace WarHub.CatalogStore.Ledger;

/// <summary>Result of applying one source's scrape outcome to the ledger.</summary>
public sealed record LivenessUpdate(
    LivenessLedger Ledger,
    IReadOnlySet<string> Flagged,
    IReadOnlySet<string> Reactivated);

/// <summary>
/// Applies a single source's scrape outcome to the ledger: updates per-source
/// health, resets/increments per-record miss streaks (gated on source success),
/// and computes which records cross the auto-flag threshold or reactivate.
/// </summary>
public static class LivenessUpdater
{
    public static LivenessUpdate Apply(
        LivenessLedger ledger,
        string sourceKey,
        bool sourceSucceeded,
        int scrapedCount,
        IReadOnlySet<string> seenKeys,
        IReadOnlyCollection<string> knownKeysForSource,
        string today,
        int missThreshold = 3,
        IReadOnlySet<string>? currentlyFlaggedKeys = null)
    {
        currentlyFlaggedKeys ??= new HashSet<string>();
        var flagged = new HashSet<string>();
        var reactivated = new HashSet<string>();

        LedgerSource prior = ledger.Sources.GetValueOrDefault(sourceKey) ?? new LedgerSource();

        if (!sourceSucceeded)
        {
            ledger.Sources[sourceKey] = prior with
            {
                LastRun = today,
                LastRunSucceeded = false,
            };
            return new LivenessUpdate(ledger, flagged, reactivated);
        }

        ledger.Sources[sourceKey] = prior with
        {
            LastRun = today,
            LastGoodRun = today,
            LastRunSucceeded = true,
            ProductCount = scrapedCount,
        };

        // Seen records: reset streak, stamp last-seen, reactivate if previously flagged.
        foreach (string key in seenKeys)
        {
            ledger.Records[key] = new LedgerRecord { LastSeen = today, MissStreak = 0 };
            if (currentlyFlaggedKeys.Contains(key))
                reactivated.Add(key);
        }

        // Known-but-unseen records: increment streak; flag on crossing the threshold.
        foreach (string key in knownKeysForSource)
        {
            if (seenKeys.Contains(key))
                continue;

            LedgerRecord prev = ledger.Records.GetValueOrDefault(key)
                ?? new LedgerRecord { LastSeen = today, MissStreak = 0 };
            int newStreak = prev.MissStreak + 1;
            ledger.Records[key] = prev with { MissStreak = newStreak };

            if (newStreak == missThreshold)
                flagged.Add(key);
        }

        return new LivenessUpdate(ledger, flagged, reactivated);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~LivenessUpdaterTests"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/WarHub.CatalogStore/Ledger/LivenessUpdater.cs tools/WarHub.CatalogStore.Tests/LivenessUpdaterTests.cs
git commit -m "feat(store): add source-health-gated liveness auto-flag logic"
```

---

## Task 6: Generic reconciler + adapter interface

**Files:**
- Create: `tools/WarHub.CatalogStore/Reconcile/ICatalogRecordAdapter.cs`
- Create: `tools/WarHub.CatalogStore/Reconcile/CatalogReconciler.cs`
- Test: `tools/WarHub.CatalogStore.Tests/CatalogReconcilerTests.cs`

**Interfaces:**
- Produces:
  - `interface ICatalogRecordAdapter<T>` with:
    - `string IdentityKey(T record)` — normalized identity, unique within the reconciled set (a faction).
    - `string? Url(T record)`
    - `T Merge(T existing, T fresh)` — update-present/keep-on-empty; MUST preserve identity + firstSeen.
    - `T WithFirstSeen(T record, string isoDate)`
    - `bool HasFirstSeen(T record)`
    - `T ApplyRename(T existing, T fresh)` — keep existing identity/firstSeen, adopt fresh's mutable fields incl. new name.
  - `record ReconcileResult<T>(IReadOnlyList<T> Records, IReadOnlySet<string> SeenKeys)` — `Records` sorted by identity key; `SeenKeys` = identity keys matched or inserted this run.
  - `class CatalogReconciler<T>(ICatalogRecordAdapter<T> adapter)` with:
    - `ReconcileResult<T> Reconcile(IReadOnlyList<T> existing, IReadOnlyList<T> fresh, IReadOnlyDictionary<string,string> aliases, ISet<string> retracted, string today)`.
- Flow: match fresh→existing by identity key, else by URL (rename), else by alias map (`oldKey→newKey`); matched → `Merge`; unmatched → insert with `WithFirstSeen(today)` if missing. Existing records not matched are kept untouched. Records whose identity key is in `retracted` are dropped. Output sorted by identity key (ordinal).

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.CatalogStore.Tests/CatalogReconcilerTests.cs`:

```csharp
using WarHub.CatalogStore.Reconcile;

namespace WarHub.CatalogStore.Tests;

public class CatalogReconcilerTests
{
    // Minimal test record + adapter exercising the generic flow.
    private sealed record Rec
    {
        public required string Name { get; init; }
        public string? Url { get; init; }
        public string? Price { get; init; }
        public string? FirstSeen { get; init; }
    }

    private sealed class RecAdapter : ICatalogRecordAdapter<Rec>
    {
        public string IdentityKey(Rec r) => NameNormalizer.Normalize(r.Name);
        public string? Url(Rec r) => r.Url;
        public Rec Merge(Rec existing, Rec fresh) => existing with
        {
            // update-present, keep-on-empty
            Price = string.IsNullOrEmpty(fresh.Price) ? existing.Price : fresh.Price,
            Url = string.IsNullOrEmpty(fresh.Url) ? existing.Url : fresh.Url,
        };
        public Rec WithFirstSeen(Rec r, string isoDate) => r with { FirstSeen = isoDate };
        public bool HasFirstSeen(Rec r) => !string.IsNullOrEmpty(r.FirstSeen);
        public Rec ApplyRename(Rec existing, Rec fresh) => existing with
        {
            Name = fresh.Name,
            Price = string.IsNullOrEmpty(fresh.Price) ? existing.Price : fresh.Price,
        };
    }

    private static readonly Dictionary<string, string> NoAliases = new();
    private static readonly HashSet<string> NoRetract = new();

    private static CatalogReconciler<Rec> NewReconciler() => new(new RecAdapter());

    [Fact]
    public void MissingFromScrape_IsKeptNotDropped()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", FirstSeen = "2026-01-01" } };
        var fresh = new List<Rec>(); // scrape returned nothing

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Single(result.Records);
        Assert.Equal("Alpha", result.Records[0].Name);
        Assert.Empty(result.SeenKeys);
    }

    [Fact]
    public void PartialScrape_DoesNotBlankFields()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", Price = "10", FirstSeen = "2026-01-01" } };
        var fresh = new List<Rec> { new() { Name = "Alpha", Price = null } }; // price missing this run

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("10", result.Records[0].Price);
        Assert.Contains("alpha", result.SeenKeys);
    }

    [Fact]
    public void UpdatedField_Overwrites()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", Price = "10", FirstSeen = "2026-01-01" } };
        var fresh = new List<Rec> { new() { Name = "Alpha", Price = "12" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("12", result.Records[0].Price);
    }

    [Fact]
    public void NewProduct_GetsFirstSeenToday()
    {
        var existing = new List<Rec>();
        var fresh = new List<Rec> { new() { Name = "Beta" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("2026-07-07", result.Records[0].FirstSeen);
    }

    [Fact]
    public void ExistingFirstSeen_IsPreserved()
    {
        var existing = new List<Rec> { new() { Name = "Alpha", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec> { new() { Name = "Alpha" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal("2020-01-01", result.Records[0].FirstSeen);
    }

    [Fact]
    public void UrlMatch_RenamesInsteadOfDuplicating()
    {
        var existing = new List<Rec> { new() { Name = "Old Name", Url = "http://x/1", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec> { new() { Name = "New Name", Url = "http://x/1" } };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Single(result.Records);
        Assert.Equal("New Name", result.Records[0].Name);
        Assert.Equal("2020-01-01", result.Records[0].FirstSeen);
    }

    [Fact]
    public void AliasMap_StitchesRenameWhenUrlDiffers()
    {
        var existing = new List<Rec> { new() { Name = "Old Name", Url = "http://x/1", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec> { new() { Name = "New Name", Url = "http://x/2" } };
        var aliases = new Dictionary<string, string> { ["new name"] = "old name" };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, aliases, NoRetract, "2026-07-07");

        Assert.Single(result.Records);
        Assert.Equal("New Name", result.Records[0].Name);
        Assert.Equal("2020-01-01", result.Records[0].FirstSeen);
    }

    [Fact]
    public void Retract_DropsRecord()
    {
        var existing = new List<Rec> { new() { Name = "Bad", FirstSeen = "2020-01-01" } };
        var fresh = new List<Rec>();
        var retract = new HashSet<string> { "bad" };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, retract, "2026-07-07");

        Assert.Empty(result.Records);
    }

    [Fact]
    public void Output_IsSortedByIdentityKey()
    {
        var existing = new List<Rec>();
        var fresh = new List<Rec>
        {
            new() { Name = "Zeta" },
            new() { Name = "Alpha" },
            new() { Name = "Mu" },
        };

        ReconcileResult<Rec> result = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");

        Assert.Equal(new[] { "Alpha", "Mu", "Zeta" }, result.Records.Select(r => r.Name).ToArray());
    }

    [Fact]
    public void IdenticalRescrape_IsStable()
    {
        var existing = new List<Rec>
        {
            new() { Name = "Alpha", Price = "10", FirstSeen = "2020-01-01" },
            new() { Name = "Beta", Price = "20", FirstSeen = "2020-01-01" },
        };
        var fresh = new List<Rec>
        {
            new() { Name = "Alpha", Price = "10" },
            new() { Name = "Beta", Price = "20" },
        };

        ReconcileResult<Rec> first = NewReconciler().Reconcile(existing, fresh, NoAliases, NoRetract, "2026-07-07");
        ReconcileResult<Rec> second = NewReconciler().Reconcile(first.Records, fresh, NoAliases, NoRetract, "2026-07-08");

        Assert.Equal(
            first.Records.Select(r => (r.Name, r.Price, r.FirstSeen)),
            second.Records.Select(r => (r.Name, r.Price, r.FirstSeen)));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~CatalogReconcilerTests"`
Expected: FAIL — types do not exist.

- [ ] **Step 3: Write the adapter interface**

Create `tools/WarHub.CatalogStore/Reconcile/ICatalogRecordAdapter.cs`:

```csharp
namespace WarHub.CatalogStore.Reconcile;

/// <summary>
/// Per-catalog hooks the generic reconciler needs to identify, match, merge,
/// and stamp records. Implementations are pure (no I/O).
/// </summary>
public interface ICatalogRecordAdapter<T>
{
    /// <summary>Normalized identity, unique within a single reconciled set (a faction file).</summary>
    string IdentityKey(T record);

    /// <summary>Canonical source URL, used as the rename-detection fallback. Null if none.</summary>
    string? Url(T record);

    /// <summary>Merge a re-scraped record into the archived one: update-present, keep-on-empty. Preserves identity + firstSeen.</summary>
    T Merge(T existing, T fresh);

    /// <summary>Stamp the write-once firstSeen date.</summary>
    T WithFirstSeen(T record, string isoDate);

    /// <summary>True if the record already carries a firstSeen date.</summary>
    bool HasFirstSeen(T record);

    /// <summary>Apply a rename: keep existing identity + firstSeen, adopt fresh's name and mutable fields.</summary>
    T ApplyRename(T existing, T fresh);
}
```

- [ ] **Step 4: Write the reconciler**

Create `tools/WarHub.CatalogStore/Reconcile/CatalogReconciler.cs`:

```csharp
namespace WarHub.CatalogStore.Reconcile;

/// <summary>Merged records (sorted by identity key) plus the keys seen this run.</summary>
public sealed record ReconcileResult<T>(IReadOnlyList<T> Records, IReadOnlySet<string> SeenKeys);

/// <summary>
/// Append-only, backfill-only reconciliation of a fresh scrape against the
/// archived records for one set (a faction file). Never drops archived records
/// except via the explicit retract set. Deterministic output order.
/// </summary>
public sealed class CatalogReconciler<T>(ICatalogRecordAdapter<T> adapter)
{
    public ReconcileResult<T> Reconcile(
        IReadOnlyList<T> existing,
        IReadOnlyList<T> fresh,
        IReadOnlyDictionary<string, string> aliases,
        ISet<string> retracted,
        string today)
    {
        // Index existing by identity key and by URL (first wins on URL collisions).
        var byKey = new Dictionary<string, T>(StringComparer.Ordinal);
        var byUrl = new Dictionary<string, string>(StringComparer.Ordinal); // url -> identity key
        foreach (T rec in existing)
        {
            string key = adapter.IdentityKey(rec);
            byKey[key] = rec;
            string? url = adapter.Url(rec);
            if (!string.IsNullOrEmpty(url))
                byUrl.TryAdd(url, key);
        }

        var seen = new HashSet<string>(StringComparer.Ordinal);

        foreach (T freshRec in fresh)
        {
            string freshKey = adapter.IdentityKey(freshRec);

            // 1. Composite key match.
            if (byKey.TryGetValue(freshKey, out T? existingByKey))
            {
                byKey[freshKey] = adapter.Merge(existingByKey, freshRec);
                seen.Add(freshKey);
                continue;
            }

            // 2. URL fallback → rename.
            string? freshUrl = adapter.Url(freshRec);
            if (!string.IsNullOrEmpty(freshUrl) && byUrl.TryGetValue(freshUrl, out string? renamedKey)
                && byKey.TryGetValue(renamedKey, out T? existingByUrl))
            {
                byKey.Remove(renamedKey);
                T renamed = adapter.ApplyRename(existingByUrl, freshRec);
                byKey[freshKey] = renamed;
                seen.Add(freshKey);
                continue;
            }

            // 3. Alias override → rename (freshKey -> canonical existing key).
            if (aliases.TryGetValue(freshKey, out string? canonicalKey)
                && byKey.TryGetValue(canonicalKey, out T? existingByAlias))
            {
                byKey.Remove(canonicalKey);
                T renamed = adapter.ApplyRename(existingByAlias, freshRec);
                byKey[freshKey] = renamed;
                seen.Add(freshKey);
                continue;
            }

            // 4. New record.
            T inserted = adapter.HasFirstSeen(freshRec) ? freshRec : adapter.WithFirstSeen(freshRec, today);
            byKey[freshKey] = inserted;
            seen.Add(freshKey);
        }

        // Apply retractions, then order deterministically.
        var ordered = byKey
            .Where(kvp => !retracted.Contains(kvp.Key))
            .OrderBy(kvp => kvp.Key, StringComparer.Ordinal)
            .Select(kvp => kvp.Value)
            .ToList();

        return new ReconcileResult<T>(ordered, seen);
    }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~CatalogReconcilerTests"`
Expected: PASS (all cases).

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.CatalogStore/Reconcile tools/WarHub.CatalogStore.Tests/CatalogReconcilerTests.cs
git commit -m "feat(store): add generic append-only CatalogReconciler"
```

---

## Task 7: Product model — new schema fields

**Files:**
- Modify: `tools/WarHub.ProductCatalog.Tool/Models/Product.cs`
- Modify: `tools/WarHub.ProductCatalog.Tool/Models/FactionCatalog.cs`
- Modify: `tools/WarHub.ProductCatalog.Tool/Models/Manifest.cs`
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Models/ProductSchemaTests.cs`

**Interfaces:**
- Produces: `Product` gains `Category` (string, required), `Packaging` (string, required), `FirstSeen` (string?, ISO date); loses `ProductType`. `FactionCatalog` loses `ProductCount`. Field order in `Product` (which drives YAML field order) is: `Name, Category, Packaging, Status, FirstSeen, Ean, EanSource, Sku, ProductCode, PriceGbp, PriceUsd, PriceEur, Url, ImageUrl, ReleaseDate, Description, Contents`.

> **Note for implementer:** This task breaks compilation of `ProductEnricher`, `Program.cs`, and existing tests that reference `ProductType`/`ProductCount`. That is expected — Tasks 8–11 fix each call site. To keep this task's build green in isolation, this task also updates the direct model consumers minimally (shown in Step 3). Do not attempt to wire the reconciler here.

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.ProductCatalog.Tool.Tests/Models/ProductSchemaTests.cs`:

```csharp
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Tests.Models;

public class ProductSchemaTests
{
    [Fact]
    public void Product_HasCategoryPackagingAndFirstSeen()
    {
        var p = new Product
        {
            Name = "Test",
            Category = "miniatures",
            Packaging = "single",
            Status = "current",
            FirstSeen = "2026-07-07",
        };

        Assert.Equal("miniatures", p.Category);
        Assert.Equal("single", p.Packaging);
        Assert.Equal("2026-07-07", p.FirstSeen);
    }

    [Fact]
    public void FactionCatalog_HasNoProductCountProperty()
    {
        Assert.Null(typeof(FactionCatalog).GetProperty("ProductCount"));
    }

    [Fact]
    public void Product_HasNoProductTypeProperty()
    {
        Assert.Null(typeof(Product).GetProperty("ProductType"));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet build tools/WarHub.ProductCatalog.Tool.Tests`
Expected: FAIL — `Product` has no `Category`/`Packaging`/`FirstSeen`; `ProductType` still present.

- [ ] **Step 3: Update the models**

Replace `tools/WarHub.ProductCatalog.Tool/Models/Product.cs` with:

```csharp
namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Represents a single catalog product (miniature kit, terrain, accessory, etc.).
/// Field declaration order defines YAML emission order.
/// </summary>
public record Product
{
    public required string Name { get; init; }

    /// <summary>What the thing is: miniatures | terrain | accessory | paint | book | tool.</summary>
    public required string Category { get; init; }

    /// <summary>How it is sold: single | bundle | box | starter.</summary>
    public required string Packaging { get; init; }

    /// <summary>current | suspected-discontinued | discontinued | delisted.</summary>
    public required string Status { get; init; }

    /// <summary>Write-once ISO yyyy-MM-dd date the record was first archived.</summary>
    public string? FirstSeen { get; init; }

    public string? Ean { get; init; }

    /// <summary>How the EAN was resolved: "upcitemdb", "shopify:{host}", "not_found".</summary>
    public string? EanSource { get; init; }

    public string? Sku { get; init; }
    public string? ProductCode { get; init; }
    public decimal? PriceGbp { get; init; }
    public decimal? PriceUsd { get; init; }
    public decimal? PriceEur { get; init; }
    public string? Url { get; init; }
    public string? ImageUrl { get; init; }
    public string? ReleaseDate { get; init; }
    public string? Description { get; init; }
    public List<ProductUnit>? Contents { get; init; }
}
```

Edit `tools/WarHub.ProductCatalog.Tool/Models/FactionCatalog.cs` — remove the `ProductCount` line:

```csharp
namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>
/// Per-faction output model containing all products for a manufacturer/game system/faction.
/// </summary>
public record FactionCatalog
{
    public required string Manufacturer { get; init; }
    public required string ManufacturerSlug { get; init; }
    public required string GameSystem { get; init; }
    public required string GameSystemSlug { get; init; }
    public required string Faction { get; init; }
    public required string FactionSlug { get; init; }
    public required List<Product> Products { get; init; }
}
```

Edit `tools/WarHub.ProductCatalog.Tool/Models/Manifest.cs` — remove all `ProductCount`/`TotalProducts` properties, leaving structure only:

```csharp
namespace WarHub.ProductCatalog.Tool.Models;

/// <summary>Manifest listing the catalog's manufacturers → game systems → factions.</summary>
public record Manifest
{
    public required string ToolVersion { get; init; }
    public required IReadOnlyList<ManufacturerSummary> Manufacturers { get; init; }
}

public record ManufacturerSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required IReadOnlyList<GameSystemSummary> GameSystems { get; init; }
}

public record GameSystemSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
    public required IReadOnlyList<FactionSummary> Factions { get; init; }
}

public record FactionSummary
{
    public required string Name { get; init; }
    public required string Slug { get; init; }
}
```

- [ ] **Step 4: Run the model test (tool project will still fail to build elsewhere)**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~ProductSchemaTests"`
Expected: The three `ProductSchemaTests` compile and pass **once** Tasks 8–11 fix the remaining call sites. If the tool project does not yet build, proceed to Task 8 before running; this test is validated at the end of Task 11.

> **Note:** Tasks 7–11 form one compilation unit (the model change cascades). Commit at the end of Task 7 even though the full solution does not build yet — the sub-agent executing Task 8 continues immediately. Do not run the whole solution build until Task 11.

- [ ] **Step 5: Commit**

```bash
git add tools/WarHub.ProductCatalog.Tool/Models tools/WarHub.ProductCatalog.Tool.Tests/Models/ProductSchemaTests.cs
git commit -m "feat(products): add category/packaging/firstSeen, drop productType and counts"
```

---

## Task 8: Category/packaging classifier

**Files:**
- Create: `tools/WarHub.ProductCatalog.Tool/Enrichment/CategoryClassifier.cs`
- Modify: `tools/WarHub.ProductCatalog.Tool/Enrichment/ProductEnricher.cs`
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Enrichment/CategoryClassifierTests.cs`

**Interfaces:**
- Consumes: `RawProduct`, `Product` (Task 7).
- Produces:
  - `static (string Category, string Packaging) CategoryClassifier.Classify(RawProduct raw)`.
  - `ProductEnricher.Enrich` now sets `Category` + `Packaging` (from the classifier) and `Status`; it no longer sets `ProductType`. `FirstSeen` is left null here (the reconciler stamps it).
- Category vocabulary: `miniatures | terrain | accessory | paint | book | tool`. Packaging vocabulary: `single | bundle | box | starter`.
- Mapping from the old heuristics: `terrain`→(terrain, single); `book`→(book, single); `paint_set`→(paint, bundle); `combat_patrol`/`battleforce`/`army_box`/`box_set`→(miniatures, box); `starter_set`→(miniatures, starter); `character`/`single_kit`/`unknown`→(miniatures, single).

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.ProductCatalog.Tool.Tests/Enrichment/CategoryClassifierTests.cs`:

```csharp
using WarHub.ProductCatalog.Tool.Enrichment;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class CategoryClassifierTests
{
    private static RawProduct Raw(string name, decimal? gbp = null, List<ProductUnit>? contents = null) => new()
    {
        Name = name,
        Manufacturer = "Games Workshop",
        GameSystem = "Warhammer 40,000",
        PriceGbp = gbp,
        Contents = contents,
    };

    [Theory]
    [InlineData("Battlefield Terrain Set", "terrain", "single")]
    [InlineData("Codex: Space Marines", "book", "single")]
    [InlineData("Combat Patrol: Necrons", "miniatures", "box")]
    [InlineData("Battleforce: Cities of Sigmar", "miniatures", "box")]
    [InlineData("Starter Set", "miniatures", "starter")]
    [InlineData("Paint Set: Base", "paint", "bundle")]
    [InlineData("Intercessors", "miniatures", "single")]
    public void Classify_MapsToCategoryAndPackaging(string name, string category, string packaging)
    {
        var (cat, pack) = CategoryClassifier.Classify(Raw(name));
        Assert.Equal(category, cat);
        Assert.Equal(packaging, pack);
    }

    [Fact]
    public void Classify_HighPricedItem_IsBoxMiniatures()
    {
        var (cat, pack) = CategoryClassifier.Classify(Raw("Big Kit", gbp: 150m));
        Assert.Equal("miniatures", cat);
        Assert.Equal("box", pack);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~CategoryClassifierTests"`
Expected: FAIL — `CategoryClassifier` does not exist.

- [ ] **Step 3: Write the classifier**

Create `tools/WarHub.ProductCatalog.Tool/Enrichment/CategoryClassifier.cs`:

```csharp
using WarHub.ProductCatalog.Tool.Configuration;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Classifies a raw product into the two orthogonal axes:
/// category (what it is) and packaging (how it is sold).
/// </summary>
public static class CategoryClassifier
{
    public static (string Category, string Packaging) Classify(RawProduct raw)
    {
        string legacyType = ProductEnricher.ClassifyProductType(raw);
        return legacyType switch
        {
            "terrain" => ("terrain", "single"),
            "book" => ("book", "single"),
            "paint_set" => ("paint", "bundle"),
            "combat_patrol" or "battleforce" or "army_box" or "box_set" => ("miniatures", "box"),
            "starter_set" => ("miniatures", "starter"),
            _ => ("miniatures", "single"),
        };
    }
}
```

- [ ] **Step 4: Update `ProductEnricher.Enrich`**

In `tools/WarHub.ProductCatalog.Tool/Enrichment/ProductEnricher.cs`, replace the body of `Enrich` (the `productType` line and the `new Product { ... }` initializer) with:

```csharp
    public static Product Enrich(RawProduct raw)
    {
        var (category, packaging) = CategoryClassifier.Classify(raw);
        string status = ManufacturerRegistry.NormalizeStatus(raw.Status);

        return new Product
        {
            Name = raw.Name.Trim(),
            Category = category,
            Packaging = packaging,
            Status = status,
            FirstSeen = null, // stamped by the reconciler
            Ean = raw.Ean?.Trim(),
            Sku = raw.Sku?.Trim(),
            ProductCode = raw.ProductCode?.Trim(),
            PriceGbp = RoundPrice(raw.PriceGbp),
            PriceUsd = RoundPrice(raw.PriceUsd),
            PriceEur = RoundPrice(raw.PriceEur),
            Url = raw.Url?.Trim(),
            ImageUrl = raw.ImageUrl?.Trim(),
            ReleaseDate = raw.ReleaseDate?.Trim(),
            Description = raw.Description?.Trim(),
            Contents = raw.Contents,
        };
    }
```

Keep the existing `ClassifyProductType` method (now `internal`, called by `CategoryClassifier`). Ensure it is at least `internal static`.

- [ ] **Step 5: Run test to verify it passes**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~CategoryClassifierTests"`
Expected: PASS. (Full tool build still pending Task 10.)

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.ProductCatalog.Tool/Enrichment/CategoryClassifier.cs tools/WarHub.ProductCatalog.Tool/Enrichment/ProductEnricher.cs tools/WarHub.ProductCatalog.Tool.Tests/Enrichment/CategoryClassifierTests.cs
git commit -m "feat(products): classify category + packaging axes"
```

---

## Task 9: `ProductRecordAdapter`

**Files:**
- Create: `tools/WarHub.ProductCatalog.Tool/Reconcile/ProductRecordAdapter.cs`
- Modify: `tools/WarHub.ProductCatalog.Tool/WarHub.ProductCatalog.Tool.csproj` (add ProjectReference to CatalogStore)
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Reconcile/ProductRecordAdapterTests.cs`

**Interfaces:**
- Consumes: `ICatalogRecordAdapter<T>`, `NameNormalizer` (Tasks 2, 6); `Product` (Task 7).
- Produces: `class ProductRecordAdapter : ICatalogRecordAdapter<Product>` implementing all six members with product-specific merge rules (update-present/keep-on-empty for `Ean`, `EanSource`, `PriceGbp/Usd/Eur`, `Url`, `ImageUrl`, `ReleaseDate`, `Description`, `Contents`, `Status`, `Sku`, `ProductCode`; immutable `Name` identity, `FirstSeen`, `Category`).

- [ ] **Step 1: Add the project reference**

In `tools/WarHub.ProductCatalog.Tool/WarHub.ProductCatalog.Tool.csproj`, add:

```xml
  <ItemGroup>
    <ProjectReference Include="..\WarHub.CatalogStore\WarHub.CatalogStore.csproj" />
  </ItemGroup>
```

- [ ] **Step 2: Write the failing test**

Create `tools/WarHub.ProductCatalog.Tool.Tests/Reconcile/ProductRecordAdapterTests.cs`:

```csharp
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Reconcile;

namespace WarHub.ProductCatalog.Tool.Tests.Reconcile;

public class ProductRecordAdapterTests
{
    private static Product P(string name, string? ean = null, decimal? usd = null, string? desc = null,
        string? firstSeen = null, string? url = null, string status = "current") => new()
    {
        Name = name, Category = "miniatures", Packaging = "single", Status = status,
        FirstSeen = firstSeen, Ean = ean, PriceUsd = usd, Description = desc, Url = url,
    };

    private readonly ProductRecordAdapter _adapter = new();

    [Fact]
    public void IdentityKey_IsNormalizedName()
    {
        Assert.Equal("space marines", _adapter.IdentityKey(P("  Space  Marines ")));
    }

    [Fact]
    public void Merge_UpdatesPresentField()
    {
        Product merged = _adapter.Merge(P("A", usd: 10m), P("A", usd: 12m));
        Assert.Equal(12m, merged.PriceUsd);
    }

    [Fact]
    public void Merge_KeepsArchivedValueWhenFreshIsEmpty()
    {
        Product merged = _adapter.Merge(P("A", ean: "0123", desc: "kept"), P("A", ean: null, desc: null));
        Assert.Equal("0123", merged.Ean);
        Assert.Equal("kept", merged.Description);
    }

    [Fact]
    public void Merge_PreservesFirstSeenAndCategory()
    {
        Product existing = P("A", firstSeen: "2020-01-01") with { Category = "terrain" };
        Product merged = _adapter.Merge(existing, P("A") with { Category = "miniatures" });
        Assert.Equal("2020-01-01", merged.FirstSeen);
        Assert.Equal("terrain", merged.Category);
    }

    [Fact]
    public void WithFirstSeen_StampsDate()
    {
        Assert.Equal("2026-07-07", _adapter.WithFirstSeen(P("A"), "2026-07-07").FirstSeen);
    }

    [Fact]
    public void HasFirstSeen_ReflectsPresence()
    {
        Assert.False(_adapter.HasFirstSeen(P("A")));
        Assert.True(_adapter.HasFirstSeen(P("A", firstSeen: "2020-01-01")));
    }

    [Fact]
    public void ApplyRename_AdoptsNewNameKeepsIdentity()
    {
        Product existing = P("Old", firstSeen: "2020-01-01", url: "http://x/1");
        Product renamed = _adapter.ApplyRename(existing, P("New", usd: 5m, url: "http://x/1"));
        Assert.Equal("New", renamed.Name);
        Assert.Equal("2020-01-01", renamed.FirstSeen);
        Assert.Equal(5m, renamed.PriceUsd);
    }
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~ProductRecordAdapterTests"`
Expected: FAIL — `ProductRecordAdapter` does not exist.

- [ ] **Step 4: Write the adapter**

Create `tools/WarHub.ProductCatalog.Tool/Reconcile/ProductRecordAdapter.cs`:

```csharp
using WarHub.CatalogStore;
using WarHub.CatalogStore.Reconcile;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Reconcile;

/// <summary>Adapts <see cref="Product"/> to the generic reconciler.</summary>
public sealed class ProductRecordAdapter : ICatalogRecordAdapter<Product>
{
    public string IdentityKey(Product record) => NameNormalizer.Normalize(record.Name);

    public string? Url(Product record) => string.IsNullOrWhiteSpace(record.Url) ? null : record.Url;

    public Product Merge(Product existing, Product fresh) => existing with
    {
        // Identity, firstSeen, and category are immutable across merges.
        Ean = Pick(fresh.Ean, existing.Ean),
        EanSource = Pick(fresh.EanSource, existing.EanSource),
        Sku = Pick(fresh.Sku, existing.Sku),
        ProductCode = Pick(fresh.ProductCode, existing.ProductCode),
        Packaging = string.IsNullOrWhiteSpace(fresh.Packaging) ? existing.Packaging : fresh.Packaging,
        Status = string.IsNullOrWhiteSpace(fresh.Status) ? existing.Status : fresh.Status,
        PriceGbp = fresh.PriceGbp ?? existing.PriceGbp,
        PriceUsd = fresh.PriceUsd ?? existing.PriceUsd,
        PriceEur = fresh.PriceEur ?? existing.PriceEur,
        Url = Pick(fresh.Url, existing.Url),
        ImageUrl = Pick(fresh.ImageUrl, existing.ImageUrl),
        ReleaseDate = Pick(fresh.ReleaseDate, existing.ReleaseDate),
        Description = Pick(fresh.Description, existing.Description),
        Contents = fresh.Contents is { Count: > 0 } ? fresh.Contents : existing.Contents,
    };

    public Product WithFirstSeen(Product record, string isoDate) => record with { FirstSeen = isoDate };

    public bool HasFirstSeen(Product record) => !string.IsNullOrWhiteSpace(record.FirstSeen);

    public Product ApplyRename(Product existing, Product fresh) =>
        Merge(existing, fresh) with { Name = fresh.Name };

    private static string? Pick(string? fresh, string? existing) =>
        string.IsNullOrWhiteSpace(fresh) ? existing : fresh;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~ProductRecordAdapterTests"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.ProductCatalog.Tool/Reconcile tools/WarHub.ProductCatalog.Tool/WarHub.ProductCatalog.Tool.csproj tools/WarHub.ProductCatalog.Tool.Tests/Reconcile/ProductRecordAdapterTests.cs
git commit -m "feat(products): add ProductRecordAdapter with merge rules"
```

---

## Task 10: Rewire writer + Program to reconcile instead of overwrite

**Files:**
- Modify: `tools/WarHub.ProductCatalog.Tool/Output/YamlCatalogWriter.cs`
- Modify: `tools/WarHub.ProductCatalog.Tool/Program.cs`
- Modify: `tools/WarHub.ProductCatalog.Tool/Enrichment/ExistingCatalogLoader.cs` (deserializer swap only)
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Output/YamlCatalogWriterTests.cs`

**Interfaces:**
- Consumes: `CatalogSerializer`, `CatalogReconciler<Product>`, `ProductRecordAdapter`, `LedgerStore`, `LivenessUpdater` (Tasks 3–6, 9).
- Produces: `YamlCatalogWriter` uses `CatalogSerializer.CreateSerializer()` and no longer writes `ProductCount`; `Program.cs` reconciles each faction against the on-disk archive, updates the ledger at `data/products/_liveness.yaml`, applies flag/reactivation status changes, and writes deterministically.

- [ ] **Step 1: Write the failing writer test**

Create `tools/WarHub.ProductCatalog.Tool.Tests/Output/YamlCatalogWriterTests.cs`:

```csharp
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;

namespace WarHub.ProductCatalog.Tool.Tests.Output;

public class YamlCatalogWriterTests
{
    private static FactionCatalog Catalog(params Product[] products) => new()
    {
        Manufacturer = "CMON", ManufacturerSlug = "cmon",
        GameSystem = "ASOIAF", GameSystemSlug = "asoiaf",
        Faction = "Baratheon", FactionSlug = "baratheon",
        Products = products.ToList(),
    };

    private static Product P(string name, string? ean) => new()
    {
        Name = name, Category = "miniatures", Packaging = "single",
        Status = "current", FirstSeen = "2026-07-07", Ean = ean,
    };

    [Fact]
    public async Task Write_QuotesEanAndOmitsProductCount()
    {
        string dir = Path.Combine(Path.GetTempPath(), $"cat-{Guid.NewGuid():N}");
        try
        {
            await YamlCatalogWriter.WriteFactionAsync(Catalog(P("Wardens", "0889696010223")), dir);
            string file = Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml");
            string yaml = await File.ReadAllTextAsync(file);

            Assert.Contains("ean: '0889696010223'", yaml);
            Assert.DoesNotContain("productCount", yaml);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task Write_IsByteIdenticalForSameInput()
    {
        string dir = Path.Combine(Path.GetTempPath(), $"cat-{Guid.NewGuid():N}");
        try
        {
            FactionCatalog c = Catalog(P("Wardens", "1"), P("Halberdiers", "2"));
            await YamlCatalogWriter.WriteFactionAsync(c, dir);
            string file = Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml");
            string first = await File.ReadAllTextAsync(file);

            await YamlCatalogWriter.WriteFactionAsync(c, dir);
            string second = await File.ReadAllTextAsync(file);

            Assert.Equal(first, second);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~YamlCatalogWriterTests"`
Expected: FAIL — `productCount` still emitted / EAN unquoted (writer not yet swapped).

- [ ] **Step 3: Rewrite the writer to use the shared serializer**

Replace `tools/WarHub.ProductCatalog.Tool/Output/YamlCatalogWriter.cs` with:

```csharp
using WarHub.CatalogStore;
using WarHub.ProductCatalog.Tool.Models;

namespace WarHub.ProductCatalog.Tool.Output;

/// <summary>Writes faction catalog YAML files and the manifest using the shared serializer.</summary>
public static class YamlCatalogWriter
{
    private static readonly YamlDotNet.Serialization.ISerializer Serializer = CatalogSerializer.CreateSerializer();

    public static async Task WriteFactionAsync(FactionCatalog catalog, string outputDir)
    {
        string dir = Path.Combine(outputDir, "manufacturers", catalog.ManufacturerSlug, catalog.GameSystemSlug);
        Directory.CreateDirectory(dir);

        string filePath = Path.Combine(dir, $"{catalog.FactionSlug}.yaml");
        await File.WriteAllTextAsync(filePath, Serializer.Serialize(catalog));
    }

    public static async Task WriteManifestAsync(Manifest manifest, string outputDir)
    {
        Directory.CreateDirectory(outputDir);
        string filePath = Path.Combine(outputDir, "manifest.yaml");
        await File.WriteAllTextAsync(filePath, Serializer.Serialize(manifest));
    }
}
```

- [ ] **Step 4: Point `ExistingCatalogLoader` at the shared deserializer**

In `tools/WarHub.ProductCatalog.Tool/Enrichment/ExistingCatalogLoader.cs`, replace the `YamlDeserializer` field initialization with the shared one:

```csharp
using WarHub.CatalogStore;
// ...
    private static readonly IDeserializer YamlDeserializer = CatalogSerializer.CreateDeserializer();
```

(Remove the now-unused `DeserializerBuilder`/`CamelCaseNamingConvention` usings if the compiler flags them.)

- [ ] **Step 5: Rewrite the Program grouping/write loop**

In `tools/WarHub.ProductCatalog.Tool/Program.cs`, replace the entire `foreach (var group in grouped)` loop body's **write section** and the manifest build. Specifically:

Replace the block from `// Write faction catalog` through `await YamlCatalogWriter.WriteFactionAsync(catalog, outputDir);` (lines ~415–429) with:

```csharp
        // Reconcile fresh scrape against the archived faction file (append-only).
        string factionPath = Path.Combine(outputDir, "manufacturers", mfgSlug, gsSlug, $"{factionSlug}.yaml");
        IReadOnlyList<Product> existingProducts = await LoadExistingFactionProductsAsync(factionPath, cancellationToken);

        var adapter = new ProductRecordAdapter();
        var reconciler = new CatalogReconciler<Product>(adapter);
        (IReadOnlyDictionary<string, string> aliases, ISet<string> retracted) =
            OverrideAliases.Load(overridesPath, mfgSlug, gsSlug, factionSlug);

        ReconcileResult<Product> reconciled = reconciler.Reconcile(
            existingProducts, enriched.ToList(), aliases, retracted, today);

        // Ledger update (per faction contributes to a per-manufacturer source entry).
        string sourceKey = mfgSlug;
        var seenLedgerKeys = reconciled.SeenKeys
            .Select(k => $"{mfgSlug}/{gsSlug}/{factionSlug}/{k}").ToHashSet(StringComparer.Ordinal);
        var knownLedgerKeys = reconciled.Records
            .Select(p => $"{mfgSlug}/{gsSlug}/{factionSlug}/{adapter.IdentityKey(p)}").ToList();
        var currentlyFlagged = reconciled.Records
            .Where(p => p.Status == "suspected-discontinued")
            .Select(p => $"{mfgSlug}/{gsSlug}/{factionSlug}/{adapter.IdentityKey(p)}")
            .ToHashSet(StringComparer.Ordinal);

        LivenessUpdate live = LivenessUpdater.Apply(
            ledger, sourceKey, sourceSucceeded: sourceHealthy, scrapedCount: enriched.Count,
            seenKeys: seenLedgerKeys, knownKeysForSource: knownLedgerKeys,
            today: today, currentlyFlaggedKeys: currentlyFlagged);
        ledger = live.Ledger;

        // Apply auto-flag / reactivation status transitions onto the records.
        var finalProducts = reconciled.Records.Select(p =>
        {
            string lk = $"{mfgSlug}/{gsSlug}/{factionSlug}/{adapter.IdentityKey(p)}";
            if (live.Flagged.Contains(lk) && p.Status == "current")
                return p with { Status = "suspected-discontinued" };
            if (live.Reactivated.Contains(lk) && p.Status == "suspected-discontinued")
                return p with { Status = "current" };
            return p;
        }).ToList();

        var catalog = new FactionCatalog
        {
            Manufacturer = mfgName,
            ManufacturerSlug = mfgSlug,
            GameSystem = gsName,
            GameSystemSlug = gsSlug,
            Faction = factionName,
            FactionSlug = factionSlug,
            Products = finalProducts,
        };

        await YamlCatalogWriter.WriteFactionAsync(catalog, outputDir);
```

Add, immediately before the `foreach (var group in grouped)` loop:

```csharp
    string today = DateTime.UtcNow.ToString("yyyy-MM-dd");
    string ledgerPath = Path.Combine(outputDir, "_liveness.yaml");
    LivenessLedger ledger = await LedgerStore.LoadAsync(ledgerPath, cancellationToken);
    // A source is healthy when its scrape produced any products; scrapers that threw
    // above leave allRawProducts empty for that source. Per-source success is tracked
    // by whether the manufacturer produced any grouped products this run.
    var healthyManufacturers = grouped
        .Where(g => g.Any())
        .Select(g => ManufacturerRegistry.GetManufacturer(g.Key.Manufacturer)?.Slug
            ?? ManufacturerRegistry.Slugify(g.Key.Manufacturer))
        .ToHashSet(StringComparer.OrdinalIgnoreCase);
```

Inside the loop, before the reconcile block, add:

```csharp
        bool sourceHealthy = healthyManufacturers.Contains(mfgSlug);
```

After the loop, replace the manifest build's count-bearing initializers so they no longer set `ProductCount`/`TotalProducts` (remove those property assignments from `Manifest`, `ManufacturerSummary`, `GameSystemSummary`, `FactionSummary`), and after `await YamlCatalogWriter.WriteManifestAsync(manifest, outputDir);` add:

```csharp
    await LedgerStore.SaveAsync(ledgerPath, ledger, cancellationToken);
```

Add these usings at the top of `Program.cs`:

```csharp
using WarHub.CatalogStore.Ledger;
using WarHub.CatalogStore.Reconcile;
using WarHub.ProductCatalog.Tool.Reconcile;
```

Add a helper method alongside the other static helpers in `Program.cs`:

```csharp
static async Task<IReadOnlyList<Product>> LoadExistingFactionProductsAsync(string factionPath, CancellationToken ct)
{
    if (!File.Exists(factionPath))
        return [];
    string yaml = await File.ReadAllTextAsync(factionPath, ct);
    FactionCatalog? catalog = CatalogSerializer.CreateDeserializer().Deserialize<FactionCatalog>(yaml);
    return catalog?.Products ?? [];
}
```

> **Remove** the now-dead `existingEanLookup`/`MergeExistingEans` preservation path only if it is fully superseded. The EAN enrichment sources (`ApplyShopifyEans`, `eanEnricher`) still run on `enriched` **before** reconciliation — keep them. `MergeExistingEans` becomes redundant (reconciliation now preserves EANs); delete the call at the old line ~404–405 and the `MergeExistingEans` method. Keep `LoadExistingCatalogDataAsync` for its `catalogSkus` return (still used for Shopify filtering); if only the EAN half is now unused, keep the method but ignore the EAN dictionary.

- [ ] **Step 6: Create the `OverrideAliases` loader (referenced above)**

This is implemented and tested in Task 11. For this task to compile, add a temporary minimal stub if executing Task 10 before Task 11:

```csharp
// tools/WarHub.ProductCatalog.Tool/Enrichment/OverrideAliases.cs (finalized in Task 11)
namespace WarHub.ProductCatalog.Tool.Enrichment;

public static class OverrideAliases
{
    public static (IReadOnlyDictionary<string, string> Aliases, ISet<string> Retracted) Load(
        string? overridesPath, string mfgSlug, string gsSlug, string factionSlug)
        => (new Dictionary<string, string>(), new HashSet<string>());
}
```

Add `using WarHub.ProductCatalog.Tool.Enrichment;` to `Program.cs` if not present.

- [ ] **Step 7: Build the tool and run the writer test**

Run: `dotnet build tools/WarHub.ProductCatalog.Tool && dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~YamlCatalogWriterTests"`
Expected: build succeeds; `YamlCatalogWriterTests` PASS.

- [ ] **Step 8: Fix any remaining broken existing tests**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests`
Expected: any test referencing `ProductType`/`ProductCount` fails to compile. Update those tests to use `Category`/`Packaging` and drop count assertions. Re-run until green.

- [ ] **Step 9: Commit**

```bash
git add tools/WarHub.ProductCatalog.Tool tools/WarHub.ProductCatalog.Tool.Tests
git commit -m "feat(products): reconcile against archive instead of overwriting"
```

---

## Task 11: Overrides — aliases + retract

**Files:**
- Modify: `tools/WarHub.ProductCatalog.Tool/Enrichment/OverrideAliases.cs` (finalize the Task 10 stub)
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Enrichment/OverrideAliasesTests.cs`

**Interfaces:**
- Consumes: `CatalogSerializer`, `NameNormalizer`.
- Produces: `static (IReadOnlyDictionary<string,string> Aliases, ISet<string> Retracted) OverrideAliases.Load(string? overridesPath, string mfgSlug, string gsSlug, string factionSlug)`.
- Override file shape (extends existing `overrides.yaml`):

```yaml
aliases:
  cmon/asoiaf/baratheon:
    "new normalized name": "Old Display Name"   # newKey -> old display name
retract:
  cmon/asoiaf/baratheon:
    - "Bad Product Name"
```

`Aliases` maps normalized-new-name → normalized-old-name (both normalized via `NameNormalizer`). `Retracted` is the set of normalized names to drop for that faction path.

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.ProductCatalog.Tool.Tests/Enrichment/OverrideAliasesTests.cs`:

```csharp
using WarHub.ProductCatalog.Tool.Enrichment;

namespace WarHub.ProductCatalog.Tool.Tests.Enrichment;

public class OverrideAliasesTests
{
    private static string Temp(string content)
    {
        string p = Path.Combine(Path.GetTempPath(), $"ov-{Guid.NewGuid():N}.yaml");
        File.WriteAllText(p, content);
        return p;
    }

    [Fact]
    public void Load_NullPath_ReturnsEmpty()
    {
        var (aliases, retracted) = OverrideAliases.Load(null, "cmon", "asoiaf", "baratheon");
        Assert.Empty(aliases);
        Assert.Empty(retracted);
    }

    [Fact]
    public void Load_AliasesAndRetract_AreNormalizedAndScoped()
    {
        string file = Temp("""
            aliases:
              cmon/asoiaf/baratheon:
                "New Name": "Old Name"
            retract:
              cmon/asoiaf/baratheon:
                - "Bad Product"
            """);
        try
        {
            var (aliases, retracted) = OverrideAliases.Load(file, "cmon", "asoiaf", "baratheon");
            Assert.Equal("old name", aliases["new name"]);
            Assert.Contains("bad product", retracted);
        }
        finally { File.Delete(file); }
    }

    [Fact]
    public void Load_DifferentFaction_IsNotApplied()
    {
        string file = Temp("""
            retract:
              cmon/asoiaf/lannister:
                - "Bad Product"
            """);
        try
        {
            var (_, retracted) = OverrideAliases.Load(file, "cmon", "asoiaf", "baratheon");
            Assert.Empty(retracted);
        }
        finally { File.Delete(file); }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~OverrideAliasesTests"`
Expected: FAIL — stub returns empty for the populated cases.

- [ ] **Step 3: Finalize the implementation**

Replace `tools/WarHub.ProductCatalog.Tool/Enrichment/OverrideAliases.cs` with:

```csharp
using WarHub.CatalogStore;

namespace WarHub.ProductCatalog.Tool.Enrichment;

/// <summary>
/// Loads rename aliases and retractions from overrides.yaml, scoped to one
/// faction path (mfgSlug/gsSlug/factionSlug). Names are normalized to match
/// reconciler identity keys.
/// </summary>
public static class OverrideAliases
{
    private sealed class OverridesFile
    {
        public Dictionary<string, Dictionary<string, string>>? Aliases { get; init; }
        public Dictionary<string, List<string>>? Retract { get; init; }
    }

    public static (IReadOnlyDictionary<string, string> Aliases, ISet<string> Retracted) Load(
        string? overridesPath, string mfgSlug, string gsSlug, string factionSlug)
    {
        var aliases = new Dictionary<string, string>(StringComparer.Ordinal);
        var retracted = new HashSet<string>(StringComparer.Ordinal);

        if (string.IsNullOrWhiteSpace(overridesPath) || !File.Exists(overridesPath))
            return (aliases, retracted);

        string scope = $"{mfgSlug}/{gsSlug}/{factionSlug}";
        OverridesFile? parsed = CatalogSerializer.CreateDeserializer()
            .Deserialize<OverridesFile>(File.ReadAllText(overridesPath));
        if (parsed is null)
            return (aliases, retracted);

        if (parsed.Aliases is not null && parsed.Aliases.TryGetValue(scope, out var scopedAliases))
            foreach (var (newName, oldName) in scopedAliases)
                aliases[NameNormalizer.Normalize(newName)] = NameNormalizer.Normalize(oldName);

        if (parsed.Retract is not null && parsed.Retract.TryGetValue(scope, out var scopedRetract))
            foreach (string name in scopedRetract)
                retracted.Add(NameNormalizer.Normalize(name));

        return (aliases, retracted);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~OverrideAliasesTests"`
Expected: PASS.

- [ ] **Step 5: Verify the whole solution builds and all product/store tests pass**

Run: `dotnet test WarHub.Catalog.slnx --filter "FullyQualifiedName~CatalogStore|FullyQualifiedName~ProductCatalog"`
Expected: build succeeds; all pass. Now run the `ProductSchemaTests` deferred from Task 7 — they pass.

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.ProductCatalog.Tool/Enrichment/OverrideAliases.cs tools/WarHub.ProductCatalog.Tool.Tests/Enrichment/OverrideAliasesTests.cs
git commit -m "feat(products): support alias renames and retractions in overrides"
```

---

## Task 12: Product data migration command

**Files:**
- Create: `tools/WarHub.ProductCatalog.Tool/Migration/ProductMigrator.cs`
- Modify: `tools/WarHub.ProductCatalog.Tool/Program.cs` (add `migrate` subcommand)
- Test: `tools/WarHub.ProductCatalog.Tool.Tests/Migration/ProductMigratorTests.cs`

**Interfaces:**
- Consumes: `CatalogSerializer`, `YamlCatalogWriter`, `LedgerStore` (Tasks 3, 4, 10).
- Produces:
  - `static async Task<int> ProductMigrator.MigrateAsync(string dataDir, string migrationDate, CancellationToken ct)` — rewrites every faction file into the new schema (quote EANs, map legacy `productType`→`category`/`packaging`, backfill `firstSeen`, drop counts, re-sort, re-serialize), and seeds `_liveness.yaml`. Idempotent: a second run produces zero changes.
- Legacy read model tolerates old fields (`productType`, `productCount`) via `IgnoreUnmatchedProperties`.

- [ ] **Step 1: Write the failing test**

Create `tools/WarHub.ProductCatalog.Tool.Tests/Migration/ProductMigratorTests.cs`:

```csharp
using WarHub.ProductCatalog.Tool.Migration;

namespace WarHub.ProductCatalog.Tool.Tests.Migration;

public class ProductMigratorTests
{
    private static string SeedLegacyTree()
    {
        string dir = Path.Combine(Path.GetTempPath(), $"mig-{Guid.NewGuid():N}");
        string factionDir = Path.Combine(dir, "manufacturers", "cmon", "asoiaf");
        Directory.CreateDirectory(factionDir);
        File.WriteAllText(Path.Combine(factionDir, "baratheon.yaml"), """
            manufacturer: CMON
            manufacturerSlug: cmon
            gameSystem: ASOIAF
            gameSystemSlug: asoiaf
            faction: Baratheon
            factionSlug: baratheon
            productCount: 2
            products:
            - name: 'Baratheon: Wardens'
              productType: single_kit
              ean: 889696010223
              status: current
            - name: 'Baratheon: Terrain Pack'
              productType: terrain
              status: current
            """);
        return dir;
    }

    [Fact]
    public async Task Migrate_TransformsSchema_AndQuotesEan()
    {
        string dir = SeedLegacyTree();
        try
        {
            await ProductMigrator.MigrateAsync(dir, "2026-07-07", default);
            string yaml = await File.ReadAllTextAsync(
                Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml"));

            Assert.Contains("ean: '889696010223'", yaml);
            Assert.Contains("category: miniatures", yaml);
            Assert.Contains("packaging: single", yaml);
            Assert.Contains("category: terrain", yaml);
            Assert.Contains("firstSeen: '2026-07-07'", yaml);
            Assert.DoesNotContain("productType", yaml);
            Assert.DoesNotContain("productCount", yaml);
            Assert.True(File.Exists(Path.Combine(dir, "_liveness.yaml")));
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public async Task Migrate_IsIdempotent()
    {
        string dir = SeedLegacyTree();
        try
        {
            await ProductMigrator.MigrateAsync(dir, "2026-07-07", default);
            string file = Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml");
            string first = await File.ReadAllTextAsync(file);

            await ProductMigrator.MigrateAsync(dir, "2099-01-01", default); // different date must NOT change firstSeen
            string second = await File.ReadAllTextAsync(file);

            Assert.Equal(first, second);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~ProductMigratorTests"`
Expected: FAIL — `ProductMigrator` does not exist.

- [ ] **Step 3: Write the migrator**

Create `tools/WarHub.ProductCatalog.Tool/Migration/ProductMigrator.cs`:

```csharp
using WarHub.CatalogStore;
using WarHub.CatalogStore.Ledger;
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;

namespace WarHub.ProductCatalog.Tool.Migration;

/// <summary>
/// One-time, idempotent migration of legacy faction files into the new schema.
/// Backfills firstSeen only when absent, so re-running never changes existing dates.
/// </summary>
public static class ProductMigrator
{
    // Legacy shape tolerant of old fields.
    private sealed record LegacyCatalog
    {
        public string Manufacturer { get; init; } = "";
        public string ManufacturerSlug { get; init; } = "";
        public string GameSystem { get; init; } = "";
        public string GameSystemSlug { get; init; } = "";
        public string Faction { get; init; } = "";
        public string FactionSlug { get; init; } = "";
        public List<LegacyProduct> Products { get; init; } = new();
    }

    private sealed record LegacyProduct
    {
        public string Name { get; init; } = "";
        public string? ProductType { get; init; }
        public string? Category { get; init; }
        public string? Packaging { get; init; }
        public string? Status { get; init; }
        public string? FirstSeen { get; init; }
        public string? Ean { get; init; }
        public string? EanSource { get; init; }
        public string? Sku { get; init; }
        public string? ProductCode { get; init; }
        public decimal? PriceGbp { get; init; }
        public decimal? PriceUsd { get; init; }
        public decimal? PriceEur { get; init; }
        public string? Url { get; init; }
        public string? ImageUrl { get; init; }
        public string? ReleaseDate { get; init; }
        public string? Description { get; init; }
        public List<ProductUnit>? Contents { get; init; }
    }

    public static async Task<int> MigrateAsync(string dataDir, string migrationDate, CancellationToken ct)
    {
        string manufacturersDir = Path.Combine(dataDir, "manufacturers");
        if (!Directory.Exists(manufacturersDir))
            return 0;

        var deserializer = CatalogSerializer.CreateDeserializer();
        var ledger = await LedgerStore.LoadAsync(Path.Combine(dataDir, "_liveness.yaml"), ct);

        foreach (string file in Directory.GetFiles(manufacturersDir, "*.yaml", SearchOption.AllDirectories).OrderBy(f => f))
        {
            ct.ThrowIfCancellationRequested();
            LegacyCatalog? legacy = deserializer.Deserialize<LegacyCatalog>(await File.ReadAllTextAsync(file, ct));
            if (legacy is null)
                continue;

            var products = legacy.Products.Select(lp =>
            {
                (string category, string packaging) = MapType(lp);
                string firstSeen = string.IsNullOrWhiteSpace(lp.FirstSeen) ? migrationDate : lp.FirstSeen!;
                var product = new Product
                {
                    Name = lp.Name,
                    Category = category,
                    Packaging = packaging,
                    Status = string.IsNullOrWhiteSpace(lp.Status) ? "current" : lp.Status!,
                    FirstSeen = firstSeen,
                    Ean = lp.Ean,
                    EanSource = lp.EanSource,
                    Sku = lp.Sku,
                    ProductCode = lp.ProductCode,
                    PriceGbp = lp.PriceGbp,
                    PriceUsd = lp.PriceUsd,
                    PriceEur = lp.PriceEur,
                    Url = lp.Url,
                    ImageUrl = lp.ImageUrl,
                    ReleaseDate = lp.ReleaseDate,
                    Description = lp.Description,
                    Contents = lp.Contents,
                };

                string ledgerKey = $"{legacy.ManufacturerSlug}/{legacy.GameSystemSlug}/{legacy.FactionSlug}/{NameNormalizer.Normalize(lp.Name)}";
                ledger.Records[ledgerKey] = new LedgerRecord { LastSeen = migrationDate, MissStreak = 0 };
                return product;
            })
            .OrderBy(p => NameNormalizer.Normalize(p.Name), StringComparer.Ordinal)
            .ToList();

            var catalog = new FactionCatalog
            {
                Manufacturer = legacy.Manufacturer,
                ManufacturerSlug = legacy.ManufacturerSlug,
                GameSystem = legacy.GameSystem,
                GameSystemSlug = legacy.GameSystemSlug,
                Faction = legacy.Faction,
                FactionSlug = legacy.FactionSlug,
                Products = products,
            };

            await YamlCatalogWriter.WriteFactionAsync(catalog, dataDir);
        }

        await LedgerStore.SaveAsync(Path.Combine(dataDir, "_liveness.yaml"), ledger, ct);
        return 0;
    }

    private static (string Category, string Packaging) MapType(LegacyProduct lp)
    {
        // Already-migrated files keep their category/packaging (idempotency).
        if (!string.IsNullOrWhiteSpace(lp.Category) && !string.IsNullOrWhiteSpace(lp.Packaging))
            return (lp.Category!, lp.Packaging!);

        return lp.ProductType switch
        {
            "terrain" => ("terrain", "single"),
            "book" => ("book", "single"),
            "paint_set" => ("paint", "bundle"),
            "combat_patrol" or "battleforce" or "army_box" or "box_set" => ("miniatures", "box"),
            "starter_set" => ("miniatures", "starter"),
            _ => ("miniatures", "single"),
        };
    }
}
```

- [ ] **Step 4: Wire the `migrate` subcommand into `Program.cs`**

In `Program.cs`, after the root command is configured but before `rootCommand.Parse(args).Invoke();`, add a subcommand:

```csharp
var migrateCommand = new Command("migrate", "One-time migration of existing data to the new schema");
var migrateDirOption = new Option<string>("--data-dir") { Description = "Path to data/products", Required = true };
migrateCommand.Add(migrateDirOption);
migrateCommand.SetAction(async (parseResult, ct) =>
{
    string dir = parseResult.GetValue(migrateDirOption)!;
    string date = DateTime.UtcNow.ToString("yyyy-MM-dd");
    return await WarHub.ProductCatalog.Tool.Migration.ProductMigrator.MigrateAsync(dir, date, ct);
});
rootCommand.Add(migrateCommand);
```

> **Note:** Match the exact System.CommandLine 2.0.9 API already used in this `Program.cs` (option/action registration style). If the existing code uses a different option-construction pattern, mirror it.

- [ ] **Step 5: Run test to verify it passes**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~ProductMigratorTests"`
Expected: PASS (both transform and idempotency).

- [ ] **Step 6: Commit**

```bash
git add tools/WarHub.ProductCatalog.Tool/Migration tools/WarHub.ProductCatalog.Tool/Program.cs tools/WarHub.ProductCatalog.Tool.Tests/Migration/ProductMigratorTests.cs
git commit -m "feat(products): add idempotent product data migration command"
```

---

## Task 13: Run the migration on real data (one-time reformatting commit)

**Files:**
- Modify: everything under `data/products/manufacturers/**/*.yaml`
- Create: `data/products/_liveness.yaml`
- Delete: derived count fields (via migration)

**Interfaces:**
- Consumes: `ProductMigrator` (Task 12).

- [ ] **Step 1: Build the tool**

Run: `dotnet build tools/WarHub.ProductCatalog.Tool`
Expected: success.

- [ ] **Step 2: Run the migration against the repo data**

Run: `dotnet run --project tools/WarHub.ProductCatalog.Tool -- migrate --data-dir data/products`
Expected: exits 0. `git status` shows every faction file modified and `data/products/_liveness.yaml` created.

- [ ] **Step 3: Spot-check the diff**

Run: `git diff -- data/products/manufacturers/cmon/asoiaf/baratheon.yaml | head -60`
Expected: EANs now quoted; `category`/`packaging`/`firstSeen` present; no `productType`/`productCount`; products alphabetized by normalized name.

- [ ] **Step 4: Verify idempotency on real data**

Run: `dotnet run --project tools/WarHub.ProductCatalog.Tool -- migrate --data-dir data/products && git status --porcelain data/products | wc -l`
Expected: the second run adds **zero** new changes beyond step 2 (line count unchanged after re-running; `git diff` stable).

- [ ] **Step 5: Commit the one-time reformat**

```bash
git add data/products
git commit -m "chore(data): migrate product catalog to stable storage schema"
```

---

## Task 14: End-to-end stability verification

**Files:**
- Create: `tools/WarHub.ProductCatalog.Tool.Tests/Integration/ReconcileStabilityTests.cs`

**Interfaces:**
- Consumes: `CatalogReconciler<Product>`, `ProductRecordAdapter`, `YamlCatalogWriter` (Tasks 6, 9, 10).

- [ ] **Step 1: Write the end-to-end stability test**

Create `tools/WarHub.ProductCatalog.Tool.Tests/Integration/ReconcileStabilityTests.cs`:

```csharp
using WarHub.CatalogStore.Reconcile;
using WarHub.ProductCatalog.Tool.Models;
using WarHub.ProductCatalog.Tool.Output;
using WarHub.ProductCatalog.Tool.Reconcile;

namespace WarHub.ProductCatalog.Tool.Tests.Integration;

public class ReconcileStabilityTests
{
    private static Product P(string name, decimal? usd = null, string? firstSeen = "2026-07-07") => new()
    {
        Name = name, Category = "miniatures", Packaging = "single",
        Status = "current", FirstSeen = firstSeen, PriceUsd = usd,
    };

    [Fact]
    public async Task IdenticalRescrape_ProducesByteIdenticalFile()
    {
        var adapter = new ProductRecordAdapter();
        var reconciler = new CatalogReconciler<Product>(adapter);
        var noAliases = new Dictionary<string, string>();
        var noRetract = new HashSet<string>();

        var existing = new List<Product> { P("Wardens", 10m), P("Halberdiers", 20m) };
        var fresh = new List<Product> { P("Wardens", 10m, firstSeen: null), P("Halberdiers", 20m, firstSeen: null) };

        ReconcileResult<Product> r1 = reconciler.Reconcile(existing, fresh, noAliases, noRetract, "2026-07-07");
        ReconcileResult<Product> r2 = reconciler.Reconcile(r1.Records, fresh, noAliases, noRetract, "2026-07-08");

        string dir = Path.Combine(Path.GetTempPath(), $"stab-{Guid.NewGuid():N}");
        try
        {
            FactionCatalog Cat(IReadOnlyList<Product> p) => new()
            {
                Manufacturer = "CMON", ManufacturerSlug = "cmon",
                GameSystem = "ASOIAF", GameSystemSlug = "asoiaf",
                Faction = "Baratheon", FactionSlug = "baratheon",
                Products = p.ToList(),
            };
            await YamlCatalogWriter.WriteFactionAsync(Cat(r1.Records), dir);
            string first = await File.ReadAllTextAsync(Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml"));
            await YamlCatalogWriter.WriteFactionAsync(Cat(r2.Records), dir);
            string second = await File.ReadAllTextAsync(Path.Combine(dir, "manufacturers", "cmon", "asoiaf", "baratheon.yaml"));

            Assert.Equal(first, second);
        }
        finally { Directory.Delete(dir, recursive: true); }
    }

    [Fact]
    public void PartialScrape_KeepsAllRecords()
    {
        var reconciler = new CatalogReconciler<Product>(new ProductRecordAdapter());
        var existing = new List<Product> { P("A"), P("B"), P("C") };
        var fresh = new List<Product> { P("A") }; // B and C missing this run

        ReconcileResult<Product> result = reconciler.Reconcile(
            existing, fresh, new Dictionary<string, string>(), new HashSet<string>(), "2026-07-08");

        Assert.Equal(3, result.Records.Count);
    }
}
```

- [ ] **Step 2: Run the test**

Run: `dotnet test tools/WarHub.ProductCatalog.Tool.Tests --filter "FullyQualifiedName~ReconcileStabilityTests"`
Expected: PASS.

- [ ] **Step 3: Full solution test run**

Run: `dotnet test WarHub.Catalog.slnx`
Expected: all tests pass (publisher tests may need the follow-on Plan 3 if they assert on `productType`/counts — if they fail, note them for Plan 3 and confirm they are the only failures).

- [ ] **Step 4: Commit**

```bash
git add tools/WarHub.ProductCatalog.Tool.Tests/Integration/ReconcileStabilityTests.cs
git commit -m "test(products): end-to-end reconcile stability and no-drop guarantees"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Overwrite→archive reconciliation → Tasks 6, 9, 10, 14. ✅
- Composite name-key identity + normalization → Tasks 2, 9. ✅
- URL fallback + alias override + retract → Tasks 6, 11. ✅
- Update-present/keep-on-empty → Tasks 6, 9. ✅
- Never-drop / keep-on-missing → Tasks 6, 14. ✅
- `firstSeen` write-once + `status` in-record → Tasks 7, 9, 10. ✅
- Liveness ledger + source-health-gated auto-flag → Tasks 4, 5, 10. ✅
- EAN string quoting (fixes #5) → Task 3. ✅
- Drop denormalized counts + exploded date → Tasks 3, 4, 7. ✅
- Two-axis category/packaging → Tasks 7, 8. ✅
- Deterministic ordering + byte-identical contract → Tasks 6, 10, 14. ✅
- One-time idempotent migration → Tasks 12, 13. ✅
- Shared library serving both catalogs (Approach A) → Tasks 1–6 (product adoption 7–14; paints deferred to Plan 2). ✅
- **Deferred (explicitly out of this plan):** paint catalog adoption (Plan 2), publisher schema update (Plan 3), cross-faction moves (documented as manual retract+re-add for now).

**Placeholder scan:** No TBD/TODO. The Task 10 `OverrideAliases` stub is intentional and finalized in Task 11 (called out). ✅

**Type consistency:** `ICatalogRecordAdapter<T>` members (`IdentityKey`, `Url`, `Merge`, `WithFirstSeen`, `HasFirstSeen`, `ApplyRename`) are identical across Tasks 6, 9. `LivenessUpdater.Apply` signature identical in Tasks 5, 10. `Product` field set identical across Tasks 7–12. ✅

## Known risks / notes for the executor

- **System.CommandLine API drift:** Tasks 10 & 12 touch `Program.cs` command wiring. Mirror the existing 2.0.9 patterns in that file rather than the illustrative snippets.
- **Per-source health signal is coarse in Plan 1:** it infers "healthy" from "the manufacturer produced any grouped products this run." A finer explicit signal (HTTP/page-marker) per the spec is a reasonable follow-up; the ledger schema already supports it.
- **Publisher will break on `productType`/counts** until Plan 3. Task 14 Step 3 confirms the only expected solution-level failures are publisher tests.
