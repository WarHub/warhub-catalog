# Publisher Schema Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `WarHub.Catalog.Publish` to read the new source schema (fixing the broken paint reader) and surface the new lifecycle/detail fields in the published JSON.

**Architecture:** The publisher reads source YAML via `YamlSource` and emits a `dist/` JSON tree validated against authored JSON Schemas. The product reader already matches the new `Product` model; only product *surfacing* changes. The paint reader is **broken** — Plan 2 nested paint fields under `details:`, but `YamlSource.LoadBrands` still deserializes the flat `BrandCatalog`/`Paint` model. Plan 3 introduces local paint read-DTOs, updates the two builders + output records + JSON schemas, fixes the stale test fixtures to mirror the migrated YAML, and verifies the whole stack against the real `data/` tree.

**Tech Stack:** C# / .NET 10, records, System.Text.Json, YamlDotNet, xUnit, JSON Schema (draft 2020-12).

## Global Constraints

- Build clean under `dotnet build WarHub.Catalog.slnx -warnaserror` — 0 warnings, 0 errors.
- The catalog **tools** (`WarHub.ProductCatalog.Tool`, `WarHub.PaintCatalog.Tool`) and the shared `WarHub.CatalogStore` library are **frozen** — Plan 3 only touches `WarHub.Catalog.Publish` (+ its test project) and `docs/`.
- **No consumers exist → no back-compat constraint.** The published record schema may grow directly. Document envelope, partitioning, index, and manifest structure are **unchanged**. `schemaVersion` stays `"1.0"`.
- **Include everything:** every source record is published regardless of `status`. No lifecycle filtering at publish time.
- **Rich surfacing:** published product record gains `category`, `status`, `availability`; published paint record gains `category`, `status`, `availability`, `volumeMl`, `container`.
- Design authority: `docs/superpowers/specs/2026-07-07-publisher-schema-addendum.md`.
- The publisher validates every emitted document against its JSON Schema as it writes (`CatalogWriter.Write` → `SchemaValidator.Validate`). New output fields must be reflected in the schemas.
- Source field names (frozen models): `Product` has `Category, Packaging, Status, Availability, FirstSeen, Ean, Sku, ProductCode, Url, ImageUrl, …`. The new paint archival YAML shape is: top-level `name, category, status, availability, firstSeen, productCode, ean, imageUrl`, plus `details: { set, r, g, b, hex, volumeMl, container, type, finish }`.

---

## File Structure

- `tools/WarHub.Catalog.Publish/Documents.cs` — **modify**: extend output `ProductRecord` and `PaintRecord` with the new fields.
- `tools/WarHub.Catalog.Publish/ProductBuilder.cs` — **modify**: populate the new product fields from `Product`.
- `tools/WarHub.Catalog.Publish/PaintBuilder.cs` — **modify**: read from the new paint DTO (`details`) and populate the new paint fields.
- `tools/WarHub.Catalog.Publish/YamlSource.cs` — **modify**: `LoadBrands` returns the new local DTO.
- `tools/WarHub.Catalog.Publish/PaintSource.cs` — **new**: local read-DTOs for the nested brand-archive YAML (`BrandFile`/`PaintYaml`/`PaintDetailsYaml`).
- `tools/WarHub.Catalog.Publish/schema/product-catalog.json`, `schema/paint-catalog.json` — **modify**: add the new properties.
- `tools/WarHub.Catalog.Publish.Tests/PublishFixture.cs` — **modify**: rewrite product + paint fixture YAML to the migrated shape.
- `tools/WarHub.Catalog.Publish.Tests/PublishTests.cs` — **modify**: update assertions + add surfacing tests.

The `Provenance`, `CatalogWriter`, `SchemaValidator`, `Slug`, envelope documents, index, and manifest are unchanged.

---

### Task 1: Surface new product fields

**Files:**
- Modify: `tools/WarHub.Catalog.Publish/Documents.cs`, `tools/WarHub.Catalog.Publish/ProductBuilder.cs`, `tools/WarHub.Catalog.Publish/schema/product-catalog.json`
- Modify: `tools/WarHub.Catalog.Publish.Tests/PublishFixture.cs` (product fixture), `tools/WarHub.Catalog.Publish.Tests/PublishTests.cs`

**Interfaces:**
- Consumes: `Product` (frozen; `Category`/`Status`/`Availability` are non-null `string`).
- Produces: output `ProductRecord` with `Category`, `Status`, `Availability`.

- [ ] **Step 1: Update the product fixture to the migrated shape.** In `PublishFixture.cs`, replace the `general.yaml` product block with the new schema (drop `productType`/`productCount`; add the two axes + lifecycle). Keep Alpha with an EAN and Beta with only a `sku` (the `Product_ean_is_optional` test depends on it):

```yaml
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
```

