"""Generate data/paints/swatches/<brand>.yaml — colours extracted from manufacturer charts.

Reads data/paints/swatch-sources.yaml (per-brand chart configs), downloads each chart
(PoliteClient: pacing, browser-UA profile where the WAF demands it, WARHUB_HTTP_CACHE_DIR
cache), samples swatch colours — anchored to the vector code labels for PDFs (see
swatch/pdf_chart.py) or to configured grid geometry for raster chart images (`type:
grid-image`, see swatch/grid_image.py) — and projects them onto the paint catalog's
identities — code-matched, once, here, so the C# SwatchApplier only ever does exact
"{Name}|{Set}" lookups (same architecture as the barcode and harvest bridges).

Outputs, all committed / reviewable:
- data/paints/swatches/<brand>.yaml — entries ONLY for catalog paints whose hex is empty
  (the fill set), with full provenance (chart id+url+sha256, page, code, confidence).
- data/review/swatches/<brand>-<chart>.jpg — contact sheet per chart: sampled crop next to
  the extracted colour for every code, the calibration/audit artifact.
- stdout: cross-check summary (chart colour vs existing catalog hex — REPORTED, never
  applied) and unmatched chart codes.

On-demand, like the harvests: run after adding/refreshing a chart config, review the contact
sheets, commit. Requires the `swatch` extra:
`uv run --extra swatch python tools/acquisition/scripts/gen_paint_swatches.py`
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools/acquisition/src"))

from warhub_acquisition.acquire.client import BROWSER_UA, PoliteClient  # noqa: E402
from warhub_acquisition.swatch.grid_image import CellSample, GridSpec, extract_grid  # noqa: E402
from warhub_acquisition.swatch.pdf_chart import ChartSpec, SampleSpec, extract_chart  # noqa: E402

CONFIG = REPO / "data/paints/swatch-sources.yaml"
BRANDS_DIR = REPO / "data/paints/brands"
OUT_DIR = REPO / "data/paints/swatches"
REVIEW_DIR = REPO / "data/review/swatches"


def load_specs() -> dict[str, tuple[dict, list[ChartSpec | GridSpec]]]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    result: dict[str, tuple[dict, list[ChartSpec | GridSpec]]] = {}
    for slug, brand_cfg in config.items():
        charts: list[ChartSpec | GridSpec] = []
        for chart in brand_cfg.get("charts") or []:
            sample = chart["sample"]
            if chart.get("type") == "grid-image":
                grid = chart["grid"]
                codes = chart["codes"]
                charts.append(
                    GridSpec(
                        chart_id=chart["id"],
                        url=chart["url"],
                        origin_x=float(grid.get("originX", 0)),
                        origin_y=float(grid.get("originY", 0)),
                        cell_w=float(grid["cellWidth"]),
                        cell_h=float(grid["cellHeight"]),
                        cols=int(grid["cols"]),
                        rows=int(grid["rows"]),
                        code_prefix=str(codes["prefix"]),
                        code_start=int(codes["start"]),
                        code_pad=int(codes.get("pad", 0)),
                        max_count=None if codes.get("maxCount") is None else int(codes["maxCount"]),
                        skip_cells=frozenset(int(i) for i in codes.get("skipCells") or ()),
                        sample=CellSample(
                            x0=float(sample["x0"]),
                            y0=float(sample["y0"]),
                            x1=float(sample["x1"]),
                            y1=float(sample["y1"]),
                        ),
                        set_name=chart.get("set"),
                    )
                )
                continue
            charts.append(
                ChartSpec(
                    chart_id=chart["id"],
                    url=chart["url"],
                    code_pattern=chart["codePattern"],
                    pages=tuple(chart.get("pages") or (0,)),
                    sample=SampleSpec(
                        dx=float(sample["dx"]),
                        dy=float(sample["dy"]),
                        width=float(sample["width"]),
                        height=float(sample["height"]),
                        inset=float(sample.get("inset", 0.2)),
                    ),
                    set_name=chart.get("set"),
                )
            )
        result[slug] = (brand_cfg, charts)
    return result


def load_catalog(slug: str) -> dict[str, dict]:
    """productCode -> {key, hex} for the brand's committed catalog."""
    path = BRANDS_DIR / f"{slug}.yaml"
    if not path.exists():
        return {}
    paints = yaml.safe_load(path.read_text(encoding="utf-8")).get("paints") or []
    by_code: dict[str, dict] = {}
    for p in paints:
        code = str(p.get("productCode") or "")
        if not code:
            continue
        details = p.get("details") or {}
        by_code.setdefault(
            code,
            {"key": f"{p['name']}|{details.get('set') or ''}", "hex": details.get("hex") or "",
             "set": details.get("set") or ""},
        )
    return by_code


