# Task 2 report: broaden sitemap-retailer URL filters (Radaddel + Game Nerdz)

Plan 5, Task 2. Scope: `data/catalog/sources/ret-radaddel.yaml`, `ret-gamenerdz.yaml` only.
DESCRIPTOR-ONLY task — no EXECUTE sweep run here (that is a separate controller-run
background step per the plan; this task ends at "commit the broadened descriptors").

## 1. Term-derivation method

Read `data/catalog/taxonomy/game-systems.yaml` (48 game-system slugs) and
`data/catalog/taxonomy/manufacturers.yaml` (9 manufacturers + `vendorNames`) directly (dumped
via a scratch `uv run python` one-liner, not from memory/imagination). Built a candidate term
list per manufacturer bucket:

- **GW** (kept, unchanged intent): `warhammer`, `citadel`, `forge-world` + added `age-of-sigmar`,
  `horus-heresy`, `the-old-world` (GW sub-brands whose slugs don't necessarily contain
  "warhammer").
- **Warlord Games**: `warlord-games` + every Warlord-published game-system slug (`bolt-action`,
  `black-powder`, `hail-caesar`, `cruel-seas`, `victory-at-sea`, `blood-red-skies`,
  `konflikt-47`, `warlords-of-erehwon`, `gates-of-antares`, `spqr`, `judge-dredd`,
  `achtung-panzer`, `black-seas`, `pike-and-shotte`, `epic-black-powder`, `epic-hail-caesar`,
  `epic-pike-and-shotte`, `stargrave`).
- **Mantic Games**: `mantic-games` + `kings-of-war`, `deadzone`, `dreadball`,
  `walking-dead-all-out-war`, `halo-flashpoint`, `dungeon-saga`.
- **Corvus Belli**: `infinity`, `aristeia`, `warcrow`.
- **Wyrd Games**: `wyrd`, `malifaux`, `the-other-side`.
- **Steamforged Games**: `steamforged`, `warmachine`, `guild-ball`, `godtear`, `epic-encounters`.
- **Atomic Mass Games**: `atomic-mass`, `marvel-crisis-protocol`, `star-wars-legion`,
  `star-wars-armada`, `star-wars-shatterpoint`, `star-wars-x-wing`.
- **CMON**: `cmon`, `asoiaf`.
- **Para Bellum**: `para-bellum`, `last-argument-of-kings`.

53 terms total in the final regex.

## 2. Measurement method

Scratch scripts in the session scratchpad (not the repo):
`fetch_and_cache.py` (live-fetches both sites' full sitemap trees once, 1 req/s, UA
`warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)`, caches to
`sitemap_cache.json` tagged by sitemap type) and `final_check2.py` /
`analyze.py` (regex measurement over the cache — old filter vs candidate/final filter, per-term
contribution counts, per-sitemap-type breakdown, random-sample junk classification).

