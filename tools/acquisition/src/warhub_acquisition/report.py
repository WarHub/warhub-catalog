"""Coverage and per-source health report (markdown)."""
import subprocess
from pathlib import Path

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import load_yaml, read_yaml

# The paint catalog is not a `DataPaths` member (that dataclass describes the product pipeline the
# resolver drives, and paints are published by a different tool), so the guard derives the brand
# directory from the data root the same way it derives the repo root.
PAINT_BRANDS_SUBDIR = ("paints", "brands")


def _paint_brands_dir(paths: DataPaths) -> Path:
    return paths.root.joinpath(*PAINT_BRANDS_SUBDIR)


def _product_barcodes(product: dict) -> list[str]:
    """Every barcode a PRODUCT record attests. Role is not tracked here: this is only ever used as
    a fallback holder for `_check_paints`, which asks "does this barcode still exist at all", and
    the product side runs its own role-aware guard over the same records."""
    barcodes: list[str] = []
    if product.get("ean"):
        barcodes.append(str(product["ean"]))
    barcodes.extend(str(extra) for extra in product.get("additionalEans") or [])
    return barcodes


def _paint_barcodes(record: dict) -> list[tuple[str, str]]:
    """Every barcode a paint record attests, paired with the role it holds it in.

    Both roles are returned: paints have no `eanConfidence` (see `_check_paints`), so the primary
    `ean` and each `additionalEans` entry are equally attested and equally tracked.
    """
    barcodes: list[tuple[str, str]] = []
    if record.get("ean"):
        barcodes.append((str(record["ean"]), "primary"))
    barcodes.extend((str(extra), "additional") for extra in record.get("additionalEans") or [])
    return barcodes


def build_report(paths: DataPaths) -> str:
    # `products` is the TOTAL and includes archival records -- a superseded product is still a real
    # product somebody owns. `current` is the subset nothing supersedes; the two are reported
    # separately so the coverage percentages (which stay over the total) can't be misread as a
    # shrinking or growing shelf when lineage links are added.
    lines = [
        "## Catalog coverage",
        "",
        "| manufacturer | products | current | with EAN | EAN % | confirmed % |",
        "|---|---|---|---|---|---|",
    ]
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        try:
            data = read_yaml(path)
            manufacturer = data["manufacturer"]
            products = data["products"]
        except Exception as exc:
            raise ValueError(f"malformed catalog file {path}: {exc}") from exc
        with_ean = [p for p in products if p.get("ean")]
        confirmed = [p for p in with_ean if p.get("eanConfidence") == "confirmed"]
        current = [p for p in products if not p.get("supersededBy")]
        total = len(products)
        ean_pct = 100 * len(with_ean) / total if total else 0.0
        confirmed_pct = 100 * len(confirmed) / total if total else 0.0
        lines.append(
            f"| {manufacturer} | {total} | {len(current)} | {len(with_ean)} "
            f"| {ean_pct:.1f}% | {confirmed_pct:.1f}% |"
        )
    # Paint coverage exists so the EAN gate's reach over paints is AUDITABLE on every run. A gate
    # that quietly reads zero files would pass forever (e.g. if the brand directory moves), which
    # is the same class of silent failure it is there to prevent -- so the barcode count it gates
    # is printed whether or not anything changed.
    brands_dir = _paint_brands_dir(paths)
    brand_rows = []
    catalog_barcodes: set[str] = set()
    for path in sorted(brands_dir.glob("*.yaml")):
        try:
            data = read_yaml(path) or {}
            brand = str(data.get("brandSlug") or path.stem)
            paints = data.get("paints") or []
        except Exception as exc:
            raise ValueError(f"malformed paint brand file {path}: {exc}") from exc
        barcodes = {code for record in paints for code, _ in _paint_barcodes(record)}
        catalog_barcodes |= barcodes
        brand_rows.append((brand, len(paints), len(barcodes)))
    if brand_rows:
        lines += ["", "## Paint coverage", "", "| brand | paints | barcodes under EAN guard |", "|---|---|---|"]
        lines += [f"| {brand} | {paints} | {barcodes} |" for brand, paints, barcodes in brand_rows]
        lines.append(f"| **total** | {sum(r[1] for r in brand_rows)} | **{len(catalog_barcodes)}** |")
    lines += ["", "## Evidence sources", ""]
    for source_id, observations in EvidenceStore(paths.evidence_products).load_all().items():
        lines.append(f"- {source_id}: {len(observations)} observations")
    return "\n".join(lines) + "\n"


