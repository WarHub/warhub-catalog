# Source probe: manufacturer/distributor trade order sheets (2026-07-16)

Evaluation of **trade order sheets** (weekly/monthly new-release forms, price lists,
trade-catalogue CSV/XLSX) as a bulk EAN source for the catalog. The premise under test:
trade order forms are manufacturer-authoritative EAN↔SKU↔name mappings, published to
retailers and often publicly linked, so an archive of them could recover the full
historical GW barcode range (incl. the ~2,000 archive-only discontinued products) and,
via distributors, close the Warlord Games and Mantic gaps (~30% EAN each). Run 2026-07-16
via `curl.exe`, Wayback CDX, and web search at ≤1 req/s. No production code written.

## Executive summary — verdict: LOW viability for EAN recovery

**The premise does not hold for publicly-reachable trade materials.** Every trade sheet
we could reach without credentials carries either **no EAN at all** (GW's public price
lists and release packs use GW's internal 11-digit code, not the GS1 EAN-13) or the same
Shopify data the catalog already harvests. The trade sheets that *do* carry barcodes —
GW's detailed stockist order forms — sit behind a password-gated Resources section and are
governed by a Trade Agreement that classifies them as **Confidential Information** with an
explicit **anti-ML/AI-processing clause**. They are disqualified twice over (auth wall +
terms), not just once.

**Estimated NEW EAN yield:**

| Target | Public trade-sheet EAN yield | Why |
|---|---|---|
| GW history (incl. ~2,000 discontinued) | **~0 new EANs** | Public GW trade sheets carry the GW 11-digit code + name + price, never the GS1 EAN-13. The EAN-bearing forms are login-walled + Confidential. |
| Warlord Games (3,979 missing) | **~0 new EANs** | Trade Shopify store has `barcode:null` and no page gtin; the Excel/CSV trade export is behind the gated Trade Hub. |
| Mantic (1,983 missing) | **~0 new EANs** | No public trade order form exists at all. |

**The single most promising vein found is a consolation prize, not the EAN goal:** the GW
trade upload archive on Wayback (`trade.games-workshop.com/wp-content/uploads/*`, **2 CDX
pages, 1,914 distinct 200-status files, captures 2014-05 → 2026-05**) is a
manufacturer-authoritative record of **name ↔ GW-11-digit-code ↔ price ↔ release-date**,
including discontinued products. It **originates zero EANs** but supplies the GW internal
code as a *join key* for EANs discovered from retailers — largely duplicating the existing
`arc-gw-webstore` source, and carrying the same terms baggage. Recommendation: **do not
build a `trade-sheet` strategy for EAN recovery.** Keep investing in the retailer-per-page
and archived-Shopify veins (2026-07-13 coverage doc), which originate genuinely new EANs.

---

## 1. trade.games-workshop.com surface

**robots.txt — fully open** (re-confirmed 2026-07-16): `User-agent: *` / empty `Disallow:`
/ sitemap `http://trade.games-workshop.com/sitemap_index.xml`. A Yoast-generated WordPress
site behind Cloudflare.

**Sitemap enumerates only marketing pages — not files.** The index lists `page-sitemap.xml`
+ five `article-sitemap*.xml`. `page-sitemap.xml` is ~110 URLs, all
localized landing pages (`/`, `/articles/`, `/resources/`, `/get-in-touch/`,
`/common-questions/`, `/privacy-notice/`, `/start-here/`, `/discover-warhammer/`) across
~16 locales. **There is no product sitemap and no media sitemap** — `wp-content/uploads`
files are never listed, so the sitemap gives no route to order forms.

**Public direct-URL files exist but are legal/marketing collateral, not product data.** A
search engine surfaced `wp-content/uploads/2025/05/7TLQKx9MwSsyNp8o.pdf` (obfuscated
filename, 200 OK, `application/pdf`, 393 KB, no auth) — sampled, it is GW's **"Rest of
World Trade Terms" (June 2025)** legal document, not an order form. Note the filename
pattern: GW switched WP uploads from descriptive names to random obfuscated strings around
late 2020 (a deliberate move to keep direct URLs unguessable while remaining technically
public).

**The order forms themselves are password-gated.** `trade.games-workshop.com/resources/`
returns a password-protected page (login markers present in HTML). The public
`/article/latest-order-forms/` article states the forms live "in the Resources section
(Guidance Docs – Order Forms)" — i.e. behind that gate. A public-web description confirms
these gated forms *do* carry barcodes ("barcodes of latest White Dwarf magazines"; "stores
receive a product pricing spreadsheet and put in want numbers"). **So EAN-bearing GW trade
sheets are real — and they are exactly the ones we cannot reach without credentials.**
Public New-Releases articles (`/article/new-releases-163/`) carry no clickable download;
the pack link is inside the gated resources.

## 2. Wayback Machine history — GW trade uploads

CDX enumeration works on the trade domain (queries per the 2026-07-12 web-archive probe's
verified shape). `showNumPages`: `trade.games-workshop.com/*` → 3 pages;
`trade.games-workshop.com/wp-content/uploads/*` → **2 pages**. Pulled both uploads pages
(`output=json&collapse=urlkey&fl=original,timestamp,statuscode`) → **1,914 distinct
200-status files**, capture timestamps **2014-05-19 → 2026-05-23**. File-type breakdown of
the document-bearing subset:

| Type | Count | What they are |
|---|---:|---|
| `.pdf` | 85 | **All legal/marketing collateral** — Trade Terms, Stockist Agreements, Conditions of Sale, Text & Imagery Licences, Account Application forms, paint-rack planograms, Age-of-Sigmar rules sheets, Hobbit invites. **No product/barcode data.** |
| `.zip` | 113 | Weekly release/promo **image asset packs** (16 explicitly `New-Releases-DDMMYY.zip`, 2019–2020; obfuscated-name packs 2020+). Year spread 2019:11 → 2025:28. |
| `.xlsx` | 1 | `RoW-Price-Change-05_15.xlsx` (2015) — a price-change list. |

**Sampled the xlsx** (`.../2015/05/RoW-Price-Change-05_15.xlsx`, capture `20160418102245`,
via the `id_` raw-replay form). Parsed cleanly (openpyxl-style: it is a normal
OOXML zip). Columns: **`Code`** (GW 11-digit product codes, e.g. `99179950001`),
**`Category`** (Paint / Spray / Tools / Glue / Scenery / …), and **New Price / Old Price ×
US$ / CA$ / AU$ / NZ$**. Critically: of 176 thirteen-digit values in the sheet, **zero
start with `5011921`** (GW's GS1 retail EAN-13 prefix, per `EanEnricher`) — they are the
11-digit code plus a 2-digit pack suffix, i.e. GW-internal codes, **not retail barcodes**.
There is **no EAN/Barcode/UPC column and no product-Name column** — only Code + Category +
prices. This 2015 public price list is *weaker* than the old-webstore archive, which at
least yields a name.

**Sampled a New-Releases zip** (`.../2019/05/New-Releases-25052019.zip`, 41 MB; read its
central directory via an HTTP range request — Wayback honored `206`, no full download).
Contents are **only JPEGs**, named `{GW-11-digit-code}_{ProductName}.jpg` (e.g.
`60040599021_NECBookofPeril01.jpg`, `99120599010_KalJerichoandScabsBox.jpg`). No
spreadsheet, no order form, **no barcode** — just a name↔code mapping embedded in
filenames.

**Conclusion for GW:** every publicly-archived GW trade artifact (price xlsx, release-pack
image filenames) carries the **GW internal 11-digit code + name + price**, never the GS1
EAN-13 — perfectly consistent with every prior probe (GW's own web properties expose no
EAN anywhere; only retailers do). This vein cannot originate EANs. Its only value is
name↔code↔price↔release-date recovery for discontinued GW products, which the existing
`arc-gw-webstore` source (gw-legacy extractor) already does from the old webstore.

## 3. Other public mirrors of GW trade sheets

No public mirror of the EAN-bearing GW order forms was found. Searches for leaked/mirrored
GW order-form spreadsheets (retailer forums, DakkaDakka, Reddit, wargaming news) returned
only GW's own gated pages and commentary. Distributor angle (the maintainer's Alliance /
ACD / GTS / Asmodee / PHD hypothesis):

- **Alliance Game Distributors** (`alliance-games.com`): retailer ordering system is
  login-gated; the only public downloads are `newaccount.pdf` (account application) and
  `alliancemanufacturerlisting.pdf` (a vendor list) — **no product UPC order form**.
- **PHD Games**: catalog/new-releases/pre-orders sit behind `portal.phdgames.com` (gated).
- No distributor publishing a **public** monthly order form with a UPC/EAN column was
  found for any tracked manufacturer. Distributor UPC order sheets exist but live behind
  retailer portals.

## 4. The actual gap — Warlord Games and Mantic

**Warlord Games** — three surfaces checked:

- `trade.warlordgames.com` is a **Shopify trade store** with standard-Shopify robots
  (`Allow: /`) and an **open `products.json`**. But per-handle `/products/<h>.js` returns
  **`"barcode":null`** (Shopify strips barcode from JSON on every store — the cross-cutting
  2026-07-12 finding), and product **pages carry no `gtin`/`barcode`** in markup (checked a
  magazine and a miniature). This is *worse* than the retail store `store.warlordgames.com`,
  whose pages *do* emit `gtin13` in JSON-LD (the known-pending per-page harvest, README
  headline #1). The trade store adds no EAN.
- `www.warlordgames.com/trade-sales/` is flagged "outdated" and redirects to the Trade Hub.
- **Trade Hub** (`tradehub.warlordgames.com`) is the real source of Warlord's "latest Excel
  trade order form" + "Excel/CSV trade products" + "database of product images by SKU" — but
  it is a **gated IIS app** (robots.txt → 404, `/downloads/` → 403 no listing, `index.php`
  → 404). Only known direct-URL legal docs are public
  (`/downloads/Warlord_New_TandCS_Trade_2024.pdf` = Conditions of Sale, a MAP/reseller
  policy). The order form/CSV is **behind login → disqualified.**
- Wayback: `trade.warlordgames.com/*` and `www.warlordgames.com/trade*` each = **1 CDX
  page** (tiny archive; recent Shopify store). No historical public order forms to mine.

**Mantic** — **no public trade order form exists.** `manticgames.com/stockists/` is a store
locator; trade/retailer resources route to gated apps (`companion.manticgames.com`,
`vault.manticgames.com`, Freshdesk support signup). `manticgames.com/trade*` Wayback = 1
CDX page. Mantic's own product pages already emit `gtin` in JSON-LD (2026-07-12 probe) — the
existing `mfr-manticgames` woo strategy with `gtinFromJsonLd` is the right lever, not a
trade sheet.

**Net:** for the two manufacturers that *are* the gap, the trade-sheet path is either
login-walled (Warlord) or nonexistent (Mantic). Retailer-per-page harvesting (Radaddel /
Game Nerdz) and the manufacturers' own per-page `gtin` remain the correct, higher-yield
levers.

## 5. Terms / ethics assessment

robots.txt being open is **not** the whole picture here, and this source class is
materially more terms-encumbered than the retailer/archive sources the repo already uses.

**Games Workshop Trade Terms** (sampled `7TLQKx9MwSsyNp8o.pdf`, RoW June 2025):

- **§14 Confidentiality.** "Confidential Information" is defined to include "unreleased
  product information … product specifications, product release dates … or any other
  commercially sensitive information." §14.1: Trade Accounts must "keep all Confidential
  Information … secret and confidential" and "only use [it] for the purposes of the Trade
  Agreement." Trade order forms (which carry unreleased products, prices, and advance-order
  dates) fall squarely inside this definition.
- **§19.7 (anti-ML/AI):** "Trade Accounts shall not input, use or process any of GW's
  Intellectual Property or Licensed IP … through any machine learning or artificial
  intelligence model or similar service."
- **§19.5:** no extracting/cropping artwork from Authorised Imagery.
- The public `/article/latest-order-forms/` page carries a site-wide notice: "Any use of
  website content to train generative artificial intelligence (AI) technologies is expressly
  prohibited."
- **Carve-out (§14.2.3):** confidentiality "shall not apply to Confidential Information
  which … is or becomes generally available to the public through no act or default of the
  Trade Account." This is the standard public-domain exception — a defence for a *trade
  account*, and the reason a file already in Wayback is not itself a breach to *read*. It
  does not grant a third party a positive licence, and it does not neutralize §19.7 or the
  site-wide AI-training notice.

**Assessment.** The catalog project is not a GW Trade Account and is not contractually bound
by §14/§19; factual EAN↔SKU↔name↔price tuples are not copyrightable. But GW's *expressed
intent* is unambiguous: trade materials are confidential to trade accounts, and GW
explicitly prohibits ML/AI processing of its IP and AI-training on its site content. For a
project that has historically tracked source-terms notes and treats a ClaudeBot disallow as
binding, that expressed intent should weigh as heavily as robots.txt. **Flag GW trade
materials as terms-restricted / avoid** — distinct from the neutral retailer sources — and
note this is largely moot because the public files carry no EAN anyway.

**Warlord** Conditions of Sale (public `Warlord_New_TandCS_Trade_2024.pdf`) is primarily a
**MAP (Minimum Advertised Price) / Authorized-Reseller conduct policy** plus a trade IP
licence; it is less aggressive on confidentiality/AI than GW's, but the product CSV it
governs is gated regardless. **Mantic**: no terms sampled (no public trade artifact).

## 6. Ingestion-strategy sketch (`trade-sheet`) — for the record

Even though the verdict is "don't build it," here is how it *would* slot into
`tools/acquisition` if a legitimately-public, EAN-bearing sheet ever appeared — and why the
architecture makes the terms question sharp.

**Shape.** A new `STRATEGIES["trade-sheet"]` (register in `acquire/strategies/`, mirroring
`cdx_archive.py`). Descriptor `kind: manufacturer` (or `archive` when fetched via Wayback),
`strategy: trade-sheet`, `baseUrl` = the host whose robots.txt gates the fetch
(`https://web.archive.org` for archived sheets, or the trade host for live ones).

**Scope fields:** `{ sheetIndex: [urls] | cdxUrlPattern, extractor: "xlsx-orderform" |
"pdf-orderform" | "zip-filenames", columnMap: {ean, sku, name, price}, manufacturer }`.
Enumeration is cheaper than CDX product enumeration (a handful of sheet URLs, or one CDX
uploads sweep cached in the cursor exactly like `cdx_archive.py`'s `url_index`).

**Fetch + parse:**
- Document fetch reuses `PoliteClient` (direct WP-uploads URL, or Wayback `/web/<ts>id_/…`
  raw replay — the same mechanism `cdx_archive.py` already uses).
- `xlsx-orderform`: parse OOXML with `openpyxl` (already a transitive dep via the `xlsx`
  tooling); a per-source `columnMap` names the ean/sku/name/price columns (header text
  varies per publisher). Validate EAN via the existing `ean.canonical_ean`.
- `pdf-orderform`: `pdftotext -layout` (or `pdfplumber`) → row regex; brittle, last resort.
- `zip-filenames`: the GW-release-pack pattern — parse `{code}_{name}.jpg` filenames from
  the zip central directory (range-fetchable, no full download). Yields name+code, no EAN.

**Observation mapping** (`models/observation.py`): one `Observation` per row —
`key=f"{descriptor.id}:{sku-or-path}"`, `name`, `sku`/productCode, `ean`, price*,
`hints={"sheetDate": …}`, `archived=True` when fetched from Wayback (so it can never flip a
new entity to `current`, per `resolve/attributes.py`), `full_sweep=False` always (a
budgeted slice of sheets is not a population census). Contract: `minCount: 0`,
`requiredFieldRates: {ean|sku: …}`.

**Provenance / confidence — the crux.** In `resolve/corroborate.py`, `KIND_PRIORITY` ranks
`manufacturer=1`, and `has_authoritative = any(kind in ("manufacturer","curated"))` →
**a single manufacturer-kind EAN assertion resolves to `confirmed` outright.** So a trade
sheet, being manufacturer-authoritative, *would* count as `confirmed`-grade corroboration
on its own — the strongest tier, above two agreeing retailers. This is precisely why the
terms flag matters: the strategy would elevate a terms-restricted source to top trust. And
it is moot for GW, because the public sheets carry no EAN to assert.

**Dedup / join.** Trade-sheet observations key on SKU; they would corroborate existing
`mfr-gw-algolia` / `arc-gw-webstore` records via the GW 11-digit code (the shared join key),
and existing Warlord/Mantic records via their manufacturer SKU. Because GW public sheets
carry code+name+price but no EAN, their realistic role is **metadata enrichment + join key**,
not EAN origination — the resolver would merge them as non-EAN evidence.

## 7. Ranked recommended next actions

1. **Do not build a `trade-sheet` acquisition strategy for EAN recovery.** Public trade
   sheets originate zero EANs; the EAN-bearing GW forms are auth-walled and terms-restricted.
   The premise is disproven for reachable materials.
2. **Prioritize the already-identified, EAN-originating veins instead** (2026-07-13 coverage
   doc): the pending per-page `gtin13` harvest of `store.warlordgames.com` (closes the
   Warlord gap directly), `mfr-manticgames` `gtinFromJsonLd`, and the Radaddel / Game Nerdz
   retailer sweeps (~3,797 projected new EANs). These beat any trade-sheet path decisively.
3. **(Optional, low priority) Widen `arc-gw-webstore`'s reach using the GW trade upload
   archive** as a *metadata/join-key* source only — not EAN. The 2019–2025 New-Releases
   image-filename packs give fresh name↔code↔release-date for discontinued GW SKUs the old
   webstore (2014–2019) misses. Gate this on the terms concern in §5: GW's anti-AI/ML and
   confidentiality posture argues against ingesting GW trade materials even though robots.txt
   is open. If pursued, treat it exactly like `arc-gw-webstore` (archived=True, no EAN) and
   record a source-terms note.
4. **Record GW trade materials as terms-restricted** in whatever source-terms register the
   repo keeps, so a future contributor doesn't re-litigate the open-robots.txt signal in
   isolation.
5. **Re-check nothing on a schedule.** Unlike drifting Shopify feeds, this verdict is
   structural (GW uses internal codes, not EANs, in trade docs; Warlord/Mantic gate their
   sheets) and will not change without GW/Warlord publishing EAN-bearing sheets publicly.

## Sources

- Live 2026-07-16 (`curl.exe`, ≤1 req/s, ClaudeBot UA): `trade.games-workshop.com/robots.txt`,
  `/sitemap_index.xml`, `/page-sitemap.xml`, `/resources/` (gated),
  `/wp-content/uploads/2025/05/7TLQKx9MwSsyNp8o.pdf` (Trade Terms, sampled);
  Wayback CDX `trade.games-workshop.com/wp-content/uploads/*` (2 pages, 1,914 files) and
  `/*`; archived `RoW-Price-Change-05_15.xlsx` (`20160418102245id_`) and
  `New-Releases-25052019.zip` (`20250109024259id_`, range-read); `trade.warlordgames.com`
  robots + `products.json` + per-handle `.js` + product pages;
  `tradehub.warlordgames.com/downloads/Warlord_New_TandCS_Trade_2024.pdf` (sampled) and
  gating probes; Wayback CDX for `trade.warlordgames.com/*`, `www.warlordgames.com/trade*`,
  `manticgames.com/trade*`.
- Web search 2026-07-16: GW latest-order-forms / new-release articles; Warlord Trade Hub /
  trade-sales; Mantic stockists / trade; Alliance / PHD distributor portals.
- Repo: `docs/research/2026-07-12-source-probe-manufacturers.md`,
  `docs/research/2026-07-12-source-probe-webarchive.md`,
  `docs/research/2026-07-13-coverage-arithmetic.md`;
  `tools/acquisition/src/warhub_acquisition/acquire/strategies/cdx_archive.py`,
  `.../acquire/runner.py`, `.../models/{descriptor,observation}.py`,
  `.../resolve/corroborate.py`; `data/catalog/sources/{arc-gw-webstore,arc-tistaminis,
  mfr-warlord-store,mfr-manticgames,ret-radaddel}.yaml`.
