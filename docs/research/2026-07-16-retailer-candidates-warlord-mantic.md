# Retailer candidates for Warlord Games / Mantic Games EAN coverage (2026-07-16)

Live probe of new retailer sources to close the EAN gap concentrated in **Warlord
Games** (~33% EAN) and **Mantic Games** (~29%), toward the plan's **≥60% overall**
gate. Catalog stands at ~55.2% (10,152 EANs / 18,392 products); the gate needs roughly
**880 more EANs** (see `docs/research/2026-07-13-campaign-results.md`). Each candidate
below was probed with a handful of polite requests: robots.txt first, then platform +
brand-depth + a barcode-fill sample. All example GTINs are verbatim from live
`/products/<handle>.js` or product-page markup on the probe date.

---

## The one insight that reframes yield

An EAN is a **global** product identifier: the same Warlord/Mantic product carries the
**same** barcode at every retailer (verified — `17-pdr…winter-crew` is `5060917995887`
on both Athena Games and The Combat Company). So a new retailer's value is **not**
"different barcodes." It is **reaching catalog products that are currently EAN-less**.
That makes two properties decisive, and Athena Games has both:

1. **Depth** — how much of the ~5,800-SKU Warlord and ~2,800-SKU Mantic ranges it
   carries (deeper than Goblin/Tistaminis, which the campaign showed publish at 85-100%
   but stock only a few hundred SKUs each).
2. **Publishing barcodes on out-of-stock / discontinued items** — directly attacking the
   6,146 "live-but-EAN-less" pool *and* the archive-adjacent back-catalogue.

---

## Executive summary — ranked shortlist

