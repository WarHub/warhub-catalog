"""Taxonomy: manufacturer registry with code patterns and vendor-name mapping."""
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from warhub_acquisition.yamlio import read_yaml


class CodeRewrite(BaseModel):
    """One spelling of a code, rewritten to the maker's own. `match` is a regex anchored at both
    ends and `replace` may use its groups (`re.sub` syntax). Applied after upper-casing and
    `codeStrip`, before `codePattern`."""

    model_config = ConfigDict(extra="forbid")
    match: str
    replace: str
    # Why this spelling exists and who writes it -- required, because a rewrite is an identity
    # decision and the next reader needs the measurement behind it, not just the regex.
    reason: str


class Manufacturer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    name: str
    codePattern: str | None = None
    codeStrip: list[str] = Field(default_factory=list)
    # A RETAILER'S SPELLING OF THE MAKER'S CODE, and the maker's spelling it stands for. `codeStrip`
    # removes a store's house prefix; this is for the spellings a strip cannot express -- a prefix
    # SWAPPED rather than added (`MANKWR407` for Mantic's `MGKWR407`), a hyphen dropped and a
    # letter inserted (`SFGGT023` for Steamforged's `SFGT-023`). Measured 2026-09-02 over the whole
    # catalog: 332 published records held two spellings of one code, and 61 products were
    # published TWICE, once under each, because the spellings never met.
    codeRewrite: list[CodeRewrite] = Field(default_factory=list)
    gs1Prefixes: list[str] = Field(default_factory=list)
    vendorNames: list[str] = Field(default_factory=list)


class Taxonomy:
    def __init__(self, manufacturers: dict[str, Manufacturer]) -> None:
        self.manufacturers = manufacturers
        self._vendor_index: dict[str, str] = {}
        for manufacturer in manufacturers.values():
            for vendor in [manufacturer.name, *manufacturer.vendorNames]:
                folded = vendor.casefold()
                existing = self._vendor_index.get(folded)
                if existing is not None and existing != manufacturer.slug:
                    raise ValueError(
                        f"vendor name {vendor!r} claimed by both {existing!r} and {manufacturer.slug!r}"
                    )
                self._vendor_index[folded] = manufacturer.slug

    @classmethod
    def load(cls, directory: Path) -> "Taxonomy":
        data = read_yaml(directory / "manufacturers.yaml")
        manufacturers = [Manufacturer.model_validate(entry) for entry in data["manufacturers"]]
        return cls({m.slug: m for m in manufacturers})

    def manufacturer_for_vendor(self, vendor: str) -> str | None:
        return self._vendor_index.get(vendor.casefold())

    def normalize_code(self, manufacturer: str, sku: str | None) -> str | None:
        spec = self.manufacturers.get(manufacturer)
        if spec is None or spec.codePattern is None or not sku:
            return None
        code = sku.upper().replace(" ", "")
        for prefix in spec.codeStrip:
            code = code.removeprefix(prefix.upper())
        code = code.removesuffix("-EN")
        for rewrite in spec.codeRewrite:
            code = re.sub(rf"^(?:{rewrite.match})$", rewrite.replace, code, count=1)
        match = re.fullmatch(spec.codePattern, code, flags=re.IGNORECASE)
        if match is None:
            return None
        # A NAMED GROUP DECLARES THE CANONICAL CODE, and without one the whole match is the code
        # (which is every pattern that predates this). It exists because some manufacturers' own
        # SKU carries a suffix that is not part of the identity: Corvus Belli writes the same
        # product as `280873` and as `280873-0990`, and 405 of its 794 codes appear BOTH ways
        # across the sources this repo harvests. Matching both forms as distinct codes would split
        # 405 products in two; refusing the suffixed form would drop most of the corpus. Neither is
        # what a `codeStrip` prefix list can express, because the suffix is a pattern rather than a
        # literal -- so the pattern names the part that IS the code.
        #
        # Only the FIRST non-empty named group is read, so a pattern with alternatives gives each
        # branch its own name and the branch that matched wins.
        named = [value for value in match.groupdict().values() if value]
        return named[0] if named else code


