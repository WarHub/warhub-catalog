# Steamforged store split — Warmachine moved to warmachine.gg (2026-08-12)

`mfr-steamforged` was failing its `minCount: 500` contract: the committed evidence holds **600**
observations from the 2026-07-13 probe, and a fresh run enumerates **248**. The two readings on the
table were *scope/tag change* (fix the strategy) and *genuine catalogue cut* (lower the floor, age
the missing products out). **Both were wrong.** The products moved to a second Shopify store
Steamforged runs, `warmachine.gg`, and are alive and on sale there today.

This matters because the losing answer was not merely imprecise — it was actively harmful. Lowering
the floor to ~210 and letting `mark_missed` decay the 352 would have published **352 actively-sold
products as `suspected-discontinued`**, on evidence that looked, right up to the last check, like a
clean catalogue cut.

## What the probe found

`https://steamforged.com/products.json?limit=250&page=N`, enumerated exactly as `shopify.py` does:

| | 2026-07-13 | 2026-08-12 |
|---|---|---|
| store-wide | 1089 | **587** |
| attributed to `steamforged-games` | 600 | **248** |

Diffing the committed 600 against the live store by handle:

| bucket | count |
|---|---|
| survivors (committed, still attributed) | **248** |
| **re-tagged** (committed, still in store, now unmapped vendor) | **0** |
| delisted (committed, gone from store) | **352** |
| new (attributed, not in committed) | **0** |

Two things stand out. **Zero re-tagged** kills the scope/tag-change reading outright: not one
committed product is still in the store hiding under a vendor string the taxonomy doesn't map. And
the 352 are not a scattered sample — they are **all Warmachine**, the entire line. Every other line
is byte-for-byte intact (Guild Ball 103, Epic Encounters 71, Godtear 70), with zero churn.

Direct checks confirmed the removal was real, not an unpublish: **12 of 12** sampled delisted
handles return **404** on `/products/<handle>.js`, and `/collections/warmachine` is **404** too.

At that point the evidence for "genuine catalogue cut" was as strong as it gets.

## Why the catalogue-cut reading was still wrong

The tell was outside the store. Steamforged **bought** Warmachine, Iron Kingdoms and Formula P3
outright from Privateer Press in **2024** — not a licence, an acquisition. And in **June 2026** they
made redundancies and cut board-game crowdfunding specifically to *refocus* on Warmachine, whose
revenue had **tripled** in the 21 months since. A company does not discontinue the line it is
restructuring itself around. The catalogue-cut story required believing a commercial absurdity.

steamforged.com says so itself. Its homepage carries a banner:

> "Warmachine and P3 Paints have a new online home"

pointing at **warmachine.gg**.

## warmachine.gg

Same Shopify shape, enumerated the same way — **613 products**:

| vendor tag | count | attributed |
|---|---|---|
| Warmachine | 361 | yes |
| P3 Paints | 222 | yes |
| Iron Kingdoms | 25 | yes |
| Warmachine (app subscribers only) | 1 | yes |
| Steamforged Games - Tradeshow | 4 | **no** |

Reconciling against the 352 that left steamforged.com:

- **350** present under an **identical handle**
- **352 of 352** matched by **sku**
- **0** unmatched

Nothing was discontinued. The line changed address.

`robots.txt` permits enumeration. Field rates measured on the probe: name **1.000**, sku **0.995**.
All **222** P3 skus match the existing `SF[A-Z0-9-]+` `codePattern` — the range was re-coded to SF\*
after the acquisition — so these observations resolve onto existing entities rather than
duplicating them.

## What changed

1. **`mfr-warmachine`** — new `strategy: shopify` source on `https://warmachine.gg`,
   `minCount: 520` (~85% of 609 attributed). Registered in group **A2** of `catalog-acquire.yml`,
   beside the source it split from.
2. **Taxonomy** — `Iron Kingdoms` and `P3 Paints` added to `steamforged-games`. They had been
   excluded since July, listed alongside the store's genuinely-licensed tags (Dark Souls, Elden
   Ring, Monster Hunter). That was a misclassification: those are third-party IP Steamforged only
   *publishes*, whereas these are brands it *owns*. The repo already had the fact on file — the
   July pipeline analysis lists Privateer Press as a dead stub, "IP moved to Steamforged"
   ([2026-07-12-current-pipeline-analysis.md](2026-07-12-current-pipeline-analysis.md), source
   table) — so this was an oversight rather than a judgement call. The store split made it visible
   by putting all three brands in one in-house catalogue. Licensed tags remain excluded.
3. **`mfr-steamforged`** — `minCount` **500 → 210** (~85% of 248), because this source's **scope**
   shrank, not because the floor was inconvenient.
4. **`Steamforged Games - Tradeshow` stays unmapped** despite naming the company: all 4 products
   under it are Baron of Dice accessories (skus BOD001–BOD003, **0 of 4** matching `codePattern`) —
   another maker's goods on a Steamforged booth.

## Why both source changes had to land together

`_check_contract` runs **before** any evidence or cursor write, so while `mfr-steamforged` fails its
floor the 352 stay frozen at `missStreak: 0` — stale, but harmless.

Lower the floor **alone** and that protection lifts: runs start passing, `full_sweep` eventually
flips true, `mark_missed` increments the 352, and at `missStreak >= 3` every entity whose only live
member was `mfr-steamforged` resolves to `suspected-discontinued`. **40** of the 351 affected
published products have steamforged-only evidence and would have gone that way; the other 311 would
have been saved only incidentally, by retailer observations.

With `mfr-warmachine` landing in the same change, each of those entities keeps a live member, so
`resolve/attributes.py` holds them at `current` — correctly — while the `mfr-steamforged` copies age
out, which is also correct: that store really did stop selling them. Sequenced apart, there is a
window where the catalogue is actively wrong.

## Re-derivation

Enumerate `https://steamforged.com/products.json?limit=250&page=N` and
`https://warmachine.gg/products.json?limit=250&page=N` until an empty page, bucket by `vendor`
casefolded against `vendorNames` for `steamforged-games` in `data/catalog/taxonomy/manufacturers.yaml`,
and diff handles/skus against `data/evidence/products/mfr-steamforged/observations.jsonl`.

## The general lesson

A source failing `minCount` after a large drop has a third explanation beyond "our scraper broke"
and "the products died": **the seller moved them to a different property it also owns.** It presents
identically to a catalogue cut from inside the store — hard 404s, a dead collection, a clean
line-shaped loss, zero re-tags — and the only thing that distinguished it here was checking what the
company was *doing*, and reading the vendor's own homepage banner.

Worth noting for the next one: this is a **source-roster** event, not a lifecycle event. The
question to ask before lowering any floor is not "did these products leave this site?" but "where did
they go?" — and a floor should only ever be lowered once that second question has an answer.

## Follow-ups (not done here)

- **Two Shopify test artifacts are published as real products.** `steamforged-games/test-product`
  ("Test Product", sku `TestProduct`) and `steamforged-games/test-paint-f-f-bundle` ("Test Paint &
  F&F Bundle") are live under the `Steamforged Games` vendor tag and published `status: current`.
  Both have mfr-steamforged-only evidence, so retracting them orphans nothing. The third product
  under that tag, `strangelight-confidential-secret-files`, is real.
- **A live P3 paint source is now possible.** `data/paints/brands/p3.yaml` carries only the static
  `Arcturus5404/miniature-paints` import, every entry `availability: unknown`. warmachine.gg
  publishes **222 P3 pots** with skus and barcodes — the first live surface this brand has had.