- [ ] **Step 2: Write the failing surfacing test** in `PublishTests.cs`:

```csharp
[Fact]
public void Product_surfaces_category_status_availability()
{
    JsonElement products = Doc("products.json").GetProperty("products");
    JsonElement alpha = products.EnumerateArray().First(p => p.GetProperty("name").GetString() == "Alpha Box");
    JsonElement beta = products.EnumerateArray().First(p => p.GetProperty("name").GetString() == "Beta Box");
    Assert.Equal("miniatures", alpha.GetProperty("category").GetString());
    Assert.Equal("current", alpha.GetProperty("status").GetString());
    Assert.Equal("in_stock", alpha.GetProperty("availability").GetString());
    Assert.Equal("discontinued", beta.GetProperty("status").GetString());
    Assert.Equal("out_of_stock", beta.GetProperty("availability").GetString());
}
```

(`Doc` is the existing helper in `PublishTests.cs` that parses a dist JSON file. Confirm its name/signature and reuse it.)

- [ ] **Step 3: Run to verify it fails** — `dotnet test tools/WarHub.Catalog.Publish.Tests --filter Product_surfaces` → FAIL (property missing).

- [ ] **Step 4: Extend the output `ProductRecord`** in `Documents.cs` (renumber `JsonPropertyOrder` cleanly; new fields are non-null so they always emit):

```csharp
internal sealed record ProductRecord(
    [property: JsonPropertyOrder(1)] string? Ean,
    [property: JsonPropertyOrder(2)] string Name,
    [property: JsonPropertyOrder(3)] string? GameSystem,
    [property: JsonPropertyOrder(4)] string? Faction,
    [property: JsonPropertyOrder(5)] string Category,
    [property: JsonPropertyOrder(6)] string Status,
    [property: JsonPropertyOrder(7)] string Availability,
    [property: JsonPropertyOrder(8)] int Quantity,
    [property: JsonPropertyOrder(9)] string? ProductCode,
    [property: JsonPropertyOrder(10)] string? Url,
    [property: JsonPropertyOrder(11)] string? ImageUrl);
```

- [ ] **Step 5: Populate them in `ProductBuilder.Build`** — the `new ProductRecord(...)` call adds `Category: p.Category, Status: p.Status, Availability: p.Availability` (positional, matching the record order above). Leave the sort and everything else unchanged.

- [ ] **Step 6: Update the JSON schema** `schema/product-catalog.json` — add to `$defs.product.properties` (leave `required` as `["name", "quantity"]`):

```json
"category": { "type": "string" },
"status": { "type": "string" },
"availability": { "type": "string" }
```

- [ ] **Step 7: Run tests** — `dotnet test tools/WarHub.Catalog.Publish.Tests` → all pass (the existing `Product_ean_is_optional`, counts, partition tests still hold; new surfacing test passes). `dotnet build -warnaserror` clean.

- [ ] **Step 8: Commit** — `git commit -am "feat(publish): surface category/status/availability on published products"`

---

### Task 2: Fix the paint reader + surface new paint fields

**Files:**
- Create: `tools/WarHub.Catalog.Publish/PaintSource.cs`
- Modify: `tools/WarHub.Catalog.Publish/YamlSource.cs`, `tools/WarHub.Catalog.Publish/PaintBuilder.cs`, `tools/WarHub.Catalog.Publish/Documents.cs`, `tools/WarHub.Catalog.Publish/schema/paint-catalog.json`
- Modify: `tools/WarHub.Catalog.Publish.Tests/PublishFixture.cs` (paint fixtures), `tools/WarHub.Catalog.Publish.Tests/PublishTests.cs`

**Interfaces:**
- Produces: local read-DTOs `BrandFile { Brand, BrandSlug, Source, License, List<PaintYaml> Paints }`, `PaintYaml { Name, Category, Status, Availability, FirstSeen, ProductCode, Ean, ImageUrl, PaintDetailsYaml Details }`, `PaintDetailsYaml { Set, R, G, B, Hex, VolumeMl, Container, Type, Finish }`.
- `YamlSource.LoadBrands(string) : IEnumerable<BrandFile>` (was `IEnumerable<BrandCatalog>`).
- Output `PaintRecord` gains `Category`, `Status`, `Availability`, `VolumeMl`, `Container`.

