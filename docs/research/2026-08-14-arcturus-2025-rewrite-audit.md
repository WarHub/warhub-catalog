# Auditing the 2025-03-27 upstream rewrite for a second P3 (2026-08-14)

PR #132 retracted 37 Formula P3 rows that upstream's 2025-03-27 rewrite had transcribed from a
Nov-2019 chart of an **expanded line that was announced and never shipped**. Privateer Press sold
the brand to Steamforged before most of it existed, and the chart was the only source those 37
names ever had.

The rewrite is one commit (`Arcturus5404/miniature-paints` `b180abb` → `22791a6`) and it rewrote
**every** `paints/*.md`. So the open question was not whether P3 was fixed but whether the same
transcription happened to any other brand. **It did not.** The rewrite's additions are, brand for
brand, better evidenced than the material that predates them. What it did leave is a different and
much smaller defect: four Army Painter paints published twice, once under a misspelling.

## Method

A line diff is useless here — the rewrite changed the file format from an HTML `<table>` to a
markdown pipe table, so it reads as 11,578 insertions against 112,052 deletions, nearly all of it
formatting. The rows have to be parsed out of both formats and compared as sets.

**Compared on names, not on `(name, set)`.** Upstream's `Set` column does not hold a set name in
most files: Army Painter holds product codes (`CP3001`) or the literal string `null`, Mr Hobby
holds codes (`H57`, `SG14`), and only a few files (P3, GreenStuffWorld) hold anything resembling a
range. The rewrite also changed that column wholesale, so a `(name, set)` diff counts set-churn as
additions and scores Army Painter at +467/−238 — of which almost none is a new paint. The name is
the only field whose meaning survives the rewrite, so it is the only honest join key.

Each added name was then scored against three signals WarHub holds independently of upstream: a
barcode, a manufacturer product code, and presence in a committed manufacturer harvest. The P3
contamination signature is all three absent.

**An uncorroborated row is not automatically contamination** — a real paint can simply be missing
from the harvests that have been run. What identifies contamination is the *contrast* with the
brand's own baseline. If the added rows are markedly less evidenced than the rows that predate
them, the addition is the anomaly; if they are better evidenced, the addition is a real range.

## Result

1,531 distinct names added across the 20 brands WarHub publishes. Barcode coverage of the added
rows against the brand's pre-existing rows:

| brand | added | with barcode | with code | in harvest | baseline barcode |
|---|---|---|---|---|---|
| army-painter | 225 | **92%** | 5% | 97% | **51%** |
| vallejo | 172 | 100% | 100% | 97% | 100% |
| mr-hobby | 391 | 59% | 100% | 85% | *(new file)* |
| ak-real-color | 251 | 0% | 100% | 0% | *(new file)* |
| mission-models | 201 | 0% | 100% | 0% | *(new file)* |
| green-stuff-world | 71 | 99% | 0% | 55% | 98% |
| monument-pro-acryl | 64 | 100% | 100% | 100% | 95% |
| turbo-dork | 40 | 100% | 0% | 100% | 100% |
| scale75 | 28 | 0% | 22% | 92% | 0% |
| kimera-kolors | 26 | 0% | 54% | 0% | 0% |
| tamiya | 20 | 0% | 100% | 0% | 0% |

Army Painter is the clearest case and the one most worth stating: the rewrite's additions there
are the Warpaints Fanatic and Speedpaint 2.0 ranges, and they carry a barcode **92%** of the time
against **51%** for the rows that predate them. That is a real range refresh, not a transcription.

Four of the eight files with no pre-rewrite baseline are new published brands (AK Real Color,
Mission Models, Mr Hobby, Turbo Dork — 1,162 rows); the other four are craft brands
`BrandRegistry` excludes and WarHub never publishes.

Only **23** added rows still published carry none of the three signals: 12 Kimera Kolors, 7 Army
Painter, 3 Scale75, 1 Green Stuff World. Kimera's baseline barcode coverage is 0%, so 0% on its
additions is that brand's normal state rather than a finding.

