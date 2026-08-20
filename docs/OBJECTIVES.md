# What this catalog is for

The objectives below are not new policy. Every one of them is already decided and enforced
somewhere in this repo — in a design spec, a schema, a resolver comment, or a test. They are
collected here because they were only discoverable by reading all of those, and a reader who has
not is liable to "fix" something that is working as designed. That has happened; §4 is the case
that prompted this file.

Each objective cites where it actually lives. **The citation is the authority, not this page.** If
this page and the code disagree, the code is right and this page is stale — fix it.

---

## 1. Archive every release, ever

> The catalog's core objective is to **archive every release, ever** — discontinuations, limited
> runs, site drops, and manufacturer closures must never remove data. We only ever backfix or add;
> we drop only genuinely bad/invalid additions.
>
> — `docs/superpowers/specs/2026-07-07-catalog-storage-model-design.md`

A product that vanished from every website in 2019 still belongs here. A paint whose brand no
longer exists still belongs here. The catalog is the record of what *was sold*, not an inventory
of what is currently purchasable — `status` and `availability` carry that, per record.

**The bar for removal is "genuinely bad/invalid", and it is high.** A store's own test artifact
qualifies (see `excludeKeys`, and `test_no_published_product_looks_like_a_store_test_artifact`).
A record you have decided is redundant does **not** qualify on that basis alone — see §4.

## 2. Append-only, deterministic, fact-driven

The reconcile loop's locked decision, same spec:

> **KEEP** every existing record NOT seen this run — untouched. **Never dropped.**

and the stability contract:

> A data file changes only when a catalog **fact** changes — never merely because a scrape ran.
> Corollary: re-running the tool against identical input produces byte-identical files.

This is why a partial scrape can never blank a field (update-present / keep-on-empty), why a
missing record is flagged `suspected-discontinued` rather than deleted, and why generated files
are byte-compared in tests rather than count-compared (`test_set_contents.py`,
`test_paint_repro.py`). A diff in this repo is meant to be readable as a list of facts that
changed. That is also why contract floors exist and why **a floor is never lowered to make a job
green** — a drop is a claim about the world, and it gets evidence or it fails.

## 3. Barcodes and codes stay addressable forever

A decade-old box that still scans must still resolve to a record, and that record must say what
replaced it:

- `ean` is the single primary barcode; `additionalEans` holds barcodes a product genuinely carried
  in an earlier packaging.
- `supersedes` / `supersededBy` link the same product across two product codes. **Both records
  stay published**, each keeping its own code and barcode.
- The relation is deliberately *not* encoded in `status`, so existing `status` filters keep working.

— `README.md`, "Document shape"; enforced by `report --ean-guard`, which fails a run when a
previously **confirmed** barcode is lost rather than moved.

Re-homing a barcode always comes **before** retracting whatever held it. Never the reverse.

## 4. Two catalogs that deliberately overlap, joined by barcode

This is the one that is easiest to get wrong, so it is quoted in full:

> A product and a paint **can be the same physical thing** — a Citadel pot is a SKU in the product
> catalog AND a colour in the paint catalog — and the only evidence tying them together is the
> barcode printed on the pot. Nothing else matches: the names differ, the availability differs, the
> ids come from different id spaces. So the barcode is the join key, and this type is the only
> place that join is computed.
>
> — `tools/WarHub.Catalog.Publish/CrossCatalogLinks.cs`

So a paint appearing in **both** catalogs is **not a defect**. It is the expected state for any
paint somebody sells, and the publisher already reconciles it for consumers, two ways:

- `paintIds` / `productIds` stamped on the records, so a consumer holding one does not need a
  second fetch;
- `dist/barcodes.json`, the whole barcode → records index, so a consumer with a scanner resolves
  without downloading both catalogs.

Measured 2026-08-20 against the published v2026.8.19: `citadel-colour` 302 paints carry
`productIds` (838 product ids — a pot links to its trade case packs), `p3` 110 of 202. Brands
showing `productIds: 0` are not "clean"; they are brands whose product records do not exist yet.

**What IS a defect in this area**, and the distinction that matters:

| shape | verdict |
|---|---|
| a pot in both catalogs, barcodes agreeing, linked | **intended** — §4 |
| a pot in both catalogs with a **wrong `category`** (e.g. `miniatures` on a paint) | **defect** — mislabelling |
| barcodes that disagree between the two catalogs | **defect** — the join silently fails; fix upstream, never paper over at publish time |
| records synthesised into the PRODUCT catalog from a **paint source** | **defect** — this is what PR #75 removed |

The last row is the one that gets misread as licensing the first. PR #75 deleted 4,839 records that
paint **sources** had generated into the product catalog — records that were never committed, so
nothing published ever lost an id. It is *not* a precedent for deleting a product record earned
from a **product source**: a retailer or distributor listing a pot for sale is a real product by
this catalog's own definition, and `SourceDescriptor.catalog` exists to separate exactly those two
provenances. **Provenance decides this, not the fact of overlap.**

## 5. Evidence is the source of truth; the catalog is derived

Per-source observations under `data/evidence/` are the ledger; `data/catalog/` is resolved from
them and is reproducible. A source's claim is kept as *that source's claim*, with kind priority
deciding who wins — not overwritten into anonymity. This is why the resolver is pure, why
`resolve` is re-runnable, and why a conflict is data (`data/review/conflicts.yaml`) rather than an
exception.

— `README.md`, "Pipeline"; `tools/acquisition/src/warhub_acquisition/resolve/`.

## 6. Refusals are recorded, never guessed

> REFUSALS ARE RECORDED, NEVER GUESSED. A ref naming zero or several paints goes to `unresolved:`
> with its raw code and a reason … A file that reported 100% by dropping the misses would be the
> failure mode this whole exercise is about.
>
> — `tools/acquisition/scripts/gen_set_contents.py`

Applies everywhere: an ambiguous join is written to `conflicts.yaml` rather than resolved by
picking the first candidate; a paint code naming two paints is refused rather than assigned. A
number that looks complete because the awkward cases were dropped is worse than a number that
admits what it could not decide.

## 7. Publish clean, versioned, self-describing JSON

Whole catalog or a single slice; a manifest as the discovery document; a JSON Schema per document
kind, validated on every build; per-day versions with immutable release assets to pin and a
`latest` for Pages.

— `README.md`, "Consuming the catalog".

The consequence worth stating: **published ids are a consumer contract.** Removing an id from
`latest` breaks anyone who stored it. Product ids are stable (`manufacturer/code-or-slug`); paint
ids are stable *within* a release but not yet across releases, which is exactly why the
cross-catalog link is emitted rather than left for consumers to recompute.

---

## How to use this page

Before changing what the catalog *contains* (as opposed to how it is acquired), check the change
against §1, §3 and §7 specifically: does it remove a record, drop a barcode, or delete a published
id? If yes, that needs a maintainer decision and a recorded reason — not an inference that the
record looked redundant.