def _head_yaml_files(repo_root: Path, rel_dir: str) -> list[str]:
    """Repo-relative *.yaml paths HEAD holds under `rel_dir` that DIFFER from the working tree.

    Enumerated from the tree rather than the working glob so a file DELETED from the working tree
    is still read; a directory absent from HEAD entirely yields nothing (`ls-tree` exits 0 with no
    output on an unmatched pathspec, which is exactly the right answer -- nothing to track).

    Intersected with `git diff --name-only HEAD` (2026-08-06) because a file identical to HEAD can
    never produce a finding, and reading it is the guard's whole cost. The argument is semantic,
    not just an optimisation: every finding here requires a barcode present in HEAD to be missing
    from the working tree under the same holder. If a file is byte-identical, every barcode it
    attests is still attested by the same record in the same role in the same file -- the
    `continue` branch -- so no comparison against it can fire. The WORKING side still reads every
    file, which is what keeps a barcode that MOVED INTO an unchanged file visible.

    `git diff --name-only HEAD` reports deletions and unstaged modifications, so both still get
    read. An untracked file cannot appear, and correctly so: it has no HEAD version to compare.
    """
    tracked = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD", "--", rel_dir + "/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", rel_dir + "/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    differing = set(changed.stdout.splitlines())
    return sorted(
        line
        for line in tracked.stdout.splitlines()
        if line.endswith(".yaml") and line in differing
    )


def _head_document(repo_root: Path, rel: str) -> dict:
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    return load_yaml(result.stdout) or {}


def _paint_label(brand: str, record: dict) -> str:
    """Human label for a paint in a finding -- COSMETIC ONLY, never used for matching.

    Shaped like the `name|set` natural key the paint files already use for their own
    `supersedes`/`supersededBy` references, prefixed with the brand slug.
    """
    name = str(record.get("name") or "?")
    paint_set = (record.get("details") or {}).get("set")
    return f"{brand}/{name}|{paint_set}" if paint_set else f"{brand}/{name}"


def _check_paints(
    repo_root: Path, brands_dir: Path, products_dir: Path
) -> tuple[list[dict], list[dict]]:
    """Compare working-tree paints/brands/*.yaml against HEAD, tracking barcodes GLOBALLY.

    ALL paint barcodes are tracked -- the primary `ean` and every `additionalEans` entry alike.
    The product side can afford to gate only `confirmed` primaries because a product EAN is
    *inferred* by the resolver from competing observations and carries an `eanConfidence` grade,
    so a provisional one is a guess a better source may legitimately correct. Paint records carry
    no such field and no such grade: a paint barcode is transcribed from a brand/trade register,
    every one is attested, and nothing in the paint pipeline replaces one pot's barcode with a
    different one -- a reformulation mints a NEW record and the old barcode stays on the old one.
    So there is no defensible "provisional" tier to demote paints into; treating them all as
    ungated would leave the gate vacuous, which is the gap this closes. No `eanConfidence` is
    invented on paints.

    Matching is deliberately identity-free at the record level. Paint records have NO `id` in the
    source at all -- ids are minted at publish time and are content-derived, so they legitimately
    change between commits -- and `name` is not unique within a brand. Keying on either would
    manufacture false alarms. The coarsest identity a paint barcode genuinely has in the source is
    its BRAND (the file it lives in), so:

      * no finding -- the barcode is still held in the SAME role under one of the SAME brands.
        A record renamed, re-set, re-coded or re-slugged under it is invisible here, by design.
      * ``moved`` -- the barcode survives somewhere in the paint catalog but changed role
        (a primary demoted into `additionalEans`, or an additional promoted) or changed brand.
        Reported with the holders named; NOT a regression.
      * ``lost`` -- the barcode appears NOWHERE in the working paint catalog: an old pot stopped
        being scannable, which is exactly the regression the caller fails the run on.

    **Cross-catalog re-homing counts as `moved` (2026-08-05).** The working PRODUCT catalog is
    searched too, and a barcode that left the paint catalog but is now held by a product is
    reported as moved rather than lost. The guard's real question is "is this barcode still
    attested SOMEWHERE in the repo", and a boxed set leaving the paint catalog for the product
    catalog -- where it always belonged -- is a correction, not a regression. This is not a
    loosening: a barcode held by neither catalog is still `lost` and still exits 5. It exists
    because the alternative was worse. Retiring the 19 Green Stuff World boxed sets that reached
    `data/paints/brands/green-stuff-world.yaml` as fake single pots requires their sole-held box
    GTINs to survive; without this, doing the RIGHT thing (re-home to products, then retract)
    would fail the build, and the only ways to keep it green would have been to weaken the guard
    outright or to hide the GTIN in a surviving pot's `additionalEans` -- which would be a factual
    lie, since a boxed-set GTIN is not a pot's GTIN.
    """
    # barcode -> {(holder, role)} across the WHOLE working paint catalog, plus the product catalog
    # as a fallback holder so a cross-catalog re-home reads as moved. Products are recorded under a
    # "products/<file stem>" holder so the rendered finding says where it went.
    working_holders: dict[str, set[tuple[str, str]]] = {}
    for path in sorted(brands_dir.glob("*.yaml")):
        working = read_yaml(path) or {}
        brand = str(working.get("brandSlug") or path.stem)
        for record in working.get("paints") or []:
            for barcode, role in _paint_barcodes(record):
                working_holders.setdefault(barcode, set()).add((brand, role))

    for path in sorted(products_dir.glob("*.yaml")):
        for product in (read_yaml(path) or {}).get("products") or []:
            for barcode in _product_barcodes(product):
                working_holders.setdefault(barcode, set()).add((f"products/{path.stem}", "product"))

    lost: list[dict] = []
    moved: list[dict] = []
    for rel in _head_yaml_files(repo_root, brands_dir.relative_to(repo_root).as_posix()):
        head_data = _head_document(repo_root, rel)
        head_brand = str(head_data.get("brandSlug") or Path(rel).stem)
        for head_record in head_data.get("paints") or []:
            for barcode, role in _paint_barcodes(head_record):
                holders = working_holders.get(barcode) or set()
                if (head_brand, role) in holders:
                    continue
                finding = {
                    "entity": _paint_label(head_brand, head_record),
                    "brand_file": rel,
                    "previous_ean": barcode,
                    "role": role,
                }
                if holders:
                    finding["retained_in"] = sorted(f"{b} ({r})" for b, r in holders)
                    moved.append(finding)
                else:
                    lost.append(finding)
    return lost, moved


