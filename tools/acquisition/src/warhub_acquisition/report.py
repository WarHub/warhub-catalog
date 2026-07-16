"""Coverage and per-source health report (markdown)."""
import subprocess

from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import load_yaml, read_yaml


def build_report(paths: DataPaths) -> str:
    lines = ["## Catalog coverage", "", "| manufacturer | products | with EAN | EAN % | confirmed % |", "|---|---|---|---|---|"]
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        try:
            data = read_yaml(path)
            manufacturer = data["manufacturer"]
            products = data["products"]
        except Exception as exc:
            raise ValueError(f"malformed catalog file {path}: {exc}") from exc
        with_ean = [p for p in products if p.get("ean")]
        confirmed = [p for p in with_ean if p.get("eanConfidence") == "confirmed"]
        total = len(products)
        ean_pct = 100 * len(with_ean) / total if total else 0.0
        confirmed_pct = 100 * len(confirmed) / total if total else 0.0
        lines.append(
            f"| {manufacturer} | {total} | {len(with_ean)} "
            f"| {ean_pct:.1f}% | {confirmed_pct:.1f}% |"
        )
    lines += ["", "## Evidence sources", ""]
    for source_id, observations in EvidenceStore(paths.evidence_products).load_all().items():
        lines.append(f"- {source_id}: {len(observations)} observations")
    return "\n".join(lines) + "\n"


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
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        working = read_yaml(path) or {}
        for product in working.get("products", []):
            working_products[product["id"]] = product
            if product.get("ean"):
                working_holders.setdefault(product["ean"], set()).add(product["id"])
            for extra in product.get("additionalEans") or []:
                working_holders.setdefault(extra, set()).add(product["id"])

    head_files = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD", "--", products_rel + "/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    lost: list[dict] = []
    repackaged: list[dict] = []
    for rel in sorted(line for line in head_files.stdout.splitlines() if line.endswith(".yaml")):
        head_result = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if head_result.returncode != 0 or not head_result.stdout.strip():
            continue
        head_data = load_yaml(head_result.stdout) or {}

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
    return {"lost": lost, "repackaged": repackaged}


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
    return "\n".join(lines) + "\n"
