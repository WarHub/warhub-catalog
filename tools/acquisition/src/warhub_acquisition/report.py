"""Coverage and per-source health report (markdown)."""
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import read_yaml


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
