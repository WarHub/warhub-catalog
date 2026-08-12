"""Generate data/paints/stores/<brand>.yaml — retailer barcode snapshots for a paint brand.

WHY a separate script. `gen_paint_harvest.py` is deterministic and reads only committed files;
it must stay that way. This is the on-demand NETWORK half, exactly like `gen_paint_swatches.py`:
run it by hand when a brand needs a barcode snapshot, review the diff, commit the result. The
harvest bridge then consumes the committed file offline.

WHY retailers at all. Some manufacturers publish no barcode anywhere. Mr Hobby (GSI Creos) is
the extreme case: mr-hobby.com is series-level only -- one page covers all of "Mr.COLOR
C1~C189" -- and carries no JAN/EAN, no per-colour page and no hex chip (live-probed 2026-07-24,
EN+JA; see data/catalog/sources/mfr-mr-hobby.yaml). The manufacturer source can therefore never
supply an EAN, so the brand's 668 catalog paints all sit EAN-less. Hobby retailers that stock
the range DO publish the JAN on each single, keyed by the manufacturer's own item code -- an
exact join, no fuzzy matching.

ROLE. Retailers are METADATA-ONLY, the same rule the harvest bridge applies to manufacturer
storefronts: a snapshot may fill a BLANK ean on an identity the catalog already has, and it may
propose candidates for review. It never mints a paint. Codes are taken verbatim from the store
sku; the brand-specific alias between a store sku and a catalog productCode lives in the
bridge, not here (evidence stays faithful to the store, and re-tuning the join must never
require a re-fetch -- same discipline as the acquire strategies).

WHY NOT an acquire source. These stores stock thousands of non-paint products (aztoyhobby.com:
8,913 products, 712 of them Mr Hobby). A `data/catalog/sources/ret-*.yaml` descriptor would
route every one of those observations into the PRODUCT resolver, which this paint-catalog work
neither owns nor can verify. The snapshot stays inside data/paints/, where the paint catalog
owns it end to end.

Config: data/paints/store-sources.yaml (per brand, ordered list of stores).
Output: data/paints/stores/<brand>.yaml -- {sku, ean, name, url, store} rows, sku-sorted, plus
the per-store provenance block (snapshot date, base url, scanned/matched counts).

    uv run --with pyyaml python tools/acquisition/scripts/gen_paint_store_barcodes.py [brand...]
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools/acquisition/src"))

from warhub_acquisition.acquire.client import PoliteClient  # noqa: E402
from warhub_acquisition.acquire.robots import fetch_policy  # noqa: E402
from warhub_acquisition.yamlio import dump_yaml  # noqa: E402

CONFIG = REPO / "data/paints/store-sources.yaml"
OUT_DIR = REPO / "data/paints/stores"
BOT_UA = "warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)"

# Shopify's /products.json caps at 250 per page and stops paginating past this; both limits are
# the platform's, not ours (see acquire/strategies/shopify.py, same constants).
PAGE_LIMIT = 250
MAX_PAGES = 40


def scan_shopify(client: PoliteClient, store: dict) -> tuple[list[dict], int]:
    """Bulk /products.json enumeration + per-handle /products/{handle}.js barcode fetch.

    Two passes because Shopify only exposes `barcode` on the .js detail: the listing pass is
    cheap and decides which handles are worth a detail request (vendor + product_type filters),
    so the expensive pass runs over paints only.
    """
    base = store["baseUrl"].rstrip("/")
    vendors = {v.casefold() for v in (store.get("vendors") or [])}
    types = store.get("includeTypes")
    listed: list[dict] = []
    scanned = 0
    for page in range(1, MAX_PAGES + 1):
        payload = client.get_json("/products.json", params={"limit": PAGE_LIMIT, "page": page})
        products = (payload or {}).get("products") or []
        if not products:
            break
        scanned += len(products)
        for product in products:
            if vendors and (product.get("vendor") or "").casefold() not in vendors:
                continue
            if types is not None and product.get("product_type") not in types:
                continue
            listed.append(product)

    rows: list[dict] = []
    for product in listed:
        handle = product.get("handle")
        detail = client.get_json(f"/products/{handle}.js") or {}
        for variant in detail.get("variants") or []:
            sku = str(variant.get("sku") or "").strip()
            ean = str(variant.get("barcode") or "").strip()
            if not sku or not ean:
                continue
            rows.append(
                {
                    "sku": sku,
                    "ean": ean,
                    "name": detail.get("title") or product.get("title"),
                    "url": f"{base}/products/{handle}",
                    "store": store["id"],
                }
            )
    return rows, scanned


SCANNERS = {"shopify": scan_shopify}


def main() -> None:
    brands = sys.argv[1:]
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()

    for slug, brand_cfg in config.items():
        if brands and slug not in brands:
            continue
        stores_meta: dict[str, dict] = {}
        seen: dict[str, dict] = {}  # sku -> row; first store in config order wins
        for store in brand_cfg.get("stores") or []:
            # Two clients on purpose, same as acquire.runner: the first is a bare probe used
            # ONLY to fetch robots.txt (checking robots against the robots.txt fetch would be
            # nonsensical); every real request goes through the second, which enforces the
            # policy per-request. A host we cannot read robots for raises -- never assume.
            probe = PoliteClient(
                store["baseUrl"], rps=float(store.get("rps", 0.5)), user_agent=BOT_UA, timeout=60.0
            )
            policy = fetch_policy(probe, store["baseUrl"])
            rps = float(store.get("rps", 0.5))
            delay = policy.crawl_delay(BOT_UA)
            if delay:  # a declared Crawl-delay always wins over the configured rate
                rps = min(rps, 1.0 / delay)
            client = PoliteClient(
                store["baseUrl"], rps=rps, user_agent=BOT_UA, timeout=60.0, robots=policy
            )
            rows, scanned = SCANNERS[store.get("platform", "shopify")](client, store)
            added = 0
            for row in rows:
                if row["sku"] not in seen:
                    seen[row["sku"]] = row
                    added += 1
            stores_meta[store["id"]] = {
                "baseUrl": store["baseUrl"],
                "snapshot": today,
                "scanned": scanned,
                "withBarcode": len(rows),
                "contributed": added,
            }
            print(f"{slug}/{store['id']}: scanned={scanned} withBarcode={len(rows)} new={added}")

        if not seen:
            print(f"{slug}: no rows, nothing to emit")
            continue
        data = {
            slug: {
                "stores": stores_meta,
                "items": [seen[sku] for sku in sorted(seen)],
            }
        }
        content = (
            "# GENERATED by tools/acquisition/scripts/gen_paint_store_barcodes.py -- do not hand-edit.\n"
            "# Retailer barcode snapshot: manufacturer item code (store sku) -> JAN/EAN, for a brand\n"
            "# whose own site publishes none. METADATA-ONLY: fills blank eans, never mints a paint.\n"
            "# Consumed offline by gen_paint_harvest.py; re-run this script to refresh.\n"
            # dump_yaml (not yaml.safe_dump) because `sku` and `ean` are what gen_paint_harvest.py
            # joins on, and safe_dump protects them only by accident: it quotes a JAN like
            # '4973028111545' because YAML 1.1 reads it as an int, but a store sku that is
            # number-shaped with a leading zero goes out BARE unless it happens to be valid octal,
            # and a YAML 1.2 reader then strips the pad. `snapshot` is the other one -- an ISO date
            # is a YAML 1.1 timestamp, so safe_dump does quote it today, but that is the resolver
            # agreeing by luck rather than the writer meaning it. dump_yaml force-quotes anything
            # number-shaped by rule.
            #
            # sort_keys was already False here and dump_yaml is too, so ordering is untouched: the
            # committed file changes only where _Dumper indents `items:` sequence entries under
            # their key. Measured 2026-08-11: 3,155 lines re-indented, 0 values requoted,
            # parse-equal under yaml.safe_load.
            + dump_yaml(data)
        )
        (OUT_DIR / f"{slug}.yaml").write_bytes(content.encode("utf-8"))
        print(f"{slug}: {len(seen)} coded barcodes -> data/paints/stores/{slug}.yaml")


if __name__ == "__main__":
    main()
