"""Coverage and per-source health report (markdown)."""
from warhub_acquisition.evidence.store import EvidenceStore
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import read_yaml


def build_report(paths: DataPaths) -> str:
    lines = ["## Catalog coverage", "", "| manufacturer | products | with EAN | EAN % | confirmed % |", "|---|---|---|---|---|"]
    for path in sorted(paths.catalog_products.glob("*.yaml")):
        data = read_yaml(path)
        products = data["products"]
        with_ean = [p for p in products if p.get("ean")]
        confirmed = [p for p in with_ean if p.get("eanConfidence") == "confirmed"]
        total = len(products)
        lines.append(
            f"| {data['manufacturer']} | {total} | {len(with_ean)} "
            f"| {100 * len(with_ean) / total:.1f}% | {100 * len(confirmed) / total:.1f}% |"
        )
    lines += ["", "## Evidence sources", ""]
    for source_id, observations in EvidenceStore(paths.evidence_products).load_all().items():
        lines.append(f"- {source_id}: {len(observations)} observations")
    return "\n".join(lines) + "\n"