## What it did leave: four paints published twice

| retracted (misspelled) | manufacturer's spelling | code | dRGB |
|---|---|---|---|
| Boney Spikes | Bony Spikes | WP3089P | 8.0 |
| Brigadine Brown | Brigandine Brown | WP3073P | 28.0 |
| Terrestial Titan | Terrestrial Titan | WP3127P | 2.3 |
| Violent Vermillion | Violent Vermilion | WP3107P | 4.7 |

The mechanism is the name-match miss. The misspelled row arrives from the base parse (firstSeen
2026-07-23); the next day the manufacturer harvest offers the correct spelling,
`HarvestApplier.ApplyEnrichment` keys on `{Name}|{Set}`, misses by one letter, and
`AppendAdditions` mints the correct name as a **second** paint (firstSeen 2026-07-24) carrying the
barcode, the product code and its own colour. Both then publish.

The manufacturer settles the spelling, not a similarity score: thearmypainter.com lists all four
correct forms and none of the four misspellings. Retracted rather than aliased — each misspelled
row holds no barcode and no product code, its only unique content is a hex the survivor already
has independently, and an alias would assert the two are one record and move history onto a colour
that is already there.

**Colour proximity alone is not a usable signal for this.** A sweep for evidence-less rows whose
hex sits within dRGB 10 of an evidenced row in the same set returns 30 hits in Army Painter and 61
in Scale75, nearly all of them false (`Deep Blue` ~ `Anthracite Grey` at 2.3 — both merely dark).
It is name proximity *plus* colour *plus* the manufacturer's own list that identifies a duplicate.

## Two findings left open (the first has since been closed)

**Scale75's Artist Range has a misspelling cluster that predates this rewrite.** *(Resolved — see
"The Artist Range pass" below.)* Chasing the three uncorroborated Scale75 rows turned up
`Yellow Ocre` (`#A0702E`, a proper ochre) sitting beside the harvest's `Yellow Ochre` (`SART-20`,
no hex) — and `Yellow Ocre` is *not* one of the rewrite's additions. `Crimsom`, `Prusian Blue`,
`Artic Blue` and `Chesknut Ink` are the same shape. Merging the pairs would lose the Arcturus hex
because the harvest-side records have none — the survivor needs the colour moved onto it first,
with the alias that identity move requires.

One claim here was wrong and the pass corrected it: *"79 of the range's 91 records carry no product
code, so the harvest enriched barely a tenth of it."* A missing `productCode` does not mean the
harvest missed. `HarvestApplier.ApplyEnrichment` fills **only** a blank Ean/ImageUrl and never
writes ProductCode or Hex — they are identity-key components and it says so outright
(`HarvestApplier.cs:20-23`). The code appears only on the `additions` path, i.e. on the paints the
name-match *missed*. So a code is a marker of failure here, not of success: the harvest matched 70
of the 91 exactly, and the count of code-less rows was measuring the wrong thing.

## The Artist Range pass

Seven pairs, merged. The range is settleable outright because the manufacturer publishes it
completely: scale75.com lists `SART-01` … `SART-84` with **no gaps**, and against that list the
archive's 91 Artist Range records partition exactly — 70 Arcturus rows matching a SART product by
name, 13 SART products minted as `additions` because the name missed, 1 contested (`Titanium Grey`),
and 7 Arcturus rows matching no SART product at all. Those 7 are the misspellings, `91 − 7 = 84`,
and 0 of the 84 SKUs fail to name a record. A bijection, not a similarity score.

