"""data/catalog/set-contents/*.yaml: the resolved boxed-set -> member-paint relation.

The generator joins each product's raw `contentSkus` against the paint archive ONCE, here, so a
publisher only ever does an exact lookup. Two properties matter more than the counts:

- NO REF IS SILENTLY DROPPED. Every ref is either a member or an `unresolved:` entry with a
  reason. A file reporting 100% resolution by discarding its misses is the failure mode.
- NO QUANTITY IS INVENTED. `quantity` is absent when the source does not state one, and absent
  must never be read as 1 -- reapermini.com states no quantity anywhere (measured 2026-08-07:
  848 associatedProducts entries, no count field, 0 repeated skus), so writing 1 would assert
  800 facts nobody made.
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools/acquisition/scripts/gen_set_contents.py"
RELATION_DIR = REPO_ROOT / "data/catalog/set-contents"
PRODUCTS_DIR = REPO_ROOT / "data/catalog/products"
BRANDS_DIR = REPO_ROOT / "data/paints/brands"


def _require():
    if not RELATION_DIR.exists():
        pytest.skip("data/catalog/set-contents/ not present")
    files = sorted(RELATION_DIR.glob("*.yaml"))
    if not files:
        pytest.skip("no relation files committed yet")
    return files


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_every_ref_is_a_member_or_a_named_refusal() -> None:
    """The load-bearing invariant. `counts.refs` must equal members + unresolved, per brand AND
    against the product records the refs came from -- so a ref cannot vanish between the two."""
    for path in _require():
        for brand, block in _load(path).items():
            sets = block.get("sets") or {}
            members = sum(len(s.get("members") or []) for s in sets.values())
            unresolved = sum(len(s.get("unresolved") or []) for s in sets.values())
            counts = block.get("counts") or {}
            assert members + unresolved == counts.get("refs"), (
                f"{path.name}/{brand}: {members} members + {unresolved} unresolved != "
                f"{counts.get('refs')} refs -- a ref was dropped between the two"
            )
            assert counts.get("members") == members
            assert counts.get("unresolved") == unresolved
            assert counts.get("sets") == len(sets)


def test_the_relation_covers_exactly_the_products_that_state_contents() -> None:
    """Cross-checked against the SOURCE of the refs, not just internal consistency: every product
    carrying `contentSkus` must appear, with the same number of refs it declares."""
    declared: dict[str, list[str]] = {}
    for path in sorted(PRODUCTS_DIR.glob("*.yaml")):
        for product in (_load(path).get("products") or []):
            if product.get("contentSkus"):
                declared[product["id"]] = product["contentSkus"]

    seen: dict[str, int] = {}
    for path in _require():
        for block in _load(path).values():
            for set_id, entry in (block.get("sets") or {}).items():
                seen[set_id] = len(entry.get("members") or []) + len(entry.get("unresolved") or [])

    assert set(seen) == set(declared), (
        f"relation covers {len(seen)} sets, products declare {len(declared)}; "
        f"missing={sorted(set(declared) - set(seen))[:5]} extra={sorted(set(seen) - set(declared))[:5]}"
    )
    mismatched = {k: (seen[k], len(v)) for k, v in declared.items() if seen[k] != len(v)}
    assert not mismatched, f"ref count differs from the product record: {mismatched}"


def test_no_member_invents_a_quantity() -> None:
    """`quantity` may be absent (source silent) or a positive int (source stated it). It may never
    be a defaulted 1, because a fabricated 1 is indistinguishable from a measured one."""
    for path in _require():
        for brand, block in _load(path).items():
            quantified = 0
            for set_id, entry in (block.get("sets") or {}).items():
                for member in entry.get("members") or []:
                    if "quantity" not in member:
                        continue
                    quantified += 1
                    assert isinstance(member["quantity"], int) and member["quantity"] > 0, (
                        f"{set_id} member {member.get('ref')}: quantity must be a positive int"
                    )
            assert (block.get("counts") or {}).get("quantified") == quantified, (
                f"{path.name}/{brand}: counts.quantified must state the real number, so a zero "
                f"is a measured zero rather than a silence"
            )


def test_every_member_names_exactly_one_committed_paint() -> None:
    """A member is a claim that a specific pot is in a specific box. `{Name}|{Set}` is not unique,
    which is why a member carries `productCode` too -- the pair must name exactly one record."""
    archives: dict[str, list[dict]] = {
        p.stem: (_load(p).get("paints") or []) for p in sorted(BRANDS_DIR.glob("*.yaml"))
    }
    offenders = []
    for path in _require():
        for block in _load(path).values():
            for set_id, entry in (block.get("sets") or {}).items():
                brand = entry.get("brand")
                records = archives.get(brand) or []
                for member in entry.get("members") or []:
                    name, _, set_name = str(member["paint"]).partition("|")
                    hits = [
                        r for r in records
                        if r.get("name") == name
                        and (r.get("details") or {}).get("set") == set_name
                        and str(r.get("productCode") or "") == str(member.get("productCode") or "")
                    ]
                    if len(hits) != 1:
                        offenders.append((set_id, member.get("ref"), member["paint"], len(hits)))
    assert not offenders, f"members naming zero or several paints: {offenders[:8]}"


def test_the_committed_relation_is_reproducible_from_committed_inputs() -> None:
    """The file depends on outputs of BOTH pipelines (data/catalog/products from catalog-acquire,
    data/paints/brands from paint-catalog-update), which run on different cadences. A stale file
    must fail CI rather than publish a membership neither side supports."""
    if not SCRIPT.exists():
        pytest.skip("gen_set_contents.py not present")
    before = {p: p.read_bytes() for p in _require()}
    subprocess.run([sys.executable, str(SCRIPT)], check=True, capture_output=True, cwd=REPO_ROOT)
    stale = [p.name for p, data in before.items() if p.read_bytes() != data]
    assert not stale, (
        f"committed relation files are not reproducible from committed inputs: {stale}. "
        "Regenerate with `uv run --with pyyaml python tools/acquisition/scripts/gen_set_contents.py`."
    )
