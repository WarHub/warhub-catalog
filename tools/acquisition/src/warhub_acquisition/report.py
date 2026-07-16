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
    """Compare working-tree catalog/products/*.yaml against `git show HEAD:<path>`.

    An entity is examined only when present in BOTH revisions with `eanConfidence == "confirmed"`
    in HEAD and a changed primary `ean` (including to/from null). New entities, removed entities,
    and non-confirmed entities are ignored. A changed primary EAN is classified two ways:

      * ``lost`` -- the previous confirmed barcode is GONE (not the new `ean`, not in the new
        `additionalEans`): a genuine regression, the caller fails the run loudly.
      * ``repackaged`` -- the previous confirmed barcode was RETAINED in `additionalEans`: a
        tracked repackaging (multi-EAN join promoted the live barcode to primary while keeping the
        old one). Reported for visibility but NOT a regression.

    Pure read -- no git mutation, no filesystem writes. The repo root is derived as the data dir's
    parent; a catalog file absent from HEAD (e.g. a new manufacturer file) is treated as empty.
    """
    repo_root = paths.root.parent
    lost: list[dict] = []
    repackaged: list[dict] = []
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        rel = path.relative_to(repo_root).as_posix()
        working = read_yaml(path) or {}
        working_products = {p["id"]: p for p in working.get("products", [])}

        head_result = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if head_result.returncode != 0 or not head_result.stdout.strip():
            continue  # absent (or empty) in HEAD -- nothing previously confirmed to compare
        head_data = load_yaml(head_result.stdout) or {}
        head_products = {p["id"]: p for p in head_data.get("products", [])}

        for entity_id, head_product in sorted(head_products.items()):
            if head_product.get("eanConfidence") != "confirmed":
                continue
            working_product = working_products.get(entity_id)
            if working_product is None:
                continue  # removed entities are not guard hits
            previous_ean = head_product.get("ean")
            new_ean = working_product.get("ean")
            if previous_ean == new_ean:
                continue
            finding = {
                "entity": entity_id,
                "manufacturer_file": rel,
                "previous_ean": previous_ean,
                "new_ean": new_ean,
            }
            retained = {new_ean, *(working_product.get("additionalEans") or [])}
            if previous_ean is not None and previous_ean in retained:
                repackaged.append(finding)
            else:
                lost.append(finding)
    return {"lost": lost, "repackaged": repackaged}


def render_ean_guard_section(findings: dict[str, list[dict]]) -> str:
    lines: list[str] = []
    if findings["lost"]:
        lines += ["", "## Confirmed-EAN changes", ""]
        for finding in sorted(findings["lost"], key=lambda f: f["entity"]):
            lines.append(f"- {finding['entity']}: {finding['previous_ean']} -> {finding['new_ean']}")
    if findings["repackaged"]:
        lines += ["", "## Confirmed-EAN repackaging (retained in additionalEans)", ""]
        for finding in sorted(findings["repackaged"], key=lambda f: f["entity"]):
            lines.append(
                f"- {finding['entity']}: {finding['previous_ean']} -> {finding['new_ean']} "
                f"(previous barcode retained)"
            )
    return "\n".join(lines) + "\n"