| retracted (misspelled) | manufacturer's spelling | code | hex moved |
|---|---|---|---|
| Artic Blue | Arctic Blue | SART-44 | `#888FA1` |
| Chesknut Ink | Chestnut Ink | SART-84 | `#40362D` |
| Crimsom | Crimson | SART-10 | `#C22335` |
| Naples Yellow | Yellow Naples | SART-18 | `#DAAC22` |
| Prusian Blue | Prussian Blue | SART-30 | `#06293D` |
| Yellow Ocre | Yellow Ochre | SART-20 | `#A0702E` |
| Yellow Oxide | Oxide Yellow | SART-56 | `#4B3527` |

Two are word **order**, not typos, and one of those was the doubtful case: `Yellow Oxide` `#4B3527`
looked too dark to be an ochre. It is the same paint anyway, and the store settles it without the
colour being consulted at all — the product's title is `OXIDE YELLOW` and its own slug is
`/products/yellow-oxide`. One maker, two spellings, one bottle, exactly like P3's
`Meridius`/`Meredius Blue`. That is the right order of proof: the hex was the thing in doubt, so it
could not also be the witness.

**A better name-match in the bridge would not have fixed this, and would have made it worse.** The
tempting class fix — teach `bridge_scale75` to match `YELLOW OCHRE` to `Yellow Ocre` — stops the
twin being minted but leaves the misspelling published *and* silently drops the seven product
codes, because `enrich` writes neither ProductCode nor Hex by design. It converts "two records, one
correct" into "one record, wrong name, no code". Only an override can correct a name, so the
instances are the right unit of repair here; the bridge is untouched and regenerates byte-identical.

`retract:` removes the misspelled row and a paired `hex:` override moves its colour onto the
survivor. The alias that identity move requires is **not** hand-written: `PaintCatalogApp.cs:490`
already auto-aliases every hex-carrying fresh identity to its own empty-hex key, which is exactly
this direction, so the archived record merges and keeps its history. (The `colourless:` entries run
the other way and must still be authored by hand.) 8,528 → 8,521 records, each survivor keeping
`firstSeen: 2026-07-24`; `--ean-guard` exit 0 — scale75 publishes no barcodes at all, so none moved.

What is lost is the retracted row's earlier `firstSeen` of 2026-07-10, and that is forced rather
than chosen: an alias onto the Arcturus row would be refused (the base re-asserts that key every
run, so `consumed` claims it) and an alias onto a retracted key is skipped outright.

### `Titanium Grey` is not a misspelling — and the contested key is settleable after all

It was on the suspect list and it does not belong there: scale75 spells it `TITANIUM GREY`
(`SART-60`) and so does the archive. It is the contested key `bridge_scale75` documents — `SART-60`
and Warfront's `SW-40` share that title, `add_enrich` refuses both, and the Artist Range record
still carries the **wrong bottle's** photo and price (`SW-40`'s `4254.jpg`, EUR 2.25).

The bridge defers it on the grounds that settling it would force `SW-40` to mint a new
`Titanium Grey|Warfront  Range` "on the strength of one store collection tag". **That premise no
longer holds.** Warfront already has the record: `Titanium Gray` `#41342B`, Arcturus-origin, no
code — American spelling, so the in-set match misses and `SW-40` falls through to the brand-wide
lookup, where the Artist Range row is the unique `titaniumgrey`. Correct the Warfront row's
spelling and both SKUs match in-set, the contest disappears, and nothing is minted. Same defect
class as the seven above, one range over. Left out of this pass because it renames a published
record in a different range on a gray/grey judgement the archive makes inconsistently elsewhere
(`Brown Grey`/`brown-gray`, `Field Grey`/`field-gray`, `Ocean Grey`/`ocean-gray` are all the same
shape) — that is a maintainer's call, not a transcription fix.

**Kimera Kolors' 12 signature-set rows are unverified in both directions.** Two artist Signature
Sets (Danilo Cartacci, Michal Pisarski) with no barcode, no code and no harvest — but the brand has
no barcode coverage at all, so there is nothing to contrast them against. Unlike P3's 37 there is
no positive evidence they never shipped. They need a manufacturer source before anything is done,
not a retraction on absence of evidence.