| # | Candidate | Platform / region | robots | Warlord depth | Mantic depth | Barcode fill (sampled) | Est. barcoded observations | Est. **net-new** EANs toward gate |
|---|---|---|---|---|---|---|---|---|
| **1** | **Athena Games** (`athenagames.com`) | Shopify / UK | ClaudeBot OK | **774** | **312** | **~90-100%** (8/8, incl. OOS) | ~980 | **~370-670** |
| 2 | **The Combat Company** (`thecombatcompany.com`) | Shopify / AU | **ClaudeBot explicit Allow** | **492** | none | **~86%** (6/7) | ~420 | ~30-80 (Warlord barcodes overlap #1; AU/OOP tail + corroboration) |
| 3 | **Board Game Bliss** (`boardgamebliss.com`) | Shopify / CA | ClaudeBot OK | 27 (shallow) | **96** | good (Mantic sample OK) | ~90 | ~30-60 (Mantic redundancy) |
| 4 | **Gap Games** (`gapgames.com.au`) | Shopify / AU | ClaudeBot OK | 391 | ~0 | **low ~17%** (1/6) | ~66 | ~20-40 |
| 5 | **Mighty Lancer Games** (`mightylancergames.co.uk`) | Shopify / UK | ClaudeBot OK | 25 (shallow) | 31 (shallow) | ~100% (2/2) | ~56 | ~20-40 |

**Headline:** **Athena Games is the single highest-yield new source found, and is
plausibly sufficient on its own to carry coverage most of the way to 60%** — it is the
only new store that stocks **both** target brands deeply, publishes 13-digit GS1 EANs at
~90-100% fill, publishes them **even on out-of-stock items**, uses vendor tags already in
our taxonomy (**no new aliases needed**), and sits on the exact `shopify` strategy we
already run for Goblin Gaming and Tistaminis. Adding The Combat Company (Warlord
corroboration + AU tail) and Board Game Bliss (Mantic redundancy) de-risks the estimate.
The plausible combined net-new (~470-890) brackets the ~880 needed.

**Two surprises worth flagging:**

- **A Cloudflare "Content-Signal" managed robots.txt that names `ClaudeBot` with
  `Disallow: /` is now deployed across multiple UK/DE wargaming retailers** — Firestorm
  Games, **Caliver Books** (a Warlord/Partizan Press specialist we'd have wanted most),
  and Battlefield Berlin all carry the identical block (`Content-Signal:
  search=yes,ai-train=no,use=reference` preamble + a fixed AI-crawler disallow list).
  This is a growing, politely-off-limits class — not a data-absence signal.
- **Alphaspel (SE) stocks Warlord and Mantic deeper than anyone else found (~650 / ~270)
  and permits ClaudeBot — but exposes no EAN at all**, only the manufacturer SKU
  (`WGB-402013103`). Its PrestaShop `ean13` field is unpopulated / not emitted. Deep
  stock ≠ published barcodes.

---

## Per-candidate detail

### 1. Athena Games — `athenagames.com` — Shopify, UK — TOP PICK

- **robots verdict: PERMITTED.** Standard Shopify `robots.txt`, no `ClaudeBot` mention
  (so the generic `*` group governs, which `Allow: /` for products/collections). No
  `Crawl-delay`. `Sitemap: https://athenagames.com/sitemap.xml`. **Caveat for the
  descriptor:** the `*` group disallows `/collections/*+*`, `/collections/*sort_by*`,
  `/collections/*filter*&*filter*`. Production enumeration must therefore use
  `/products.json` (allowed) — **not** the `/collections/vendors?q=X+Y` filter URLs (the
  "+" matches `/collections/*+*`). *Transparency note: my manual depth probes did hit a
  few `…?q=Warlord+Games` URLs; the acquisition strategy itself never needs them.*
- **Brand depth (live):** vendor `Warlord Games` = **774** products (33 pages); vendor
  `Mantic Games` = **312** products (147 in stock / 165 out of stock), spanning Kings of
  War, Armada, Deadzone, Firefight, Halo Flashpoint, Walking Dead. This is **the only new
  store deep in both target brands** and it carries other tracked brands too (GW,
  Chaosium, etc. seen in the bulk feed) — bonus coverage.
- **Barcode fill — 8/8 sampled populated with valid 13-digit GS1 GTINs, across every
  line, including an out-of-stock item:**
  | handle | vendor | sku | barcode |
  |---|---|---|---|
  | `17-pdr-anti-tank-gun-with-british-infantry-winter-crew` | Warlord | 403401002K | `5060917995887` |
  | `bolt-action-stug-iii-ausf-d-assault-gun` | Warlord | 402412003 | `5060393706311` |
  | `bolt-action-starter-set-band-of-brothers-third-edition` | Warlord | 401510007 | `5060917994538` |
  | `a-storm-in-the-shires-2-player-set-kings-of-war` | Mantic | MGKWM115 | `5060924980494` |
  | `abyssal-dwarf-army-kings-of-war` | Mantic | MGKWK112 | `5060469665184` |
  | `40mm-movement-tray-pack-kings-of-war` | Mantic | MGKWM08 | `5060469661605` |
  | `gcps-battlegroup` (Firefight) | Mantic | mgffg301 | `5060924983150` |
  | `halo-flashpoint-rise-of-the-banished` (Halo, **OOS**) | Mantic | MGHAB106 | `5060924985475` |
  Prefixes are genuine: Warlord `5060393` / `5060572` / `5060917`; Mantic `5060469` /
  `5060924`. Mantic SKUs (`MGKW…`, `mgffg…`, `MGHAB…`) match the taxonomy `codePattern`.
- **Enumeration confirmed:** `/products.json?limit=5&page=1` returns products with
  `vendor` + `handle`; the **bulk feed omits `barcode`** (platform-wide Shopify behavior).
  Barcodes come from per-handle **`/products/<handle>.js`**, which the **apex host serves
  directly (no `www` redirect)** — like Tistaminis, unlike Goblin Gaming.
- **Strategy fit:** `strategy: shopify` — identical to `ret-goblingaming` /
  `ret-tistaminis`. Descriptor hints:
  ```
  id: ret-athenagames
  kind: retailer
  strategy: shopify
  baseUrl: https://athenagames.com     # apex serves /products/<handle>.js directly
  scope:
    currency: gbp
    # No scope.vendors: taxonomy attribution governs inclusion (like un-scoped goblin/tista).
    # Vendor tags "Warlord Games" and "Mantic Games" are ALREADY in
    # data/catalog/taxonomy/manufacturers.yaml vendorNames -- NO new aliases needed.
  politeness: { rps: 0.5 }
  contract: { minCount: <conservative floor from first sweep>, maxDropPct: 30,
              requiredFieldRates: { name: 1.0, sku: 0.8 } }
  ```
  Budget: large general store (thousands of SKUs store-wide); a controller sweep should
  comfortably cover the ~1,086 Warlord+Mantic SKUs plus the other tracked brands.
- **Risks:** (a) Shopify's `/products.json` 25,000-cap could bite if the store is very
  large (`shopify.py` already handles this — forces `full_sweep=False`, as documented on
  `ret-tistaminis`). (b) Overlap with existing EANs reduces net-new below the ~980 raw
  observations; the depth + OOS-barcoding are exactly why net-new should still be large.

### 2. The Combat Company — `thecombatcompany.com` — Shopify, AU — Warlord corroboration

- **robots verdict: PERMITTED — `ClaudeBot` is *explicitly* listed with `Allow: /`**
  (only cart/checkout/account/orders/admin/password disallowed). `Nutch` fully blocked;
  `AhrefsBot`/`MJ12bot` `Crawl-delay: 10`; the generic `*` also disallows
  `/collections/*+*` (same enumerate-via-`/products.json` note as #1).
- **Brand depth:** vendor `Warlord Games` = **492** products (it is Warlord's AU
  distributor / historical specialist). **No Mantic** (`?q=Mantic` and `?q=Mantic+Games`
  both 404).
- **Barcode fill — 6/7 valid 13-digit GTINs across all lines:**
  | handle | sku | barcode |
  |---|---|---|
  | `17-pdr-anti-tank-gun-with-british-infantry-winter-crew` | 403401002 | `5060917995887` |
  | `crossing-the-rhine-british-canadian-infantry-winter-starter-army` | 402611002 | `5060917995245` |
  | `soviet-bt-7-fast-tank` | 402414002 | `5060393701606` |
  | `carro-armato-semovente` | 402018005 | `5060572502994` |
  | `korean-war-chinese-pva-infantry-squad` | 412218501 | `5060572503700` |
  | `church` (terrain) | 802010006 | `5060572501119` |
  | `25-pdr-light-howitzer-with-british-infantry-winter-crew` | 403401001 | `83106598` (8-digit, **not** GTIN-13) |
- **Strategy fit:** `strategy: shopify`; `baseUrl: https://www.thecombatcompany.com`
  (robots/store-id use `www`); `currency: aud`; vendor `Warlord Games` already mapped.
  The occasional 8-digit code (e.g. `83106598`) is harmless — the resolver already
  rejects anything that isn't a 13-digit GS1-valid GTIN.
- **Risks / positioning:** Warlord barcodes are the *same values* Athena publishes
  (global EANs), so this mostly **corroborates** #1 rather than adding volume. Its net-new
  is the AU-regional / out-of-print Warlord tail Athena lacks. Keep as a **redundancy +
  corroboration** source; it also independently de-risks the Warlord half if Athena drifts.

### 3. Board Game Bliss — `boardgamebliss.com` — Shopify, CA — Mantic redundancy

- **robots verdict: PERMITTED.** Standard Shopify `robots.txt`, no `ClaudeBot` mention;
  same `/collections/*+*` disallow (enumerate via `/products.json`).
- **Brand depth:** vendor `Mantic Games` = **96** products (Deadzone, Kings of War, etc.);
  vendor `Warlord Games` = only **27** (mostly OOS) — shallow on Warlord.
- **Barcode fill:** Mantic `deadzone-second-edition` (sku `MG-DZM103`) →
  `5060469667652` (valid 13-digit Mantic GTIN). Fill looked consistent on the sample.
- **Strategy fit:** `strategy: shopify`; `baseUrl: https://www.boardgamebliss.com`;
  `currency: cad`; vendor `Mantic Games` already mapped. **Value = a second, independent
  Mantic source** (the harder half of the gap), useful if Athena's Mantic coverage has
  holes.
- **Risks:** modest depth; net-new mostly bounded by overlap with Athena's Mantic set.

### 4. Gap Games — `gapgames.com.au` — Shopify, AU — deep Warlord but low fill

- **robots verdict: PERMITTED** (standard Shopify, no `ClaudeBot` mention).
- **Brand depth:** vendor `Warlord Games` = **391** (372 in stock). Mantic: essentially
  none — `/collections/mantic-games` returned a single non-Mantic item.
- **Barcode fill — LOW, 1/6:** only `8th-army-2-pounder-anti-tank-gun` had a barcode
  (`5060572502437`); `41m-turan-ii-medium-tank`, `4-7cm-panzerjager-r35-f-ba`,
  `a13-cruiser-tank-mk-iii-upgraded`, `alexander-the-great-philip-ii-of-macedon`,
  `ancient-britons-mastiff-packmaster` all `barcode: null`. Its SKUs carry a Gap-internal
  `" D"` suffix (e.g. `405107401 D`), suggesting a re-keyed import that dropped most
  barcodes.
- **Strategy fit:** `strategy: shopify`; `currency: aud`; vendor `Warlord Games` mapped.
  **Low priority** — deep but ~17% fill makes it a weak EAN contributor (~66 observations,
  most overlapping Athena/Warlord-store).

### 5. Mighty Lancer Games — `mightylancergames.co.uk` — Shopify, UK — high fill, shallow

- **robots verdict: PERMITTED** (standard Shopify; the robots even carries a human note
  that checkouts are for humans — no `ClaudeBot` restriction).
- **Brand depth:** `warlord-games-products` collection = **25**; `mantic-games` = **31**.
  Both shallow.
- **Barcode fill — good (2/2):** Warlord
  `konflikt-47-british-commonwealth-mk-iic-automated-director` (sku 453210603) →
  `5060917998086`. (Mantic collection populated with `MGKW…` SKUs.)
- **Positioning:** clean `shopify` fit and high fill, but too shallow to move the gate on
  its own. Marginal / opportunistic add.

---

## Disqualified

| Candidate | Platform | Reason |
|---|---|---|
| **Firestorm Games** (`firestormgames.co.uk`) | Cloudflare-managed | **robots.txt `User-agent: ClaudeBot` → `Disallow: /`** (Content-Signal managed block). Also had no EAN in prior probe. |
| **Caliver Books** (`caliverbooks.com`) | Cloudflare-managed | **robots.txt `ClaudeBot Disallow: /`** (same managed block). The Warlord/Partizan-Press specialist we'd most have wanted — off-limits by policy. |
| **Battlefield Berlin** (`battlefield-berlin.de`) | Cloudflare-managed | **robots.txt `ClaudeBot Disallow: /`** (same managed block). |
| **Dark Sphere** (`darksphere.co.uk`) | — | robots.txt `User-agent: *` → `Disallow: /` (blocks all crawlers). |
| **Alphaspel** (`alphaspel.se`) | PrestaShop, SE | **Permitted + deepest stock found (~650 Warlord, ~270 Mantic) — but NO EAN/GTIN in markup**, only manufacturer SKU (`WGB-402013103`, `WGB-402011008`). Two product pages checked, both SKU-only. *Caveat: worth one raw-HTML re-check for a hidden `gtin13`/`ean13` before final closure.* |
| **Michigan Toy Soldier** (`michtoy.com`) | custom, US | **Permitted (no robots.txt = allow-all) but NO EAN** — product markup carries only the manufacturer part number (`WLG-402613102`), no JSON-LD/microdata gtin. Deep Warlord historical range, useless for EAN (same profile as Noble Knight). |
| **Miniaturicum** (`miniaturicum.de`) | JTL-Shop, DE | Permitted and exposes `gtin13` (a known Tier-1 EAN site from the 2026-07-12 probe) — **but shallow for this mission**: the Warlord-Games category is **6 products** (books only). Fine for GW, not for the Warlord/Mantic gap. |

Prior known dead-ends (not re-probed, per campaign docs): **Wayland Games**
(PerimeterX), **Element Games** / **Miniature Market** (no usable barcodes), **Noble
Knight** (MPN only), **CMON** (no barcodes exist), free barcode DBs (barcode-in only,
exhausted). **Fantasywelt** remains ethically off-limits (`ClaudeBot` disallowed) — not
proposed.

---

## Not fully assessed (lower-priority follow-ups)

- **Chaos Cards** (`chaoscards.co.uk`) — custom "evocms", **permitted** (`Crawl-delay: 3`,
  product pages allowed) but a WAF returned **HTTP 403** to WebFetch on a category URL.
  EAN exposure unknown; needs a real-browser check before judging.
- **Spelexperten** (`spelexperten.com`) — Swedish "iButik" platform, **permitted**
  (`*` allows all but admin). Depth and EAN exposure untested (given Alphaspel's SE-shop
  SKU-only result, expectation is low).
- **Common Ground Games** (`commongroundgames.co.uk`) — DNS/connection timed out on both
  probe attempts; retry later.
- **Zatu/Big Orbit, War-Toys / Wargames Delivered, Igiari, Bits of War, Brückenkopf
  shops** — not deep-probed (board-game-led or bits-maker profiles; low expected
  Warlord/Mantic-with-EAN depth).

---

## Recommended next actions

1. **Build `ret-athenagames` first** (`strategy: shopify`, `baseUrl:
   https://athenagames.com`, `currency: gbp`, no `scope.vendors`). No taxonomy change
   needed — `Warlord Games` and `Mantic Games` are already mapped. Enumerate via
   `/products.json` pagination + per-handle `/products/<handle>.js` for barcodes; **do not
   use `/collections/*?q=…+…` filter URLs** (robots-disallowed). This is the single
   highest-yield action toward the 60% gate and the only new source deep in **both**
   target brands, publishing barcodes even on OOS items.
2. **Add `ret-thecombatcompany`** (`shopify`, `baseUrl:
   https://www.thecombatcompany.com`, `currency: aud`) as Warlord corroboration + the
   AU/OOP tail. Its `ClaudeBot Allow: /` is the cleanest permission of the set.
3. **Add `ret-boardgamebliss`** (`shopify`, `baseUrl: https://www.boardgamebliss.com`,
   `currency: cad`) as an independent **Mantic** redundancy source (the harder half).
4. **Re-verify Alphaspel with raw HTML** for a hidden `gtin13`/`ean13` before final
   closure — it is the deepest stock found and permitted; if any EAN surfaces it becomes a
   top-3 source overnight. If confirmed SKU-only, close it out.
5. **Defer** Gap Games (low fill) and Mighty Lancer (shallow) unless a first Athena sweep
   still leaves the gate short; both are clean `shopify` adds if needed.
6. **Do not** re-attempt Firestorm / Caliver / Battlefield Berlin / Fantasywelt — the
   `ClaudeBot` disallow is a deliberate, honored constraint, not a data-absence finding.

## Verification

Depth figures are live vendor-collection / manufacturer-page counts on 2026-07-16.
Barcode-fill samples are verbatim `sku`/`barcode` from live `/products/<handle>.js`
(Shopify) or product-page markup, one row per request. All cited GTINs are 13-digit GS1
values with genuine Warlord (`506039x`/`506057x`/`506091x`) or Mantic
(`5060469`/`5060924`) prefixes. robots verdicts are from each site's live `robots.txt`.
