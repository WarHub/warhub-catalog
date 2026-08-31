# Task 1 report — Un-scope the retailers we already enumerate

**Plan:** `docs/superpowers/plans/2026-07-13-local-deep-harvest.md` (Plan 5 of 5), Task 1 — DESCRIPTOR portion.
**Date:** 2026-07-13. **Status:** COMPLETE (descriptor + taxonomy work; Steps 3/4/5 harvests are controller-run).

## What changed

| File | Change |
|---|---|
| `data/catalog/sources/ret-goblingaming.yaml` | dropped `scope.vendors: [Games Workshop]`; evidence comment added; `scope.currency: gbp` kept; `contract.minCount: 2500` UNCHANGED (comment says the controller re-floors it from the first wide harvest) |
| `data/catalog/sources/ret-tistaminis.yaml` | dropped `scope.vendors: [Games Workshop, GW-Local, GW-LOCAL]`; evidence comment added; `scope.currency: cad` kept; `contract.minCount: 1000` UNCHANGED (same note) |
| `data/catalog/taxonomy/manufacturers.yaml` | **4 new `vendorNames` aliases** (below) with live-evidence comments |

No strategy code changed. `shopify.py` reads `descriptor.scope.get("vendors")` and, when absent,
falls straight to `taxonomy.manufacturer_for_vendor(vendor)`; unmapped vendors land in
`skipped_unknown_vendor` instead of `out_of_scope_vendor`. That path is already covered by
`test_scope_vendors_absent_behaves_unchanged` (`tests/test_strategy_shopify.py:441`).

## Aliases added (the highest-value part of this task)

All four were discovered by live-enumerating `tistaminis.com/products.json` and confirmed by
pulling actual product titles/SKUs for each vendor tag. **tistaminis tags vendors by
brand-plus-format, not by brand** — the existing taxonomy only knew the `GW-Local` case of that
convention, so the rest of the convention was invisible.

| Alias added | Manufacturer | Live evidence (2026-07-13) |
|---|---|---|
| `Warlord-BLISTER` | warlord-games | **77 products in a single 1,500-product page sample** — the largest unmapped tracked-brand vendor string found anywhere. Titles/SKUs are unambiguously Warlord: `Hail Caesar Roman Standing Battleline` sku `WGH-IR-22`, `Hail Caesar Roman Pack Mule` sku `WGH-IR-55` |
| `Warlord-WEB` | warlord-games | `Bolt Action Soviet Tachankia MMG Wagon` sku `WGB-RI-130`; `Victory at Sea German Konigsberg` sku `745101006` |
| `GW-Web` | games-workshop | SKUs are raw GS1 GW barcodes: `High Elves Ellyrian Reavers` sku `5011921221493`, `High Elves Great Eagles` sku `5011921245932` (casefolded matching also covers the observed `GW-WEB`) |
| `GW-OOP` | games-workshop | `Chaos Space Marines World Eater Terminator Azrakh` sku `43-68`; `BLOOD BOWL VAMPIRE TEAM PITCH & DUGOUTS` sku `202-39`; `MIDDLE-EARTH SBG: HALBARAD` |