def check_ean_guard(paths: DataPaths) -> dict[str, list[dict]]:
    """Compare working-tree catalog/products/*.yaml against HEAD, tracking barcodes GLOBALLY.

    Every barcode HEAD attests -- a `confirmed` primary `ean`, or ANY `additionalEans` entry
    (those only exist through a deliberate repackaging join, so they are always tracked) -- must
    still be present somewhere in the working tree. Presence is checked across the WHOLE catalog
    (any product's `ean` or `additionalEans`), independent of whether the barcode's HEAD entity
    survived: a join that REMOVES an entity does not exempt its confirmed barcode. Each tracked
    barcode that is no longer where HEAD had it is classified:

      * ``lost`` -- the barcode appears NOWHERE in the working tree: a genuine regression
        (a silently dropped confirmed barcode, or a vanished additionalEans entry), the caller
        fails the run loudly.
      * ``repackaged`` -- the barcode moved but is RETAINED somewhere (e.g. a removed entity's
        confirmed barcode landing in the surviving entity's `additionalEans`, or a primary demoted
        to its own `additionalEans` by a repackaging join). Reported for visibility with the
        retaining entities named, but NOT a regression.

    The PAINT catalog (paints/brands/*.yaml) is gated alongside it under the `paint_lost` /
    `paint_moved` keys -- same lost-vs-moved split, different tracking rule because paints have no
    `eanConfidence` and no source-side id. See `_check_paints`.

    Pure read -- no git mutation, no filesystem writes. The repo root is derived as the data dir's
    parent. HEAD-side files are enumerated with `git ls-tree` (not the working glob), so barcodes
    in a manufacturer file deleted from the working tree are still tracked; a catalog absent from
    HEAD entirely (e.g. a brand-new repo) tracks nothing.
    """
    repo_root = paths.root.parent
    products_rel = paths.catalog_products.relative_to(repo_root).as_posix()

    # Working tree: every product by id, plus a global barcode -> holding entities presence map.
    working_products: dict[str, dict] = {}
    working_holders: dict[str, set[str]] = {}
    working_codes: set[str] = set()
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        working = read_yaml(path) or {}
        for product in working.get("products", []):
            working_products[product["id"]] = product
            if product.get("ean"):
                working_holders.setdefault(product["ean"], set()).add(product["id"])
            for extra in product.get("additionalEans") or []:
                working_holders.setdefault(extra, set()).add(product["id"])
            if product.get("productCode"):
                working_codes.add(product["productCode"])

    lost: list[dict] = []
    repackaged: list[dict] = []
    # Non-fatal visibility buckets. The confirmed-only guard above is silent about two real losses:
    # a PROVISIONAL primary that vanishes catalog-wide, and a productCode that vanishes catalog-wide
    # (today a repackaging join folds an old code away and nothing notices). Both are REPORTED but
    # never fail the run -- a provisional barcode is legitimately corrected when a better source
    # arrives, and code folding is still the current design. Making them visible is the point: they
    # are the acceptance test for the archival work that stops discarding old codes/barcodes.
    dropped_provisional: list[dict] = []
    dropped_codes: list[dict] = []
    for rel in _head_yaml_files(repo_root, products_rel):
        head_data = _head_document(repo_root, rel)

        for head_product in head_data.get("products", []):
            entity_id = head_product["id"]
            tracked: list[tuple[str, str]] = []
            if head_product.get("eanConfidence") == "confirmed" and head_product.get("ean"):
                tracked.append((head_product["ean"], "primary"))
            tracked.extend((extra, "additional") for extra in head_product.get("additionalEans") or [])

            working_product = working_products.get(entity_id)
            for barcode, role in tracked:
                if working_product is not None:
                    # No finding only when the barcode kept ITS position on the same entity; a
                    # primary demoted to its own additionalEans (or an additional promoted to
                    # primary) is a repackaging event and is still reported below.
                    if role == "primary" and working_product.get("ean") == barcode:
                        continue
                    if role == "additional" and barcode in (working_product.get("additionalEans") or []):
                        continue
                finding = {
                    "entity": entity_id,
                    "manufacturer_file": rel,
                    "previous_ean": barcode,
                    "new_ean": working_product.get("ean") if working_product else None,
                }
                holders = sorted(working_holders.get(barcode, set()))
                if holders:
                    finding["retained_in"] = holders
                    repackaged.append(finding)
                else:
                    lost.append(finding)

            # A provisional primary is only reported when it vanished EVERYWHERE -- if it merely
            # moved (promoted, demoted, or re-homed on another entity) it survived, which is all
            # this bucket is asking about.
            provisional = head_product.get("ean")
            if provisional and head_product.get("eanConfidence") != "confirmed":
                if not working_holders.get(provisional):
                    dropped_provisional.append(
                        {
                            "entity": entity_id,
                            "manufacturer_file": rel,
                            "previous_ean": provisional,
                            "new_ean": working_product.get("ean") if working_product else None,
                        }
                    )

            head_code = head_product.get("productCode")
            if head_code and head_code not in working_codes:
                dropped_codes.append(
                    {"entity": entity_id, "manufacturer_file": rel, "previous_code": head_code}
                )

    paint_lost, paint_moved = _check_paints(
        repo_root, _paint_brands_dir(paths), paths.catalog_products
    )

    return {
        "lost": lost,
        "repackaged": repackaged,
        "dropped_provisional": dropped_provisional,
        "dropped_codes": dropped_codes,
        "paint_lost": paint_lost,
        "paint_moved": paint_moved,
    }