Live totals (2026-07-13, this session): **Radaddel 12,806 URLs** (1 gzipped child sitemap,
matches prior probe exactly). **Game Nerdz 260,267 URLs** across 32 `xmlsitemap.php` child pages
(27 `products`, 1 `pages`, 1 `categories`×2, 1 `brands`×2, 1 `news` — small drift from the
2026-07-13-coverage-arithmetic.md doc's 257,416/3,164, normal site churn, not a discrepancy).

## 3. Iterative junk-filtering (the actual work)

An initial broad term list (adding every taxonomy slug/vendor name verbatim, including bare
`middle-earth`, `armada`, `warlord`, `mantic`, `corvus`, `firefight`, `conquest`) was measured
first and found to admit heavy junk on Game Nerdz specifically (Radaddel isn't filtered at all,
see §5, so its junk exposure is moot):

| Term (bare, dropped) | Matches | Junk cause (live-verified) |
|---|---:|---|
| `middle-earth` | 2,872 | Magic: The Gathering "Tales of Middle-earth" set, not GW's Middle-earth SBG |
| `warlord` | 130 | ~98% MTG "Warlord" creature-type cards + an unrelated CCG; Game Nerdz's own category page `/warlord/` is titled "Card Games - Warlord" (confirmed by live browser navigation) |
| `mantic` | 76 | ~97% "manticore"/"necromantic" (D&D minis, Blood Bowl team names) collisions |
| `corvus` | 14 | 100% junk here: GW "Corvus Blackstar", Citadel "Corvus Black" paint, Star Wars Destiny cards — 0 genuine Corvus Belli hits |
| `firefight` | 7 | 100% junk: Star Wars Destiny "Into the Firefight" cards — 0 genuine hits |
| `armada` | 30 (radaddel) | Freebooter Miniatures' unrelated "Imperiale Armada" line (verified by fetching a product page: `itemprop="brand"` = "Freebooter Miniatures") |
| `conquest` | many | Common English word: Master of Orion, Dune, Hero Realms, MTG "Lich Knights Conquest", etc. |

Fixes applied: dropped `middle-earth` and bare `armada`/`corvus`/`firefight` entirely (their
genuine signal is already covered by other terms — `infinity`/`aristeia`/`warcrow` for Corvus
Belli, `age-of-sigmar`/`horus-heresy`/`the-old-world`/`warhammer`/`citadel`/`forge-world` for GW);
replaced bare `warlord` → `warlord-games`; bare `mantic` → `mantic-games`; bare `conquest` →
`last-argument-of-kings` (Para Bellum's actual product-slug pattern).

**Finding surfaced by this process, not assumed:** Game Nerdz's real Warlord Games miniatures
stock is negligible — after removing the MTG/CCG false positives, exactly **one** confirmed
Warlord product exists across the whole 260k-URL sitemap: `bolt-action-us-army-command`. This was
cross-checked two ways: (a) sitemap regex, (b) a live browser session (`claude-in-chrome`)
against `gamenerdz.com/search.php?search_query=bolt+action` — the "find" tool's product-grid scan
returned "Bolt Action: US Army Command" as the only genuine hit among ~15+ results (rest were
"Ice Bolt" MTG cards, Bandai "Action Base" figures, Tekken action figures — fuzzy any-word
matching). The plan's "live search for 'bolt action': 9 hits" claim counted these fuzzy/irrelevant
hits, not genuine Warlord products. This is a structural-ceiling finding (Task 2's Warlord yield
from Game Nerdz specifically will be tiny), not a filter-construction failure — Mantic fares much
better (kings-of-war 127, dungeon-saga 16, walking-dead-all-out-war 43, halo-flashpoint 43,
mantic-games 1 = ~230 URLs of genuine Mantic-line signal).

## 4. Final junk-rate check

40-URL random sample (seed 123) of newly-admitted Game Nerdz **product-type** URLs, manually
reviewed: **0/40 junk** (100% genuine wargaming-miniatures products — Infinity, Malifaux, Kings of
War, Star Wars Legion/Shatterpoint, Halo Flashpoint, Marvel Crisis Protocol, Judge Dredd RPG, Age
of Sigmar). Sample of 10:

```
https://www.gamenerdz.com/infinity-aleph-andromeda-sophistes-of-the-steel-phalanx-submachine-gun
https://www.gamenerdz.com/kings-of-war-2nd-edition-deluxe-gamers-edition
https://www.gamenerdz.com/infinity-code-one-dire-foes-mission-pack-beta-void-tango
https://www.gamenerdz.com/malifaux-the-arcanists-ramos-miners-steamfitters-union
https://www.gamenerdz.com/judge-dredd-the-worlds-of-2000-ad-rpg-the-robot-wars
https://www.gamenerdz.com/infinity-combined-army-morat-aggression-forces-starter-pack-6
https://www.gamenerdz.com/halo-flashpoint-banished-sangheili-mercenaries
https://www.gamenerdz.com/malifaux-3e-the-ten-peaks
https://www.gamenerdz.com/warhamemr-age-of-sigmar-regiments-of-renown-flesh-eater-courts-the-scarlet-jury
https://www.gamenerdz.com/malifaux-3e-heavy-metal
```

Across **all** sitemap types (not just `products`), 30 of the final 5,455 total matches (0.55%)
land on non-product `categories`/`brands` sitemap pages (e.g. `/kings-of-war`, `/infinity`,
`/brands/Warlord-Games.html`) — these will just fail extraction and count
`stats["extraction_failed"]`, the same (pre-existing, unchanged) behavior the old filter already
had at a smaller scale (7/3,171 category-page leakage under the old filter). **Overall junk rate:
~0.6%, all in the harmless "extraction_failed" category, not silent corruption.**

## 5. Before/after URL counts

| Source | Total sitemap URLs | Filter before | Filter after | Newly admitted |
|---|---:|---:|---:|---:|
| Radaddel | 12,806 | *(none — already unfiltered)* | *(unchanged — still none)* | 0 (no change) |
| Game Nerdz | 260,267 | 3,171 (`warhammer\|citadel\|forge-world`) | **5,455** (53-term regex) | **2,284** |

Radaddel was re-verified rather than assumed unchanged: applying the same broadened
multi-manufacturer term list to Radaddel's live sitemap would match only **670 of 12,806** URLs
(5.2%) — i.e., a filter here would still discard >94% of the catalog, confirming the original
2026-07-13 probe's finding that Radaddel's slugs carry no reliable brand/category token (e.g. the
GW flagship `necrons-combat-patrol` has no GW substring at all). Left deliberately unfiltered.

Game Nerdz's broadened set (5,455) stays well under the plan's ~20k explosion-cap threshold, so
no `--budget` note is needed for the controller beyond what the descriptor comment already says.

## 6. Files changed

- `data/catalog/sources/ret-gamenerdz.yaml` — `scope.urlInclude` replaced with the 53-term
  regex; comment records the before/after counts, the Warlord/Mantic gap rationale, and the
  junk-term removal log (§3 above, condensed).
- `data/catalog/sources/ret-radaddel.yaml` — no functional change (still no `urlInclude`);
  comment extended to record that Task 2 re-verified rather than assumed the "leave unfiltered"
  decision, with the 670/12,806 evidence.
- No test changes needed — `tests/test_strategy_sitemap_sd.py` builds its own descriptor scopes
  in-test (`radaddel_descriptor()`/`gamenerdz_descriptor()`), it does not read the real YAML
  files, so none of its assertions depend on the production regex content.

## 7. Test suite

`uv run pytest -q` → **457 passed, 4 deselected** (matches the stated baseline exactly, no
regressions).
