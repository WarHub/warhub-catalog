"""report --ean-guard: confirmed-EAN change detection against `git show HEAD:<path>`.

Uses a THROWAWAY git repo built under tmp_path (git init + config + commit) -- never touches
the real repo. The data dir is repo_root/"data" so DataPaths(data).root.parent == repo_root,
matching how the guard derives the repo root in production.
"""
import subprocess
from pathlib import Path

from warhub_acquisition.cli import main
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import write_yaml


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(repo_root: Path) -> DataPaths:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=repo_root)
    _git("config", "user.email", "test@example.com", cwd=repo_root)
    _git("config", "user.name", "Test", cwd=repo_root)
    return DataPaths(repo_root / "data")


def _commit(repo_root: Path, message: str) -> None:
    _git("add", "-A", cwd=repo_root)
    _git("commit", "-m", message, cwd=repo_root)


def _write_catalog(paths: DataPaths, products: list[dict]) -> None:
    write_yaml(
        paths.catalog_products / "games-workshop.yaml",
        {"manufacturer": "games-workshop", "products": products},
    )


def _write_brand(paths: DataPaths, brand: str, paints: list[dict]) -> None:
    write_yaml(
        paths.root / "paints" / "brands" / f"{brand}.yaml",
        {"brand": brand.replace("-", " ").title(), "brandSlug": brand, "paints": paints},
    )


def test_confirmed_ean_change_exits_5_and_lists_the_entity(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "games-workshop/a" in out
    assert "5011921194285" in out
    assert "5060393709671" in out


def test_no_change_exits_0_and_no_guard_section(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_provisional_ean_change_is_reported_but_never_fails(tmp_path: Path, capsys) -> None:
    """A provisional primary that vanishes catalog-wide is REPORTED but must not fail the run.

    A provisional barcode is legitimately corrected the moment a better source arrives, so this
    can never be exit 5 -- but it used to be entirely silent, which is what the archival work
    needs to be able to see.
    """
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "provisional"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671", "eanConfidence": "provisional"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out
    assert "## Provisional-EAN dropped" in out
    assert "5011921194285" in out


def test_provisional_ean_retained_elsewhere_is_not_reported(tmp_path: Path, capsys) -> None:
    """Only a provisional barcode that vanished EVERYWHERE is reported -- one that merely moved
    (here: promoted to another entity's primary) survived, so it is not a finding."""
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "provisional"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/b", "name": "Thing B", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Provisional-EAN dropped" not in out


def test_dropped_product_code_is_reported_but_never_fails(tmp_path: Path, capsys) -> None:
    """A productCode that vanishes catalog-wide is REPORTED but not fatal.

    This is exactly what a repackaging join does today when it folds an old code away -- the code
    disappears with nothing noticing. It stays non-fatal because folding is still the current
    design; the point is that the loss stops being invisible.
    """
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [
            {"id": "games-workshop/99120204012", "name": "Old Box", "productCode": "99120204012",
             "ean": "5011921062164", "eanConfidence": "confirmed"},
            {"id": "games-workshop/99120204035", "name": "New Box", "productCode": "99120204035",
             "ean": "5011921179398", "eanConfidence": "confirmed"},
        ],
    )
    _commit(repo_root, "seed catalog")

    # the fold: old entity gone, its barcode retained in the survivor's additionalEans
    _write_catalog(
        paths,
        [
            {"id": "games-workshop/99120204035", "name": "New Box", "productCode": "99120204035",
             "ean": "5011921179398", "eanConfidence": "confirmed",
             "additionalEans": ["5011921062164"]},
        ],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0  # barcode was retained -> repackaged, not lost
    assert "## Product-code dropped" in out
    assert "99120204012" in out


def test_new_entity_is_not_a_hit(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [
            {"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"},
            {"id": "games-workshop/b", "name": "Thing B", "ean": "5011921194286", "eanConfidence": "provisional"},
        ],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_removed_entity_with_vanished_confirmed_barcode_is_lost(tmp_path: Path, capsys) -> None:
    # Confirmed barcodes are tracked GLOBALLY, independent of per-entity survival: removing the
    # entity does not exempt its confirmed barcode. Gone from the whole catalog -> lost, exit 5.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(paths, [])

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "games-workshop/a" in out
    assert "5011921194285" in out


def test_new_manufacturer_file_absent_from_head_is_not_a_hit(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8", newline="\n")
    _commit(repo_root, "seed repo")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_repackaging_retained_in_additional_passes_and_reports(tmp_path: Path, capsys) -> None:
    # HEAD confirmed ean X; the working record's primary flips to Y but X is retained in
    # additionalEans -- a tracked repackaging (multi-EAN join). Reported distinctly, NOT a
    # regression: exit 0, and the regression section is absent.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{
            "id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671",
            "eanConfidence": "confirmed", "additionalEans": ["5011921194285"],
        }],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out
    assert "repackaging" in out.lower()
    assert "games-workshop/a" in out


def test_lost_confirmed_ean_not_in_additional_fails_loudly(tmp_path: Path, capsys) -> None:
    # HEAD confirmed ean X; the working primary is Y and X is NOWHERE (not primary, not in
    # additionalEans) -- a genuine regression that must fail loudly: exit 5.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{
            "id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671",
            "eanConfidence": "confirmed", "additionalEans": ["5011921063765"],
        }],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "5011921194285" in out