Impact: tistaminis' tracked-vendor share went **5.8% → 9.7%** on the sampled population, and
**warlord-games became the single largest tracked brand at that store** (111 sampled products vs
games-workshop's 102). Without these aliases the un-scoping would have silently dropped the
Warlord stock — the exact bucket that is 53% of the missing-EAN gap.

Deliberately NOT aliased:
- **`Games Workshop Used`** (742 products sampled — the store's biggest GW-ish tag). Second-hand
  one-off listings with unique `-aNN` handle suffixes. The original descriptor excluded these on
  purpose; taxonomy attribution now excludes them naturally (no manufacturer claims that string)
  and they fall into `skipped_unknown_vendor`. Correct outcome, preserved.
- **`OOP`**, **`Lion Rampant`**, **`Universal`**, **`3D Printing`** — checked by product sample;
  they are *not* hidden tracked-brand stock. `OOP` = Star Wars Armada (FFG, sku `FFGSWM34`),
  `Lion Rampant` = Star Wars Unlimited game mats (Gamegenic sku `GGS40084ML`). Generic/format
  tags, not brand tags.

## Vendor → manufacturer table

### Goblin Gaming (`https://www.goblingaming.co.uk`) — 2,250 products sampled (pages 1-4, 10, 20, 30, 40, 50 of 54)

| Vendor | Sampled count | → manufacturer |
|---|---:|---|
| Games Workshop | 454 | **games-workshop** |
| Vallejo | 214 | – |
| TT Combat | 215 | – |
| Kraken Wargames | 168 | – |
| Corvus Belli | 109 | **corvus-belli** |
| GCT Studios | 90 | – |
| Warlord Games | 86 | **warlord-games** |
| Atomic Mass Games | 72 | **atomic-mass-games** |
| Modiphius Entertainment | 66 | – |
| Mantic Games | 62 | **mantic-games** |
| The Army Painter | 62 | – |
| ARCANE TINMEN | 59 | – |
| Wizards Of The Coast | 56 | – |
| Wyrd Miniatures (+ `Wyrd miniatures`) | 47 | **wyrd-games** |
| Battlefront Miniatures | 47 | – |
| Pokemon | 43 | – |
| Q Workshop | 45 | – |
| Goblin Gaming (house brand) | 37 | – |
| Krautcover | 34 | – |
| Gale Force 9 | 32 | – |
| Wargames Atlantic | 30 | – |
| Archon Studios | 19 | – |
| Club Mocchi Mocchi | 18 | – |
| Universus | 17 | – |
| Osprey Publishing | 16 | – |
| Ultra Pro | 17 | – |
| The Colour Forge | 17 | – |
| Warcradle Studios | 22 | – |
| Freecompany | 13 | – |
| Gamegenic | 11 | – |
| Free League Publishing | 10 | – |
| Stonemaier Games | 10 | – |
| Bandai | 7 | – |
| Ultimate Guard | 5 | – |
| Wizkids / Cubicle 7 | 4 each | – |
| Fantasy Flight Games, Paizo, Artis Opus | 3 each | – |
| Mystery Dice Goblin, Incredible Dream Studios, Catalyst Game Labs, Edge Entertainment, Milliput, Revell | 2-3 each | – |
| Konami, Studio Midhall, Pickpocket Games, Edge, Ghost Galaxy, Office Dog, Themeborne, Chaosium, Big Potato Games, Z-Man Games | 1 each | – |

**Goblin tracked-vendor share: 830 / 2,250 = 36.9%.** No alias needed — every tracked brand this
store carries already used its canonical vendor string (`Wyrd miniatures` lowercase variant is
handled by the existing casefolded matching).

### Tistaminis (`https://tistaminis.com`) — 2,500 products sampled (pages 1-4, 10, 25, 40, 55, 70, 85 of ~100)

| Vendor | Sampled count | → manufacturer |
|---|---:|---|
| Games Workshop Used | 742 | – (excluded on purpose, see above) |
| 3D Printing | 613 | – |
| Universal | 123 | – |
| Battlefront (+ `BattleFront`) | 114 | – |
| Lion Rampant | 100 | – |
| Modiphius-1 | 79 | – |
| **Warlord-BLISTER** | 77 | **warlord-games** *(alias added)* |
| GW-LOCAL / GW-Local | 90 | **games-workshop** |
| Grosnor | 59 | – |
| Magic the Gathering | 43 | – |
| Asmodee | 36 | – |
| Pokemon (+ `Pokémon`) | 36 | – |
| Warlord Games | 31 | **warlord-games** |
| Mantic | 29 | **mantic-games** |
| Victrix | 32 | – |
| Battle Systems | 33 | – |
| Tistaminis (house) | 30 | – |
| Gamers Grass | 24 | – |
| Reaper Miniatures | 17 | – |
| Rubicon | 16 | – |
| Upper Deck | 14 | – |
| PM Hansen / Raging Heroes | 14 each | – |
| Plamod | 13 | – |
| Yugioh | 12 | – |
| Snacks | 13 | – |
| Commission | 9 | – |
| Prince | 9 | – |
| Artis Opus / Lightspeed | 8 each | – |
| **GW-WEB / GW-Web** | 9 | **games-workshop** *(alias added)* |
| JPN-TCG | 7 | – |
| Import Dragon / Famous Toys | 5 each | – |
| Topps (+ `TOPPS`) | 5 | – |
| **Warlord-WEB** | 3 | **warlord-games** *(alias added)* |
| **GW-OOP** | 3 | **games-workshop** *(alias added)* |
| OOP | 3 | – (FFG Star Wars Armada, not GW) |
| Wargames Atlantic / Deepcut Studio / Shieldwolf | 3 each | – |
| Tickets, Foam Brain, Army Painter, NorthStar/North Star, Battletech variants, Everest | 1-2 each | – |

**Tistaminis tracked-vendor share: 242 / 2,500 = 9.7%** (was 5.8% before the aliases).

## Extrapolated tracked-product counts (what the wide harvests should find)

| Store | Enumerable catalog | Tracked share (sampled) | Projected tracked products | Harvested under old scope |
|---|---:|---:|---:|---:|
| Goblin Gaming | 13,436 (full, 54 pages) | 36.9% | **~4,960** | 2,923 |
| Tistaminis | 25,000 (Shopify platform cap) | 9.7% | **~2,425** | 1,178 |

Projected per-manufacturer at goblin: games-workshop ~2,710, corvus-belli ~650, warlord-games
~515, atomic-mass-games ~430, mantic-games ~370, wyrd-games ~280.
At tistaminis: warlord-games ~1,110, games-workshop ~1,020, mantic-games ~290.

Combined, the un-scoping roughly **doubles** the tracked-product reach of these two sources
(4,101 → ~7,385), and — the point of the exercise — it puts ~1,625 Warlord and ~660 Mantic
products into the detail queue where the old GW-only scope reached **zero** of either.

## Concerns / caveats for the controller

1. **Shares are sampled, not exhaustive.** I sampled 2,250/13,436 goblin (16.7%) and
   2,500/25,000 tistaminis (10%), spread across the pagination rather than taken from the head,
   so they should be representative — but a full enumeration attempt stalled mid-run and I fell
   back to the spread sample rather than block the task. Treat the projected counts as ±10%.
2. **`contract.minCount` is now stale-low on both descriptors, intentionally.** Goblin's 2,500
   and tistaminis' 1,000 were floors for the GW-only population. They will not fail (the wider
   scope only adds products), but they no longer protect against a partial harvest. Re-floor both
   from the first wide run's evidence (Step 4) — projected ~85% floors would be ~4,200 (goblin)
   and ~2,050 (tistaminis).
3. **Detail-queue growth is the cost.** Goblin goes from ~2,900 to ~4,960 detail fetches and
   tistaminis from ~1,180 to ~2,425. At 0.5 rps that is ~2.8 h and ~1.3 h *of new work* on top of
   what is already banked — cheaper than the plan's 6 h / 10-20 h estimates, because the tracked
   share is well under 100% and the strategy only queues details for taxonomy-attributed products.
4. **Barcode fill at tistaminis is unverified for the newly-admitted brands.** The 97.7% figure in
   the recon doc was measured on GW stock. The sampled Warlord/Mantic products at tistaminis had
   `barcode: null` in the *bulk* `/products.json` payload — but so did the GW ones, because
   Shopify's bulk endpoint omits barcodes entirely; barcodes only appear in the per-product
   `.js` detail fetch, which is exactly what the harvest does. Not a red flag, but the Step-5
   gate (warlord + mantic EAN counts must rise) is the real test and should be watched.
5. **Only 6 of 9 tracked manufacturers appear at goblin, 3 of 9 at tistaminis.** Neither store
   stocks Steamforged, CMON or Para Bellum under any vendor string (searched ~24 pages across
   both for `steamforged|cmon|cool mini|para bellum|warmachine|guild ball|godtear` substrings:
   zero hits). Not a taxonomy bug — those brands simply are not carried.
