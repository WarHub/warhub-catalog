# tools/acquisition/tests/test_classify_supersessions.py
"""Phase 5: manufacturer-asserted lineage -> reviewable supersession proposals.

The generator makes no product-identity judgement (the manufacturer's own re-coding register
asserts that); every test here is about whether an asserted edge is mechanically SAFE to declare.
"""
import json
from pathlib import Path

from warhub_acquisition.classify.supersessions import (
    ALREADY_DECLARED,
    CONFLICTING,
    CONTRADICTS_DECLARED,
    MERGED,
    REGIONAL,
    READY,
    RETIRED_ALREADY_DECLARED,
    SAME_CODE,
    STALE_REGISTER_ROW,
    UNOBSERVED,
    generate_supersession_proposals,
    run_supersession_proposals,
)
from warhub_acquisition.resolve.resolver import DataPaths
from warhub_acquisition.yamlio import read_yaml, write_yaml


def _seed(tmp_path: Path, *, observations: list[dict], products: list[dict], matches: dict | None = None) -> DataPaths:
    paths = DataPaths(tmp_path)
    write_yaml(
        paths.taxonomy / "manufacturers.yaml",
        {"manufacturers": [{"slug": "games-workshop", "name": "Games Workshop",
                            "codePattern": r"\d{11}", "codeStrip": ["GWS"],
                            "gs1Prefixes": ["5011921"], "vendorNames": []}]},
    )
    write_yaml(paths.sources / "mfr-gw-trade.yaml",
               {"id": "mfr-gw-trade", "kind": "manufacturer", "strategy": "gw-trade-sheets"})
    jsonl = paths.evidence_products / "mfr-gw-trade" / "observations.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text(
        "".join(
            json.dumps({"manufacturer": "games-workshop", "firstSeen": "2026-07-01",
                        "lastSeen": "2026-07-30", "extractor": "gw-trade@1", **o},
                       sort_keys=True, separators=(",", ":")) + "\n"
            for o in observations
        ),
        encoding="utf-8", newline="\n",
    )
    write_yaml(paths.catalog_products / "games-workshop.yaml",
               {"manufacturer": "games-workshop", "products": products})
    if matches is not None:
        write_yaml(paths.matches, matches)
    return paths


def _product(entity: str, code: str | None, evidence: list[str], **kw: object) -> dict:
    return {"id": entity, "name": "Widget", "manufacturer": "games-workshop", "productCode": code,
            "status": "current", "firstSeen": "2026-07-01", "evidence": evidence, **kw}


NEW = {"key": "mfr-gw-trade:99120110002", "name": "WIDGET", "sku": "99120110002", "ean": "5011921179398"}


def test_both_sides_observed_as_distinct_entities_is_ready_to_promote(tmp_path: Path) -> None:
    paths = _seed(
        tmp_path,
        observations=[
            {**NEW, "hints": {"supersedes": [{"productCode": "99120110001", "ean": "5011921062164",
                                              "changedOn": "2024-03-01"}]}},
            {"key": "mfr-gw-trade:99120110001", "name": "WIDGET", "sku": "99120110001",
             "ean": "5011921062164", "archived": True},
        ],
        products=[
            _product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:99120110002"]),
            _product("games-workshop/99120110001", "99120110001", ["mfr-gw-trade:99120110001"]),
        ],
    )
    (proposal,) = generate_supersession_proposals(paths)
    assert proposal["bucket"] == READY
    assert proposal["retiredEntity"] == "games-workshop/99120110001"
    assert proposal["survivingEntity"] == "games-workshop/99120110002"
    assert proposal["retiredEan"] == "5011921062164"
    assert proposal["changedOn"] == "2024-03-01"
    assert proposal["assertedBy"] == "mfr-gw-trade:99120110002"