def test_removed_entity_join_with_barcode_retained_in_survivor_is_repackaged(tmp_path: Path, capsys) -> None:
    # The exact topology of a shipped repackaging join: entity a (confirmed X) is REMOVED by the
    # join and X lands in the SURVIVING entity b's additionalEans. Tracked repackaging -> reported
    # under the repackaging section naming the retaining entity, exit 0, no regression section.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [
            {"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"},
            {"id": "games-workshop/b", "name": "Thing B", "ean": "5060393709671", "eanConfidence": "confirmed"},
        ],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{
            "id": "games-workshop/b", "name": "Thing B", "ean": "5060393709671",
            "eanConfidence": "confirmed", "additionalEans": ["5011921194285"],
        }],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out
    assert "repackaging" in out.lower()
    assert "games-workshop/a" in out
    assert "retained in games-workshop/b" in out


def test_removed_entity_join_with_barcode_dropped_entirely_is_lost(tmp_path: Path, capsys) -> None:
    # Same removed-entity join topology, but the removed entity's confirmed barcode is retained
    # NOWHERE (not the survivor's primary, not any additionalEans) -- the blind spot the global
    # tracking closes: lost, exit 5.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [
            {"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"},
            {"id": "games-workshop/b", "name": "Thing B", "ean": "5060393709671", "eanConfidence": "confirmed"},
        ],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/b", "name": "Thing B", "ean": "5060393709671", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "games-workshop/a" in out
    assert "5011921194285" in out


def test_vanished_additional_ean_is_lost(tmp_path: Path, capsys) -> None:
    # A barcode demoted to additionalEans by an earlier repackaging must not silently vanish on a
    # later run: HEAD has it under b's additionalEans, the working record drops it -> lost, exit 5.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{
            "id": "games-workshop/b", "name": "Thing B", "ean": "5060393709671",
            "eanConfidence": "confirmed", "additionalEans": ["5011921194285"],
        }],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/b", "name": "Thing B", "ean": "5060393709671", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "games-workshop/b" in out
    assert "5011921194285" in out


def test_paint_ean_lost_everywhere_fails_loudly(tmp_path: Path, capsys) -> None:
    # The gap this closes: the paint catalog carries real barcodes and had NO gate at all, so a
    # pot could stop being scannable between commits with nothing noticing. Gone -> exit 5.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black", "ean": "5011921182848"}])
    _commit(repo_root, "seed paints")

    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black"}])

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Paint-EAN lost" in out
    assert "citadel-colour/Abaddon Black" in out
    assert "5011921182848" in out