class Settings:
    """The SETTINGS a game is set in, and which setting each game belongs to.

    A setting is the fictional universe or the historical period a game is played in -- Warhammer
    40,000, Age of Sigmar, Middle-earth, the Second World War -- and it is the layer ABOVE a game
    system. Kill Team, Necromunda, The Horus Heresy and Warhammer 40,000 are four games in one
    setting; Bolt Action, Konflikt '47 and Achtung Panzer! are three games in another.

    WHY IT IS A SEPARATE AXIS AND NOT A WIDER GAME SLUG. A Black Library novel belongs to the
    Warhammer 40,000 setting and to no game at all; a laser-cut Normandy farmhouse is sold for Bolt
    Action and is just as much a Konflikt '47 building. Neither is a game membership, and stamping
    a game on them was the choice this catalog used to face -- the Black Library rows were vetoed
    for exactly that reason and stayed `unknown`. A product's game systems DERIVE its settings
    (`resolve/attributes.py::complete_membership_bases`); a product with no game can still be
    placed in a setting by a rule, and a product that belongs to nothing at all can say so.

    ONE SETTING PER GAME. `game-systems.yaml` names each game's setting, and it is a scalar because
    no game in the taxonomy is played in two universes -- measured against the publishers' own
    descriptions when this was introduced (2026-09-02). A catch-all bucket (`catchAll: true`) is
    the one entry allowed to name none: it is not a game.
    """

    def __init__(
        self,
        labels: dict[str, str],
        of_game: dict[str, str],
        settingless: frozenset[str] = frozenset(),
        catch_alls: frozenset[str] = frozenset(),
    ) -> None:
        self.labels = labels
        self.of_game = of_game
        # Games declared `catchAll: true` in game-systems.yaml -- buckets rather than claims. A
        # record holding only a catch-all has not been placed in a game (see
        # resolve/attributes.py::complete_membership_bases and categorize/stage.py).
        self.catch_alls = catch_alls
        # Games that belong to NO setting as a fact rather than as a gap -- Steamforged's Epic
        # Encounters are 5e-compatible boxes played in whatever campaign the buyer runs. A product
        # of such a game is `not-applicable` on the settings axis, where a product of a game this
        # register simply has no entry for is `unknown`.
        self.settingless = settingless

    @classmethod
    def load(cls, taxonomy_dir: Path) -> "Settings":
        settings_path = taxonomy_dir / "settings.yaml"
        labels: dict[str, str] = {}
        if settings_path.exists():
            for entry in (read_yaml(settings_path) or {}).get("settings") or []:
                labels[entry["slug"]] = entry["label"]
        of_game: dict[str, str] = {}
        settingless: set[str] = set()
        catch_alls: set[str] = set()
        systems_path = taxonomy_dir / "game-systems.yaml"
        if systems_path.exists():
            for entry in (read_yaml(systems_path) or {}).get("gameSystems") or []:
                if entry.get("settingless"):
                    settingless.add(entry["slug"])
                if entry.get("catchAll"):
                    catch_alls.add(entry["slug"])
                setting = entry.get("setting")
                if setting is None:
                    continue
                if setting not in labels:
                    raise ValueError(
                        f"game-systems.yaml: {entry['slug']!r} names setting {setting!r}, "
                        f"which settings.yaml does not declare"
                    )
                of_game[entry["slug"]] = setting
        return cls(labels, of_game, frozenset(settingless), frozenset(catch_alls))

    def for_games(self, game_systems: list[str]) -> list[str]:
        """The settings a list of games derives, sorted, without duplicates."""
        return sorted({self.of_game[g] for g in game_systems if g in self.of_game})

    def all_settingless(self, game_systems: list[str]) -> bool:
        """True when every one of these games is declared to belong to no setting."""
        return bool(game_systems) and all(g in self.settingless for g in game_systems)


def load_labels(taxonomy_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    def read_map(path: Path, key: str) -> dict[str, str]:
        if not path.exists():
            return {}
        data = read_yaml(path)
        return {entry["slug"]: entry["label"] for entry in data[key]}

    return (
        read_map(taxonomy_dir / "game-systems.yaml", "gameSystems"),
        read_map(taxonomy_dir / "factions.yaml", "factions"),
    )