def render_ean_guard_section(findings: dict[str, list[dict]]) -> str:
    order = lambda f: (f["entity"], f["previous_ean"] or "")  # noqa: E731
    lines: list[str] = []
    if findings["lost"]:
        lines += ["", "## Confirmed-EAN changes", ""]
        for finding in sorted(findings["lost"], key=order):
            lines.append(f"- {finding['entity']}: {finding['previous_ean']} -> {finding['new_ean']}")
    if findings["repackaged"]:
        lines += ["", "## Confirmed-EAN repackaging (retained in additionalEans)", ""]
        for finding in sorted(findings["repackaged"], key=order):
            retained = ", ".join(finding.get("retained_in", []))
            lines.append(
                f"- {finding['entity']}: {finding['previous_ean']} -> {finding['new_ean']} "
                f"(retained in {retained})"
            )
    if findings.get("dropped_provisional"):
        lines += ["", "## Provisional-EAN dropped (visibility only, not a regression)", ""]
        for finding in sorted(findings["dropped_provisional"], key=order):
            lines.append(
                f"- {finding['entity']}: {finding['previous_ean']} -> {finding['new_ean']} "
                f"(no longer anywhere in the catalog)"
            )
    if findings.get("dropped_codes"):
        lines += ["", "## Product-code dropped (visibility only, not a regression)", ""]
        for finding in sorted(findings["dropped_codes"], key=lambda f: (f["entity"], f["previous_code"])):
            lines.append(
                f"- {finding['entity']}: productCode {finding['previous_code']} "
                f"no longer anywhere in the catalog"
            )
    if findings.get("paint_lost"):
        lines += ["", "## Paint-EAN lost", ""]
        for finding in sorted(findings["paint_lost"], key=order):
            lines.append(
                f"- {finding['entity']}: {finding['previous_ean']} ({finding['role']}) "
                f"no longer anywhere in the paint catalog"
            )
    if findings.get("paint_moved"):
        lines += ["", "## Paint-EAN moved (retained, not a regression)", ""]
        for finding in sorted(findings["paint_moved"], key=order):
            retained = ", ".join(finding.get("retained_in", []))
            lines.append(
                f"- {finding['entity']}: {finding['previous_ean']} was {finding['role']} "
                f"-- now held by {retained}"
            )
    return "\n".join(lines) + "\n"