def test_paint_additional_ean_is_gated_exactly_like_the_primary(tmp_path: Path, capsys) -> None:
    """Paints have no `eanConfidence`, so there is no tier to demote a barcode into: an
    `additionalEans` entry that vanishes is just as fatal as a vanished primary."""
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(
        paths,
        "citadel-colour",
        [{"name": "Abaddon Black", "ean": "5011921182848",
          "additionalEans": ["5011921199457", "5011921244379"]}],
    )
    _commit(repo_root, "seed paints")

    _write_brand(
        paths,
        "citadel-colour",
        [{"name": "Abaddon Black", "ean": "5011921182848", "additionalEans": ["5011921199457"]}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Paint-EAN lost" in out
    assert "5011921244379" in out
    assert "5011921199457" not in out  # still held -> not a finding


def test_paint_ean_demoted_to_additional_is_moved_not_fatal(tmp_path: Path, capsys) -> None:
    # A reformulation making the new pot primary and keeping the old barcode in additionalEans is
    # the archival outcome we WANT: reported for visibility, never a regression.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(paths, "citadel-colour", [{"name": "Hexwraith Flame", "ean": "5011921182848"}])
    _commit(repo_root, "seed paints")

    _write_brand(
        paths,
        "citadel-colour",
        [{"name": "Hexwraith Flame", "ean": "5011921139774",
          "additionalEans": ["5011921182848"]}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Paint-EAN lost" not in out
    assert "## Paint-EAN moved" in out
    assert "5011921182848" in out
    assert "citadel-colour (additional)" in out


def test_paint_ean_moving_to_another_brand_is_moved_not_fatal(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(paths, "citadel-colour", [{"name": "Some Pot", "ean": "5011921182848"}])
    _write_brand(paths, "vallejo", [{"name": "Other Pot", "ean": "8429551700504"}])
    _commit(repo_root, "seed paints")

    _write_brand(paths, "citadel-colour", [])
    _write_brand(
        paths,
        "vallejo",
        [{"name": "Other Pot", "ean": "8429551700504"}, {"name": "Some Pot", "ean": "5011921182848"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Paint-EAN lost" not in out
    assert "## Paint-EAN moved" in out
    assert "vallejo (primary)" in out


def test_paint_identity_change_alone_is_not_a_finding(tmp_path: Path, capsys) -> None:
    """A published paint id is CONTENT-DERIVED (brand + name, escalating to set/productCode/hex),
    so it legitimately changes between commits -- see `publish(paints): make ids depend on the
    paint, not on its neighbours`. The guard is keyed on barcodes, never on the record's identity:
    rewrite every id-input on the record and, with the barcodes untouched, nothing fires.
    """
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(
        paths,
        "citadel-colour",
        [{"name": "Hexwraith Flame", "productCode": "29-11",
          "ean": "5011921182848", "additionalEans": ["5011921199457"],
          "details": {"set": "Technical", "hex": "#4CB0A0"}}],
    )
    _commit(repo_root, "seed paints")

    # name, set, productCode and hex all rewritten -> a different published id, same barcodes.
    _write_brand(
        paths,
        "citadel-colour",
        [{"name": "Hexwraith Flame (Contrast)", "productCode": "29-56",
          "ean": "5011921182848", "additionalEans": ["5011921199457"],
          "details": {"set": "Contrast", "hex": "#3FA090"}}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Paint-EAN lost" not in out
    assert "## Paint-EAN moved" not in out


def test_new_paint_brand_file_absent_from_head_tracks_nothing(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8", newline="\n")
    _commit(repo_root, "seed repo")

    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black", "ean": "5011921182848"}])

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Paint-EAN lost" not in out
    assert "## Paint-EAN moved" not in out


def test_deleted_paint_brand_file_is_still_read_from_head(tmp_path: Path, capsys) -> None:
    # HEAD-side files come from `git ls-tree`, not the working glob, so deleting a brand file
    # cannot hide its barcodes from the gate.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black", "ean": "5011921182848"}])
    _commit(repo_root, "seed paints")

    (paths.root / "paints" / "brands" / "citadel-colour.yaml").unlink()

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Paint-EAN lost" in out
    assert "5011921182848" in out


def test_unchanged_paint_catalog_is_silent(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(
        paths,
        "citadel-colour",
        [{"name": "Abaddon Black", "ean": "5011921182848", "additionalEans": ["5011921199457"]}],
    )
    _commit(repo_root, "seed paints")

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Paint-EAN" not in out


def test_new_paint_with_a_new_barcode_is_not_a_finding(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black", "ean": "5011921182848"}])
    _commit(repo_root, "seed paints")

    _write_brand(
        paths,
        "citadel-colour",
        [{"name": "Abaddon Black", "ean": "5011921182848"},
         {"name": "Hexwraith Flame", "ean": "5011921139774"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Paint-EAN" not in out


def test_paint_guard_does_not_mask_a_lost_product_barcode(tmp_path: Path, capsys) -> None:
    # Both catalogs are gated by the same run; a clean paint catalog must not swallow a product
    # regression, and both sections render together.
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black", "ean": "5011921182848"}])
    _commit(repo_root, "seed both catalogs")

    _write_catalog(paths, [])
    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black"}])

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Confirmed-EAN changes" in out
    assert "## Paint-EAN lost" in out


def test_report_without_ean_guard_flag_ignores_git_state(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285", "eanConfidence": "confirmed"}],
    )
    _commit(repo_root, "seed catalog")

    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5060393709671", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Confirmed-EAN changes" not in out


def test_paint_barcode_rehomed_to_the_product_catalog_is_moved_not_lost(
    tmp_path: Path, capsys
) -> None:
    """The re-home case this exists for: a boxed set wrongly published as a paint is retracted from
    the paint catalog, and its sole-held box GTIN now lives on a product record. That is a
    correction, so it must NOT fail the run -- but it must still be REPORTED, because a barcode
    changing catalogs is exactly the kind of move a reviewer should see."""
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(
        paths,
        "green-stuff-world",
        [{"name": "Paint Set - Chrome", "ean": "8436574506327", "details": {"set": "Chrome"}}],
    )
    _commit(repo_root, "seed the bogus paint record")

    # The retraction, plus the re-home that must precede it.
    _write_brand(paths, "green-stuff-world", [])
    _write_catalog(
        paths,
        [{"id": "green-stuff-world/10133", "name": "Paint Set - Chrome",
          "ean": "8436574506327", "eanConfidence": "confirmed"}],
    )

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Paint-EAN lost" not in out
    assert "## Paint-EAN moved" in out
    assert "8436574506327" in out
    assert "products/games-workshop" in out  # the holder is named, so the move is auditable


def test_retracting_a_paint_without_rehoming_is_still_lost(tmp_path: Path, capsys) -> None:
    """The other half, and the reason the cross-catalog lookup is not a loosening: retract the same
    record WITHOUT putting its barcode anywhere, and the guard still fails the run."""
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_brand(
        paths,
        "green-stuff-world",
        [{"name": "Paint Set - Chrome", "ean": "8436574506327", "details": {"set": "Chrome"}}],
    )
    _commit(repo_root, "seed the bogus paint record")

    _write_brand(paths, "green-stuff-world", [])

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Paint-EAN lost" in out
    assert "8436574506327" in out


def test_a_product_barcode_does_not_silence_an_unrelated_paint_loss(tmp_path: Path, capsys) -> None:
    """The cross-catalog fallback must be barcode-exact, not a blanket amnesty: an unrelated
    product barcode existing cannot excuse a different paint barcode going missing."""
    repo_root = tmp_path / "repo"
    paths = _init_repo(repo_root)
    _write_catalog(
        paths,
        [{"id": "games-workshop/a", "name": "Thing A", "ean": "5011921194285",
          "eanConfidence": "confirmed"}],
    )
    _write_brand(paths, "citadel-colour", [{"name": "Abaddon Black", "ean": "5011921182848"}])
    _commit(repo_root, "seed both catalogs")

    _write_brand(paths, "citadel-colour", [])

    exit_code = main(["report", "--data", str(paths.root), "--ean-guard"])
    out = capsys.readouterr().out

    assert exit_code == 5
    assert "## Paint-EAN lost" in out
