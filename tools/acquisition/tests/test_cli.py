import json
from pathlib import Path

from warhub_acquisition.cli import main
from test_resolver import seed  # reuse the fixture builder


def test_resolve_command(tmp_path: Path, capsys) -> None:
    seed(tmp_path)
    exit_code = main(["resolve", "--data", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "resolved 1 products across 1 manufacturers; 0 conflicts" in out
    assert (tmp_path / "catalog" / "products" / "games-workshop.yaml").exists()


def test_report_command(tmp_path: Path, capsys) -> None:
    seed(tmp_path)
    main(["resolve", "--data", str(tmp_path)])
    exit_code = main(["report", "--data", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "| games-workshop | 1 | 1 | 1 | 100.0% | 0.0% |" in out  # products | current | with EAN
    assert "- mfr-gw: 1 observations" in out


def test_missing_data_dir_is_loud(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "nope"
    assert main(["report", "--data", str(missing)]) == 1
    assert main(["resolve", "--data", str(missing)]) == 1
    err = capsys.readouterr().err
    assert "data directory not found" in err


def test_a_run_whose_only_finding_is_a_re_homing_exits_clean(tmp_path: Path, capsys) -> None:
    """THE POINT OF SPLITTING rehomed.yaml OUT, expressed as the exit code.

    `resolve` returns 2 when `conflicts.yaml` has rows, and the nightly reports that as review
    material. A `supersession-stale-code` row is not review material -- it is a placement the
    resolver made itself, on a declared pair, and no edit to any committed file removes one. While
    those rows lived in the working set, a catalog with nothing left to decide still exited 2
    forever. Now it exits 0, and the re-homings are still counted on the line and still written.
    """
    from warhub_acquisition.yamlio import read_yaml, write_yaml

    write_yaml(
        tmp_path / "catalog" / "taxonomy" / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "codeStrip": [],
                            "gs1Prefixes": ["5011921"], "vendorNames": []}]},
    )
    write_yaml(tmp_path / "catalog" / "sources" / "mfr-gw.yaml",
               {"id": "mfr-gw", "kind": "manufacturer", "strategy": "algolia"})
    write_yaml(tmp_path / "catalog" / "sources" / "ret-goblin.yaml",
               {"id": "ret-goblin", "kind": "retailer", "strategy": "shopify"})
    write_yaml(tmp_path / "catalog" / "matches.yaml",
               {"supersessions": {"games-workshop/99120110001": "games-workshop/99120110002"}})

    def line(**kw: object) -> str:
        base = {"firstSeen": "2026-07-07", "lastSeen": "2026-07-12", "extractor": "test@1",
                "manufacturer": "games-workshop"}
        return json.dumps({**base, **kw}) + "\n"

    gw = tmp_path / "evidence" / "products" / "mfr-gw" / "observations.jsonl"
    gw.parent.mkdir(parents=True)
    gw.write_text(
        line(key="mfr-gw:retired", name="Widget", sku="99120110001", ean="5011921062164")
        + line(key="mfr-gw:current", name="Widget", sku="99120110002", ean="5011921179398"),
        encoding="utf-8", newline="\n")
    goblin = tmp_path / "evidence" / "products" / "ret-goblin" / "observations.jsonl"
    goblin.parent.mkdir(parents=True)
    # the bridge: the shop's own catalogue number is the RETIRED code, the box scans as the CURRENT
    goblin.write_text(
        line(key="ret-goblin:widget", name="Widget", sku="99120110001", ean="5011921179398"),
        encoding="utf-8", newline="\n")

    exit_code = main(["resolve", "--data", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 0, "a re-homing must not hold the exit code at 2"
    assert "0 conflicts; 1 re-homed" in out
    assert read_yaml(tmp_path / "review" / "conflicts.yaml")["conflicts"] == []
    assert [c["type"] for c in read_yaml(tmp_path / "review" / "rehomed.yaml")["rehomed"]] == [
        "supersession-stale-code"]