- [ ] **Step 1: Update the paint fixtures to the migrated (nested) shape** in `PublishFixture.cs`. Replace `citadel.yaml` and `vallejo.yaml` with the new shape (drop `paintCount`; nest color/physical fields under `details`; add lifecycle). Keep the same paints/sets/hex/codes the equivalences fixture and existing tests reference (Abaddon Black/Base/C1/#231F20, Mephiston Red/Base/C2, Vallejo Black/Model Color/V1/#232323):

```yaml
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
```

```yaml
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
```

(Leave the `equivalences.yaml` fixture unchanged — the equivalences file keeps its flat `EquivRef` shape, which the real `data/paints/equivalences.yaml` also still uses.)

- [ ] **Step 2: Run existing paint tests to confirm the reader is now broken** — `dotnet test tools/WarHub.Catalog.Publish.Tests --filter Paint` → FAIL (e.g. `Paint_ids_and_range_map_from_set` gets an empty `range`/`hex` because the flat model can't read `details`). This is the RED that Task 2 fixes.

- [ ] **Step 3: Create the local read-DTOs** `PaintSource.cs` (mirrors `EquivalenceData.cs`'s local-model pattern; use `List<T>` so YamlDotNet can instantiate):

```csharp
namespace WarHub.Catalog.Publish;

// Local read-models for the new nested paint brand-archive YAML (data/paints/brands/*.yaml).
// The publisher owns its read contract; these decouple it from the paint tool's model and
// avoid a name clash with the publisher's own output PaintRecord.
internal sealed class BrandFile
{
    public string Brand { get; set; } = "";
    public string BrandSlug { get; set; } = "";
    public string Source { get; set; } = "";
    public string License { get; set; } = "";
    public List<PaintYaml> Paints { get; set; } = [];
}

internal sealed class PaintYaml
{
    public string Name { get; set; } = "";
    public string Category { get; set; } = "";
    public string Status { get; set; } = "";
    public string Availability { get; set; } = "";
    public string? FirstSeen { get; set; }
    public string? ProductCode { get; set; }
    public string? Ean { get; set; }
    public string? ImageUrl { get; set; }
    public PaintDetailsYaml Details { get; set; } = new();
}

internal sealed class PaintDetailsYaml
{
    public string Set { get; set; } = "";
    public int R { get; set; }
    public int G { get; set; }
    public int B { get; set; }
    public string Hex { get; set; } = "";
    public int? VolumeMl { get; set; }
    public string? Container { get; set; }
    public string? Type { get; set; }
    public string? Finish { get; set; }
}
```

- [ ] **Step 4: Point `YamlSource.LoadBrands` at the new DTO** — change its return type to `IEnumerable<BrandFile>` and `Deserialize<BrandFile>(...)`. Remove the now-unused `using WarHub.PaintCatalog.Tool.Models;` if nothing else in the file needs it (the product loader still uses `WarHub.ProductCatalog.Tool.Models`).

- [ ] **Step 5: Extend the output `PaintRecord`** in `Documents.cs` (clean `JsonPropertyOrder`; `Equivalents` stays last; nullable detail fields omit when null):

```csharp
internal sealed record PaintRecord(
    [property: JsonPropertyOrder(1)] string Id,
    [property: JsonPropertyOrder(2)] string Brand,
    [property: JsonPropertyOrder(3)] string Category,
    [property: JsonPropertyOrder(4)] string? Range,
    [property: JsonPropertyOrder(5)] string Name,
    [property: JsonPropertyOrder(6)] string Hex,
    [property: JsonPropertyOrder(7)] string? Type,
    [property: JsonPropertyOrder(8)] string? Finish,
    [property: JsonPropertyOrder(9)] int? VolumeMl,
    [property: JsonPropertyOrder(10)] string? Container,
    [property: JsonPropertyOrder(11)] string Status,
    [property: JsonPropertyOrder(12)] string Availability,
    [property: JsonPropertyOrder(13)] IReadOnlyList<PaintEquivalent> Equivalents);
```

- [ ] **Step 6: Update `PaintBuilder.Build`** to consume `IReadOnlyList<BrandFile>` and read color/physical fields from `p.Details`. Concretely:
  - Signature: `Build(IReadOnlyList<BrandFile> brands, EquivFile? equivalences, Provenance prov, CatalogWriter writer)`.
  - `Entry` holds a `PaintYaml`. Every `p.Set` → `p.Details.Set`, `p.Hex` → `p.Details.Hex`, `p.Type` → `p.Details.Type`, `p.Finish` → `p.Details.Finish`; `p.Name`/`p.ProductCode` stay top-level.
  - The `recordById[id] = new PaintRecord(...)` call fills the new fields:
    `Category: e.Paint.Category`, `Range: string.IsNullOrWhiteSpace(e.Paint.Details.Set) ? null : e.Paint.Details.Set`, `Hex: NormalizeHex(e.Paint.Details.Hex)`, `Type: e.Paint.Details.Type`, `Finish: e.Paint.Details.Finish`, `VolumeMl: e.Paint.Details.VolumeMl`, `Container: e.Paint.Details.Container`, `Status: e.Paint.Status`, `Availability: e.Paint.Availability`, `Equivalents: []`.
  - `NaturalKey`, id assignment (`Slug.Make(e.Paint.Name)`), equivalence folding, partitioning, and ordering are otherwise unchanged. The `.ThenBy(e => e.Paint.Hex, ...)` tiebreak in id assignment becomes `.ThenBy(e => e.Paint.Details.Hex, ...)`.

- [ ] **Step 7: Add the surfacing test** in `PublishTests.cs`:

```csharp
[Fact]
public void Paint_surfaces_category_status_volume_container()
{
    JsonElement paints = Doc("paints.json").GetProperty("paints");
    JsonElement abaddon = paints.EnumerateArray().First(p => p.GetProperty("id").GetString() == "citadel/abaddon-black");
    Assert.Equal("paint", abaddon.GetProperty("category").GetString());
    Assert.Equal("current", abaddon.GetProperty("status").GetString());
    Assert.Equal("unknown", abaddon.GetProperty("availability").GetString());
    Assert.Equal(12, abaddon.GetProperty("volumeMl").GetInt32());
    Assert.Equal("pot", abaddon.GetProperty("container").GetString());
    // discontinued paints are still published (include-everything).
    Assert.Contains(paints.EnumerateArray(), p => p.GetProperty("status").GetString() == "discontinued");
}
```

- [ ] **Step 8: Update the JSON schema** `schema/paint-catalog.json` — add to `$defs.paint.properties` (keep `required` as `["id", "brand", "name", "hex", "equivalents"]`; add `category` there too if desired, but leaving it non-required is fine):

```json
"category": { "type": "string" },
"status": { "type": "string" },
"availability": { "type": "string" },
"volumeMl": { "type": "integer" },
"container": { "type": "string" }
```

- [ ] **Step 9: Run tests** — `dotnet test tools/WarHub.Catalog.Publish.Tests` → all pass (the previously-RED paint tests are green again; new surfacing test passes; `Paint_ids_and_range_map_from_set`, `Equivalents_are_bidirectional`, counts, partitions all hold). `dotnet build -warnaserror` clean.

- [ ] **Step 10: Commit** — `git commit -am "feat(publish): read nested paint schema; surface status/availability/volume/container"`

---

### Task 3: End-to-end publish against the real migrated data

**Files:** none committed (dist/ is git-ignored). This is a verification task, like Plan 1/2's migration runs.

- [ ] **Step 1: Run the publisher against the real `data/` tree.** Use the same invocation CI/`Program.cs` uses. Inspect `Program.cs` for the exact CLI (options for products dir, paints dir, out dir, schema dir, provenance). A representative run:

```bash
dotnet run --project tools/WarHub.Catalog.Publish -- \
  --products data/products --paints data/paints \
  --out dist --schema tools/WarHub.Catalog.Publish/schema
```

(Match the real option names from `Program.cs`; provenance/version options may be required — supply placeholder values if so.)

- [ ] **Step 2: Confirm it completes and every document is schema-valid.** The publisher validates each document as it writes (`CatalogWriter` → `SchemaValidator`); a schema violation throws and fails the run. A clean exit = all emitted JSON validates against the updated schemas.

- [ ] **Step 3: Verify no records were dropped (include-everything).** Compare the published counts to the source: `manifest.json` `counts.products` / `counts.paints` (or `products.json` / `paints.json` `counts`) must equal the number of records in the source tree. Products: sum of `- name:` across `data/products/manufacturers/**/*.yaml`. Paints: 7105 (the migrated total). Investigate any shortfall (a legitimate cause is the paint builder's exact-duplicate natural-key de-dup and product de-dup — quantify and log it if the numbers differ, do not silently accept).

- [ ] **Step 4: Spot-check surfaced fields.** In `dist/paints.json`, confirm a paint carries `hex` (non-empty, `#rrggbb`), `volumeMl`, `container`, `status`, `category: "paint"` — proving the nested reader works on real data. In `dist/products.json`, confirm a product carries `category`, `status`, `availability`. Confirm at least one `discontinued`/`suspected-discontinued` record is present (include-everything).

- [ ] **Step 5:** No commit (dist/ is git-ignored). Record the observed counts and the run result in the progress ledger.

---

## Notes for the executor

- Tools + shared library are frozen — only `WarHub.Catalog.Publish[.Tests]` and `docs/` change.
- The output `PaintRecord` (this project) and the paint tool's archival `PaintRecord` are different types with the same name — the local read-DTOs (`PaintYaml`) deliberately avoid referencing the tool's model, so no aliasing is needed.
- Adding output fields does not break schema validation even before the schema edits (the `$defs` don't set `additionalProperties: false`), but update the schemas anyway — they are the published contract.
- Final run: `dotnet test WarHub.Catalog.slnx` and `dotnet build WarHub.Catalog.slnx -warnaserror` must be green. The whole-branch review gates the stacked PR against `catalog-paints-adoption` (Plan 2), not `main`.
