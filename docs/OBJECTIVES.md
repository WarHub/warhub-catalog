# What this catalog is for

The values below already govern this repo; each cites where it is enforced. **The citation is the
authority** — if this page and the code disagree, the code is right and this page is stale.

**1. Archive every release, ever.** "Discontinuations, limited runs, site drops, and manufacturer
closures must never remove data." We backfix or add; we drop only the genuinely bad or invalid, and
"it looked redundant" has never qualified. Stale beats deleted.
— `docs/superpowers/specs/2026-07-07-catalog-storage-model-design.md`;
`docs/superpowers/specs/2026-07-12-data-acquisition-rewrite-design.md`; `EvidenceStore.drop`,
the only deletion path, and `mark_missed` / `missStreak`, how everything else decays instead;
`CatalogReconciler`

**2. A file changes only when a fact changes.** A record not seen this run is kept, not dropped.
Identical input gives byte-identical output. A contract floor is never lowered to make a job green:
a drop is a claim about the world, and it gets evidence or the run fails.
— same specs; `yamlio.dump_yaml`; the wipe guard in `resolve_catalog`; `_check_contract`, which
raises on a count below the descriptor's `minCount`

**3. Anything published stays addressable.** A decade-old barcode still resolves, and its record
says what replaced it. Re-home a barcode before retracting whatever held it. A published id is a
consumer contract — removing one from `latest` breaks whoever stored it.
— `README.md`; `report --ean-guard`, which attests a confirmed primary `ean` or any
`additionalEans` entry

**4. The two catalogs overlap on purpose.** A pot is legitimately a product *and* a paint; the
barcode is the join, computed once at publish. What belongs in which catalog follows from a
source's provenance, never from the fact of overlap.
— `tools/WarHub.Catalog.Publish/CrossCatalogLinks.cs`; `SourceDescriptor.catalog`

**5. Evidence is the truth; the catalog is derived.** A source's claim stays that source's claim.
Conflicts and refusals are recorded, never guessed — a number that hides what it could not decide
is worse than one that admits it. No published field has a fallback behind it: where nothing was
asserted the record carries no value, and its basis says which of those two happened.
— `README.md` "Pipeline"; `tools/acquisition/scripts/gen_set_contents.py`;
`CanonicalProduct.categoryBasis` and the `categorize` stage that shrinks it

**6. Take politely; publish only what we may.** Honour robots and per-source rate limits. Source
terms bind what may be published at all — unreleased product information and wholesale pricing stay
out as policy, not as taste.
— `acquire/robots.py`; `acquire/strategies/gw_trade_sheets.py`

---

**Open — not settled by anything in this repo:**

- Who are the priority consumers?
- What counts as good coverage, and for which catalog?
- Which catalog leads when the two compete for effort?