def contact_sheet(swatches, renders, out_path: Path, *, row_h: int = 44, crop_w: int = 120) -> None:
    # Grid charts pass a larger row_h/crop_w: their crop is the FULL cell whose printed code
    # must stay legible (the sheet's self-verification), so it must not be thumbnailed down.
    from PIL import Image, ImageDraw

    if not swatches:
        return
    color_w, text_w, pad = 90, 90, 6
    width = text_w + crop_w + color_w + 4 * pad
    sheet = Image.new("RGB", (width, row_h * len(swatches) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    for i, sw in enumerate(sorted(swatches, key=lambda s: s.code)):
        y = i * row_h + pad
        draw.text((pad, y + 8), f"{sw.code} p{sw.page}", fill="black")
        draw.text((pad, y + 22), f"{sw.hex} {sw.confidence}", fill="gray")
        crop = renders[sw.page].crop(sw.crop_box_px)
        crop.thumbnail((crop_w, row_h - 2 * pad))
        sheet.paste(crop, (text_w + pad, y))
        draw.rectangle(
            (text_w + crop_w + 2 * pad, y, text_w + crop_w + 2 * pad + color_w, y + row_h - 2 * pad),
            fill=sw.rgb,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=82)


def main() -> None:
    import pdfplumber

    only_brands = set(sys.argv[1:])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for slug, (brand_cfg, charts) in load_specs().items():
        if only_brands and slug not in only_brands:
            continue
        catalog = load_catalog(slug)
        if not catalog:
            print(f"{slug}: no catalog file with product codes; skipping")
            continue

        client = PoliteClient(
            None,
            rps=0.2,
            user_agent=BROWSER_UA if brand_cfg.get("uaProfile") == "browser" else
            "warhub-catalog-bot/1.0 (+https://github.com/WarHub/warhub-catalog)",
            timeout=120.0,
        )

        applied: dict[str, dict] = {}
        cross_checks: list[str] = []
        unmatched: list[str] = []
        for spec in charts:
            raw = client.get_response(spec.url).content
            sha = hashlib.sha256(raw).hexdigest()
            if isinstance(spec, GridSpec):
                from PIL import Image

                chart_image = Image.open(io.BytesIO(raw)).convert("RGB")
                swatches = extract_grid(chart_image, spec)
                renders = {0: chart_image}  # extract_grid stamps page=0 on every swatch
                method = "grid-image"
                # Full cells at ~original scale so the printed code stays readable.
                sheet_size = {"row_h": round(spec.cell_h) + 12, "crop_w": round(spec.cell_w) + 16}
            else:
                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    swatches, renders = extract_chart(pdf, spec)
                method = "pdf-chart"
                sheet_size = {}
            contact_sheet(swatches, renders, REVIEW_DIR / f"{slug}-{spec.chart_id}.jpg", **sheet_size)

            filled = checked = 0
            for sw in swatches:
                entry = catalog.get(sw.code)
                if entry is None:
                    unmatched.append(f"{spec.chart_id}: {sw.code} {sw.hex}")
                    continue
                if spec.set_name is not None and entry["set"] != spec.set_name:
                    unmatched.append(
                        f"{spec.chart_id}: {sw.code} -> {entry['key']} (outside set {spec.set_name})"
                    )
                    continue
                if entry["hex"]:
                    checked += 1
                    if entry["hex"].upper() != sw.hex.upper():
                        cross_checks.append(
                            f"{spec.chart_id}: {sw.code} chart {sw.hex} vs catalog {entry['hex']} ({entry['key']})"
                        )
                    continue
                filled += 1
                # Keyed by {Name}|{Set}|{ProductCode}: variant ranges (TMM) reuse a colour
                # name across 4 coded variants with DIFFERENT chart colours -- a 2-part key
                # would paint all four with one variant's hex.
                applied.setdefault(
                    f"{entry['key']}|{sw.code}",
                    {
                        "hex": sw.hex,
                        "code": sw.code,
                        "method": method,
                        "chart": spec.chart_id,
                        "source": spec.url,
                        "sourceSha256": sha,
                        "page": sw.page,
                        "confidence": sw.confidence,
                    },
                )
            print(
                f"{slug}/{spec.chart_id}: swatches={len(swatches)} filled={filled} "
                f"cross-checked={checked} (contact sheet: data/review/swatches/{slug}-{spec.chart_id}.jpg)"
            )

        if applied:
            out = OUT_DIR / f"{slug}.yaml"
            content = (
                "# GENERATED by tools/acquisition/scripts/gen_paint_swatches.py -- do not hand-edit.\n"
                "# Colours sampled from manufacturer charts (PDF or raster grid), keyed by the\n"
                "# paint catalog's {Name}|{Set} identity. The C# SwatchApplier fills EMPTY hex\n"
                "# only; overrides win.\n"
                "# Review artifacts: data/review/swatches/*.jpg (crop vs extracted colour per code).\n"
                + yaml.safe_dump({slug: {k: applied[k] for k in sorted(applied)}},
                                 sort_keys=False, allow_unicode=True, width=200)
            )
            out.write_bytes(content.encode("utf-8"))
            print(f"{slug}: wrote {len(applied)} fills -> {out.relative_to(REPO)}")
        if cross_checks:
            print(f"{slug}: {len(cross_checks)} cross-check differences (chart vs existing catalog hex; NOT applied):")
            for line in cross_checks[:10]:
                print("   ", line)
        if unmatched:
            print(f"{slug}: {len(unmatched)} chart codes not usable:")
            for line in unmatched[:10]:
                print("   ", line)


if __name__ == "__main__":
    main()