def test_retired_code_nothing_observes_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    # The population no mechanism reaches yet: the register says the code existed, but no source
    # observes it, so there is no entity to link. It must still be counted and carry its barcode.
    paths = _seed(
        tmp_path,
        observations=[{**NEW, "hints": {"supersedes": [{"productCode": "99120110001",
                                                        "ean": "5011921062164"}]}}],
        products=[_product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:99120110002"])],
    )
    (proposal,) = generate_supersession_proposals(paths)
    assert proposal["bucket"] == UNOBSERVED
    assert proposal["retiredEntity"] is None
    assert proposal["retiredEan"] == "5011921062164"


def test_same_code_restatement_is_never_a_supersession(tmp_path: Path) -> None:
    # A re-barcode on the SAME code is an additionalEans case; declaring it would point an entity
    # at itself (which resolve/resolver.py refuses outright).
    paths = _seed(
        tmp_path,
        observations=[{**NEW, "hints": {"supersedes": [{"productCode": "99120110002",
                                                        "ean": "5011921062164"}]}}],
        products=[_product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:99120110002"])],
    )
    (proposal,) = generate_supersession_proposals(paths)
    assert proposal["bucket"] == SAME_CODE


def test_retired_code_observed_only_inside_the_survivor_is_merged_not_ready(tmp_path: Path) -> None:
    # It IS observed, but everything carrying it currently resolves into the surviving entity --
    # promoting needs the union barrier to split them, which is not a paste-and-go change.
    paths = _seed(
        tmp_path,
        observations=[
            {**NEW, "hints": {"supersedes": [{"productCode": "99120110001"}]}},
            {"key": "mfr-gw-trade:old", "name": "WIDGET", "sku": "99120110001", "ean": "5011921179398"},
        ],
        products=[
            _product("games-workshop/99120110002", "99120110002",
                     ["mfr-gw-trade:99120110002", "mfr-gw-trade:old"]),
        ],
    )
    (proposal,) = generate_supersession_proposals(paths)
    assert proposal["bucket"] == MERGED
    assert proposal["retiredEntity"] is None


def test_one_retired_code_claimed_by_two_survivors_is_conflicting(tmp_path: Path) -> None:
    paths = _seed(
        tmp_path,
        observations=[
            {**NEW, "hints": {"supersedes": [{"productCode": "99120110001"}]}},
            {"key": "mfr-gw-trade:99120110003", "name": "OTHER", "sku": "99120110003",
             "ean": "5011921155873", "hints": {"supersedes": [{"productCode": "99120110001"}]}},
            {"key": "mfr-gw-trade:99120110001", "name": "WIDGET", "sku": "99120110001",
             "ean": "5011921062164", "archived": True},
        ],
        products=[
            _product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:99120110002"]),
            _product("games-workshop/99120110003", "99120110003", ["mfr-gw-trade:99120110003"]),
            _product("games-workshop/99120110001", "99120110001", ["mfr-gw-trade:99120110001"]),
        ],
    )
    proposals = generate_supersession_proposals(paths)
    assert {p["bucket"] for p in proposals} == {CONFLICTING}
    assert len(proposals) == 2


def test_declared_edge_is_idempotent_and_never_re_proposed_as_ready(tmp_path: Path) -> None:
    paths = _seed(
        tmp_path,
        observations=[
            {**NEW, "hints": {"supersedes": [{"productCode": "99120110001"}]}},
            {"key": "mfr-gw-trade:99120110001", "name": "WIDGET", "sku": "99120110001",
             "ean": "5011921062164", "archived": True},
        ],
        products=[
            _product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:99120110002"]),
            _product("games-workshop/99120110001", "99120110001", ["mfr-gw-trade:99120110001"]),
        ],
        matches={"supersessions": {"games-workshop/99120110001": "games-workshop/99120110002"}},
    )
    (proposal,) = generate_supersession_proposals(paths)
    assert proposal["bucket"] == ALREADY_DECLARED


def test_artifact_carries_a_paste_ready_block_of_only_the_ready_bucket(tmp_path: Path) -> None:
    paths = _seed(
        tmp_path,
        observations=[
            {**NEW, "hints": {"supersedes": [{"productCode": "99120110001"},
                                             {"productCode": "99120110009"}]}},
            {"key": "mfr-gw-trade:99120110001", "name": "WIDGET", "sku": "99120110001",
             "ean": "5011921062164", "archived": True},
        ],
        products=[
            _product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:99120110002"]),
            _product("games-workshop/99120110001", "99120110001", ["mfr-gw-trade:99120110001"]),
        ],
    )
    summary = run_supersession_proposals(paths)
    assert summary.edges == 2
    assert summary.buckets == {READY: 1, UNOBSERVED: 1}

    document = read_yaml(paths.root / "review" / "supersession-proposals.yaml")
    # only the ready edge is paste-ready; the unobserved one is reported but not promotable
    assert document["readyToPromote"] == {"games-workshop/99120110001": "games-workshop/99120110002"}
    assert document["summary"][READY] == 1
    assert [p["bucket"] for p in document["proposals"]] == [READY, UNOBSERVED]
    # the generator is a pure reader -- matches.yaml is never written
    assert not paths.matches.exists()


def test_regional_fan_out_picks_the_same_region_successor(tmp_path: Path) -> None:
    """A retired code is restated against every REGIONAL edition of its replacement (GW keys the
    register on the code body; the leading pair is the region). Only the edition in the retired
    code's own region succeeds it -- the others have their own retired codes."""
    retired = {"key": "mfr-gw-trade:old", "name": "SKAVEN PAINT SET", "sku": "52170206001",
               "ean": "5011921219285", "archived": True}
    same_region = {"key": "mfr-gw-trade:52170206002", "name": "SKAVEN + PAINT SET ENG",
                   "sku": "52170206002", "ean": "5011921260195",
                   "hints": {"supersedes": [{"productCode": "52170206001"}]}}
    other_region = {"key": "mfr-gw-trade:54170206002", "name": "SKAVEN + PAINT SET GER",
                    "sku": "54170206002", "ean": "5011921260218",
                    "hints": {"supersedes": [{"productCode": "52170206001"}]}}
    paths = _seed(
        tmp_path,
        observations=[retired, same_region, other_region],
        products=[
            _product("games-workshop/52170206001", "52170206001", ["mfr-gw-trade:old"]),
            _product("games-workshop/52170206002", "52170206002", ["mfr-gw-trade:52170206002"]),
            _product("games-workshop/54170206002", "54170206002", ["mfr-gw-trade:54170206002"]),
        ],
    )
    by_survivor = {p["survivingCode"]: p for p in generate_supersession_proposals(paths)}
    assert by_survivor["52170206002"]["bucket"] == READY
    assert by_survivor["54170206002"]["bucket"] == REGIONAL


def test_fan_out_that_is_not_a_regional_split_stays_conflicting(tmp_path: Path) -> None:
    # A filler code reused across unrelated products: the survivors share no code body, so there is
    # nothing deterministic to pick and a human has to look.
    paths = _seed(
        tmp_path,
        observations=[
            {"key": "mfr-gw-trade:a", "name": "TERRAIN A", "sku": "99120599051", "ean": "5011921176953",
             "hints": {"supersedes": [{"productCode": "03040199135"}]}},
            {"key": "mfr-gw-trade:b", "name": "TERRAIN B", "sku": "99120599052", "ean": "5011921177073",
             "hints": {"supersedes": [{"productCode": "03040199135"}]}},
        ],
        products=[
            _product("games-workshop/99120599051", "99120599051", ["mfr-gw-trade:a"]),
            _product("games-workshop/99120599052", "99120599052", ["mfr-gw-trade:b"]),
        ],
    )
    assert {p["bucket"] for p in generate_supersession_proposals(paths)} == {CONFLICTING}


def _pair(retired: str, surviving: str, ean: str, other_ean: str) -> list[dict]:
    return [
        {"key": f"mfr-gw-trade:{surviving}", "name": "WIDGET", "sku": surviving, "ean": ean,
         "hints": {"supersedes": [{"productCode": retired}]}},
        {"key": f"mfr-gw-trade:{retired}", "name": "WIDGET", "sku": retired, "ean": other_ean,
         "hints": {"supersedes": [{"productCode": surviving}]}},
    ]


def test_register_asserting_a_pair_both_ways_never_reaches_ready(tmp_path: Path) -> None:
    """The cumulative register contradicts itself across workbook generations. A 2-cycle would make
    resolve_catalog raise, so neither direction may be promoted -- and demoting only one of them
    would be picking a winner at random."""
    paths = _seed(
        tmp_path,
        observations=_pair("99120204012", "99120204035", "5011921179398", "5011921062164"),
        products=[
            _product("games-workshop/99120204035", "99120204035", ["mfr-gw-trade:99120204035"]),
            _product("games-workshop/99120204012", "99120204012", ["mfr-gw-trade:99120204012"]),
        ],
    )
    assert {p["bucket"] for p in generate_supersession_proposals(paths)} == {CONFLICTING}


def test_edge_contradicting_a_hand_declaration_is_reported_separately(tmp_path: Path) -> None:
    # matches.yaml already declares 012 -> 035 from evidence; the register asserts the reverse.
    # The declaration wins, and the register's edge is named rather than silently dropped.
    paths = _seed(
        tmp_path,
        observations=[
            {"key": "mfr-gw-trade:99120204012", "name": "WIDGET", "sku": "99120204012",
             "ean": "5011921062164", "hints": {"supersedes": [{"productCode": "99120204035"}]}},
        ],
        products=[
            _product("games-workshop/99120204035", "99120204035", ["mfr-gw-trade:99120204035x"]),
            _product("games-workshop/99120204012", "99120204012", ["mfr-gw-trade:99120204012"]),
        ],
        matches={"supersessions": {"games-workshop/99120204012": "games-workshop/99120204035"}},
    )
    (proposal,) = generate_supersession_proposals(paths)
    assert proposal["bucket"] == CONTRADICTS_DECLARED


def test_a_legitimate_chain_is_still_promotable(tmp_path: Path) -> None:
    # A -> B -> C (re-coded twice, or a region folded into another) is legal: only cycles are not.
    paths = _seed(
        tmp_path,
        observations=[
            {"key": "mfr-gw-trade:b", "name": "WIDGET", "sku": "99120110002", "ean": "5011921155873",
             "hints": {"supersedes": [{"productCode": "99120110001"}]}},
            {"key": "mfr-gw-trade:c", "name": "WIDGET", "sku": "99120110003", "ean": "5011921179398",
             "hints": {"supersedes": [{"productCode": "99120110002"}]}},
            {"key": "mfr-gw-trade:a", "name": "WIDGET", "sku": "99120110001", "ean": "5011921062164",
             "archived": True},
        ],
        products=[
            _product("games-workshop/99120110001", "99120110001", ["mfr-gw-trade:a"]),
            _product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:b"]),
            _product("games-workshop/99120110003", "99120110003", ["mfr-gw-trade:c"]),
        ],
    )
    assert {p["bucket"] for p in generate_supersession_proposals(paths)} == {READY}


def test_a_retired_code_already_declared_elsewhere_is_never_ready(tmp_path: Path) -> None:
    """`supersessions` is keyed by the RETIRED id, so promoting a second edge for the same retired
    code REPLACES the first rather than adding to it. Marking it `ready` would let a bulk
    paste-readyToPromote step silently rewrite a hand-verified declaration."""
    paths = _seed(
        tmp_path,
        observations=[
            {**NEW, "hints": {"supersedes": [{"productCode": "99120110001"}]}},
            {"key": "mfr-gw-trade:99120110001", "name": "WIDGET", "sku": "99120110001",
             "ean": "5011921062164", "archived": True},
        ],
        products=[
            _product("games-workshop/99120110002", "99120110002", ["mfr-gw-trade:99120110002"]),
            _product("games-workshop/99120110001", "99120110001", ["mfr-gw-trade:99120110001"]),
            _product("games-workshop/99120110009", "99120110009", ["mfr-gw-trade:99120110009"]),
        ],
        matches={"supersessions": {"games-workshop/99120110001": "games-workshop/99120110009"}},
    )
    (proposal,) = generate_supersession_proposals(paths)
    assert proposal["bucket"] == RETIRED_ALREADY_DECLARED


# --- GW's SS Code: the product's identity across a re-code ---------------------------------------


def _fanout(tmp_path, retired_ssc, claimants):
    """One retired code claimed by several survivors, each with its own SS Code."""
    observations = [
        {"key": f"mfr-gw-trade:{code}", "name": f"WIDGET {code}", "sku": code, "ean": ean,
         "hints": {"sscCode": ssc,
                   "supersedes": [{"productCode": "99120110001",
                                   **({"ssc": retired_ssc} if retired_ssc else {})}]}}
        for code, ean, ssc in claimants
    ]
    observations.append({"key": "mfr-gw-trade:99120110001", "name": "OLD WIDGET",
                         "sku": "99120110001", "ean": "5011921062164", "archived": True,
                         "hints": {"sscCode": retired_ssc} if retired_ssc else {}})
    products = [_product(f"games-workshop/{c}", c, [f"mfr-gw-trade:{c}"]) for c, _, _ in claimants]
    products.append(_product("games-workshop/99120110001", "99120110001",
                             ["mfr-gw-trade:99120110001"]))
    return _seed(tmp_path, observations=observations, products=products)


def test_the_claimant_that_kept_the_retired_ss_code_is_the_successor(tmp_path: Path) -> None:
    """GW's SS Code is the product's identity ACROSS a re-code -- 706 of 727 register pairs keep
    it -- so among COMPETING claimants the one that kept it is the real successor."""
    paths = _fanout(tmp_path, "91-07", [
        ("99120110002", "5011921179398", "91-07"),   # kept the SSC
        ("99120110003", "5011921155873", "80-15"),   # a different product entirely
    ])
    by = {p["survivingCode"]: p for p in generate_supersession_proposals(paths)}
    assert by["99120110002"]["bucket"] == READY
    assert by["99120110003"]["bucket"] == REGIONAL


def test_a_retired_code_no_claimant_kept_is_a_stale_register_row(tmp_path: Path) -> None:
    """Its own SS Code is known and NOT ONE claimant carries it, so it is not their predecessor --
    it is a real product parked in the register's `Old ...` columns while a batch of genuinely new
    products was registered. A verdict, not an unknown."""
    paths = _fanout(tmp_path, "109-19", [
        ("99120110002", "5011921179398", "80-01"),
        ("99120110003", "5011921155873", "80-15"),
    ])
    assert {p["bucket"] for p in generate_supersession_proposals(paths)} == {STALE_REGISTER_ROW}


def test_an_unknown_retired_ss_code_is_never_convicted_on_absence(tmp_path: Path) -> None:
    # Requires knowing BOTH sides. Without the retired SSC the rule must stay silent.
    paths = _fanout(tmp_path, None, [
        ("99120110002", "5011921179398", "80-01"),
        ("99120110003", "5011921155873", "80-15"),
    ])
    assert {p["bucket"] for p in generate_supersession_proposals(paths)} == {CONFLICTING}


def test_a_declared_edge_inside_an_unresolved_fanout_is_not_re_reported(tmp_path: Path) -> None:
    # Both claimants share the SSC so it cannot split them; one is already declared. Re-flagging
    # the settled edge as `conflicting` would hide that only its RIVAL needs a human.
    paths = _fanout(tmp_path, "91-07", [
        ("99120110002", "5011921179398", "91-07"),
        ("99120110003", "5011921155873", "91-07"),
    ])
    write_yaml(paths.matches,
               {"supersessions": {"games-workshop/99120110001": "games-workshop/99120110002"}})
    by = {p["survivingCode"]: p for p in generate_supersession_proposals(paths)}
    assert by["99120110002"]["bucket"] == ALREADY_DECLARED
    assert by["99120110003"]["bucket"] == CONFLICTING
