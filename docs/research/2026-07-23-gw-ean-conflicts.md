# GW EAN conflicts — repackaging joins & review (2026-07-23)

Adding the GW trade barcodes (PR #40) surfaced **38 EAN conflicts** on Games Workshop products —
cases where one catalog entity has two different barcodes asserted by its sources. This documents
what each one actually is, in plain English, and what was done. Analysis was fanned out across
subagents (one per conflict), and every proposed repackaging join was adversarially re-checked as
same-product before being written.

**The headline:** almost none of these are "wrong data" — they are GW *repackaging* the same
product with a new barcode (and often a new product code and name). The catalog wants to keep
**both** barcodes: the current one as the primary `ean`, the retired one in `additionalEans` so
old shelf stock still scans.

| bucket | count | what it is | action |
|---|---:|---|---|
| Fixed by repackaging join | 8 | old code folded → retired barcode moved to `additionalEans` | done in this PR |
| Stale published primary | 23 | catalog shows the **old** barcode as primary (a resolver ranking artifact) | needs a resolver fix — see below |
| Distinct products (do NOT merge) | 3 | two genuinely different products, or a material re-sculpt | your call, per item |
| Other needs-direction | 4 | name-slug entity or retailer mislabel; no clean fold | noted per item |

## 1. Fixed in this PR — repackaging joins (`additionalEans` populated)

Each verified same product, old box → new box. The current barcode stays primary; the retired one
is preserved in `additionalEans`. Conflict cleared.

| product | current (primary) | retired → additionalEans | folded old code |
|---|---|---|---|
| AOS S/E + PAINT SET ENG/SPA/PORT/LATV/RM | `5011921219322` | `5011921260157` | `52170218004` |
| Drazhar | `5011921155873` | `5011921127504` | `99120112040` |
| Dryads | `5011921179398` | `5011921062164` | `99120204012` |
| Haarken Worldclaimer, Herald of the Apocalypse | `5011921178179` | `5011921111084` | `99120102088` |
| Kor'sarro Khan | `5011921142590` | `5011921119868` | `99120101255` |
| Kustom Boosta-blasta | `5011921157068` | `5011921107995` | `99120103064` |
| Legions Imperialis: Lightning Fighter Squadron | `5011921188772` | `5011921132133` | `99121808004` |
| Rukkatrukk Squigbuggy | `5011921157082` | `5011921108022` | `99120103066` |

## 2. Stale published primary — the catalog is showing an OLD barcode

**23 products** publish a *retired* barcode as their primary `ean`. Root cause is a
resolver ranking rule: when the same product code carries two barcodes, the resolver ranks by
source *kind* first, and the legacy import (`kind: curated`) outranks the live GW trade feed and
live retailers (`kind: manufacturer`/`retailer`). So a stale barcode from the 2020-era import wins
primacy over the barcode GW and every current retailer actually use today.

These are **not** individual judgement calls — they share one cause and one fix: teach the resolver
to prefer a **live-corroborated** barcode over a curated/legacy/archive-only one for the primary
(the `corroborate.py` docstring already states this is the intent — *"a stale legacy barcode must
not displace the live one"* — it just is not applied in the same-code-disagreement branch). That is
a small, principled resolver change best done as its own stacked PR with tests, since it shifts
primacy semantics catalog-wide. Once landed, all of these clear at once, most also gaining an
`additionalEans`.

| product | currently published (STALE) | correct current barcode |
|---|---|---|
| AGE OF SIGMAR: SET DI PRESENTAZIONE ITA | `5011921220908` | `5011921251452` |
| AGE OF SIGMAR: SET INTRODUCTORIO (ESP) | `5011921220915` | `5011921251469` |
| Askurgan Trueblades | `5011921182121` | `5011921261444` |
| Boingrot Bounderz | `5011921170241` | `5011921256891` |
| Cave Drake | `5011921037162` | `5011921238125` |
| Chaos Gargant | `5011921133901` | `5011921177806` |
| Claws of Karanak | `5011921182114` | `5011921259533` |
| Dragon | `5011921024582` | `5011921238118` |
| Goreblade Warband | `5011921079964` | `5011921252923` |
| Gutrot Spume | `5011921063765` | `5011921259090` |
| Jade Obelisk | `5011921139521` | `5011921261017` |
| Karanak | `5011921113187` | `5011921259083` |
| Lord of Blights | `5011921170333` | `5011921254804` |
| Lord of Plagues | `5011921170326` | `5011921254798` |
| Monsta-Killaz | `5011921201495` | `5011921261420` |
| Mortisan Boneshaper | `5011921204281` | `5011921254668` |
| Poxbringer | `5011921090877` | `5011921259113` |
| Rogue Trader Entourage and Voidsmen-at-Arms | `5011921180998` | `5011921236336` |
| Rotbringer Sorcerer | `5011921995462` | `5011921254781` |
| Rotmire Creed | `5011921179039` | `5011921261024` |
| Thatos Pattern: Platforms & Walkways | `5011921176939` | `5011921176953` |
| Vulkyn Flameseekers | `5011921201471` | `5011921261437` |
| Warhammer 40.000: Paints + Tools Set | `5011921196951` | `5011921260256` |

## 3. Distinct products — do NOT merge (your decision)

These are the genuinely ambiguous ones. Each is **two different products** (or a material
re-sculpt), so joining them would corrupt the catalog. They need a data decision, not a join.

### Chief Librarian Tigurius  (`99120101329`)

Ultramarines special character. Old code 99120101254 (barcode `5011921119776`) → current code
99120101329 (barcode `5011921142583`, agreed by every retailer + the current trade sheet).

**This one is a genuine disagreement.** The first-pass analysis read it as a plain repackage (same
model, new box) and proposed a join. The adversarial verifier overruled it: a web check found the
old and new codes are a **metal → plastic re-sculpt** — a different physical sculpt in a different
material, which the project's own join rule classes as a *distinct product*, not a repackage. Given
that, **no join was applied** (the safe default). If it really is just a re-box, the join
`mfr-gw-trade:99120101254 → games-workshop/99120101329` would clear it cleanly; if it is a re-sculpt,
the two barcodes belong to two separate products.

**Recommendation:** Confirm against a physical box whether the 99120101254 and 99120101329 Tigurius
are the same sculpt. If same → add the join above. If a re-sculpt → keep them as distinct products
(do not merge). Left unmerged pending your call.

### Zodgrod Wortsnagga  (`99120103074`)

This entity is the standalone Ork character Zodgrod Wortsnagga (single clampack miniature, barcode 5011921128327). The second barcode, 5011921138395, is the 'WH40K: Beast Snagga Orks Army Set' - a whole multi-unit army launch box that merely CONTAINS Zodgrod, not a new box of the single model. They are genuinely different products. The army-set barcode was dragged onto Zodgrod because Goblin Gaming listed a Zodgrod product under the army-set product code 60010103001. Current/primary barcode is the Zodgrod single (5011921128327); the army-set barcode does not belong on this entity.

**Recommendation:** Do not join. Split the 'Beast Snagga Orks Army Set' observations (code 60010103001, barcode 5011921138395) out into their own product entity, and keep Zodgrod Wortsnagga's primary barcode as 5011921128327 - a join here would falsely stamp the army-set barcode onto the single character.

### Combat Patrol: Space Marines  (`99120101402`)

GW product code 99120101402 has two completely different products stuck on it. A curated seed record labels it 'Combat Patrol: Space Marines' (a large multi-unit army starter box, barcode 5011921178629), while Games Workshop's own trade sheet lists that same code as the now-discontinued 'Kill Team: Space Marine Scout Squad' (a small single-squad kit, barcode 5011921203420, on an archived Deletions row). These are not the same box repackaged - they are different products, so neither barcode is a 'retired' version of the other. A Tistaminis listing is already annotated '(OLD BOX-CHECK)', so a human likely spotted this before.

**Recommendation:** Do not join - the two barcodes are different products (a Combat Patrol army box vs a Kill Team scout-squad box). A human should confirm which product truly owns code 99120101402 (GW appears to have reused it: first the discontinued Kill Team: Space Marine Scout Squad, then Combat Patrol: Space Marines) and split the Scout Squad observations (mfr-gw-trade:99120101402 and ret-tistaminis:kill-team-space-marine-scout-squad, both barcode 5011921203420) out into their own entity.

## 4. Other needs-direction

- **Acolyte Hybrids** (`99120117019`, retailer-inconsistency): The Warhammer 40,000 Genestealer Cults 'Acolyte Hybrids' box (the same dual-build kit also sold as 'Hybrid Metamorphs'). GW recoded it from the old, now-discontinued code 99120117003 (barcode 5011921077267) to the current code 99120117019 (barcode 5011921171934, confirmed by GW trade, legacy, and Goblin Gaming) - a clean GW repackage in isolation. But a pure join is blocked by a retailer inconsistency: GameNerdz lists it under the current GW number GWS51-51 while still carrying the OLD barcode 5011921077267, and that sku does not normalize to the old GW 11-digit code, so folding 99120117003 leaves GameNerdz asserting the retired barcode as a live primary candidate and the conflict persists.
  - *Recommendation:* Folding the discontinued code 99120117003 into 99120117019 handles GW's own old barcode but will not clear the conflict on its own, because GameNerdz (sku GWS51-51, which normalizes to nothing) still asserts the retired barcode 5011921077267 as a live source; a human should correct or retire GameNerdz's stale barcode (or suppress that observation) so 5011921171934 becomes the sole primary with 5011921077267 in additionalEans.

- **Biophagus** (`99070117012`, repackaging-needs-direction): The Genestealer Cults 'Biophagus' single character, re-released under a new product code. Old code 99070117003 (barcode 5011921110988) became current code 99070117012 (barcode 5011921171835), which GW's trade sheet, the legacy catalog and Goblin Gaming all confirm. Same model, new box and code. This is NOT a clean join: the retailer GameNerdz still lists the OLD barcode 5011921110988 under its own SKU 'GWS51-44' (which normalizes to nothing, not the old GW code 99070117003), so folding the old code does not supersede GameNerdz's row and 5011921110988 stays a competing primary.
  - *Recommendation:* A code-join on 99070117003 won't fully clear it because GameNerdz asserts the old barcode under a retailer SKU; correct/retire the GameNerdz barcode, or add an override pinning primary 5011921171835 with 5011921110988 in additionalEans.

- **Canoness** (`99120108058`, repackaging-needs-direction): Same product repackaged: the Adepta Sororitas Canoness single-model clampack. GW moved it from product code 99120108034 (old barcode 5011921131174, now an archived trade row) to code 99120108058 (current barcode 5011921156771, corroborated live by Goblin Gaming, Radaddel and the current trade sheet). A genuine repackaging - current barcode 5011921156771 should be primary, retired 5011921131174 kept as an additional EAN. But a plain fold of the old code will NOT clear the conflict, because Game Nerdz still lists the retired barcode 5011921131174 under GW short code GWS52-21, which does not normalize to the old 11-digit code, so that barcode stays a primary candidate.
  - *Recommendation:* Confirm the repackaging, then handle the Game Nerdz observation (sku GWS52-21 -> barcode 5011921131174) separately - via an override forcing additionalEans, since folding old code 99120108034 alone leaves the retired barcode asserted by a short-code retailer listing and the conflict persists.

- **Akhelian King** (`99120219028`, repackaging-needs-direction): Idoneth Deepkin dual-build plastic kit that makes EITHER the Akhelian King OR Volturnos, High King of the Deep, from one box (GW lists both names against the same current code 99120219028). Two GW product codes exist for the same kit: old code 99120219017 and the current unified code 99120219028 — both are the same physical product. This one is genuinely ambiguous on WHICH barcode is current: every retailer (Goblin Gaming, Radaddel), the legacy import, and the current catalog primary all use 5011921173563, while ONLY GW's trade row for the current code 99120219028 carries a different barcode 5011921229499. No clean join exists because 5011921173563 is asserted on the surviving code by legacy-catalog (two rows) and Goblin Gaming, so a fold of the old code can't resolve it.
  - *Recommendation:* Keep both barcodes; needs a human decision on primary. Recommended: keep 5011921173563 as primary (retailer + market + current-primary consensus) and add 5011921229499 to additionalEans — but verify against a physical current box, because GW's trade sheet assigns 5011921229499 to the current product code 99120219028, which conflicts with every retailer. Do not apply a blind join.

