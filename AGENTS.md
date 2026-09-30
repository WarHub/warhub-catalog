# Working in this repository

Operational rules for a session starting cold. They fill gaps and do not restate the repo's own
documentation:

- what the catalog is, its pipeline and its workflows: [README.md](README.md)
- the values its data obeys (archive everything, keep every published barcode, refuse rather
  than guess): [docs/OBJECTIVES.md](docs/OBJECTIVES.md). Read it before changing what the catalog
  *contains*.
- how to correct one data fact, and which file does it: [docs/adjudication.md](docs/adjudication.md)

## How work lands

- Every change is a pull request. A session pushes and opens it, and the maintainer merges it. A
  session never merges, closes or approves a PR, or enables auto-merge on one, a bot's PR
  included, unless the maintainer names that PR in chat.
- Work in more than one step lands as a stack, one layer per PR, built with the `gh stack`
  extension (`gh extension install github/gh-stack`). The maintainer merges a stack as a single
  operation with `gh stack merge <stack> --squash --yes`. Never hand off "merge bottom-up".
- Open each layer with `gh pr create --base <the layer below>` and a written body, then run
  `gh stack link <every PR, bottom to top>`. `gh stack submit` opens drafts with generated titles.
  A `link` that leaves out a middle PR re-points the next PR's base past it.
- `gh stack init <branches>` adopts branches without restacking them. Run `gh stack rebase`, then
  check each pair with `git diff --stat <parent>..<branch>` before opening PRs.
- The PR body becomes the squash commit. The subject is `area: one sentence saying what changed`,
  and the body pins each claim to a date and a measurement. Update the body when review changes
  the PR.
- README.md and `docs/` state the current rules and cite files. Counts, dates and history go in
  commit messages.
- Judge whether a PR is ready by the check runs on its head commit
  (`gh api repos/WarHub/warhub-catalog/commits/<sha>/check-runs`), not by the rollup. A cancelled
  duplicate run's gate reads FAILURE until `gh run rerun <id>` replaces it.

## CI

- `main` requires `CI gate` and `Data CI gate`, set in repo ruleset 21797609. The org ruleset
  `default-branch-protections` cannot be edited from this repo. A required check must report on
  every PR, so neither workflow takes a `paths:` filter on `pull_request`; ci.yml's header
  explains why.
- A workflow that pushes or opens a PR uses `.github/actions/bot-token`. A push made with
  `GITHUB_TOKEN` starts no workflow runs, so a PR opened that way never gets its required checks.
- The Python suite is `uv run pytest -q`, run from `tools/acquisition` (addopts deselects `live`).
  It takes about 12–14 min in CI and ~27 min locally on Windows, so run it in the background. It
  regenerates `data/catalog/set-contents/` in place: run `git status -- data` afterwards, and
  treat any change there as a stale committed file.
- No test may require the product catalog and the paint catalog to agree. See data-ci.yml's
  header.

## The bot pull requests

`catalog/acquisition` (catalog-acquire.yml: nightly Sun–Fri, weekly sweep on Saturday) and
`catalog/paint-update` (paint-catalog-update.yml: Sunday) are rebuilt on every run: `main` plus
one run's output, force-pushed. Nothing accumulates on them, except that catalog-acquire.yml
takes evidence for sources that did not run from the branch.

An acquisition run that pushes first withdraws any earlier auto-merge on its PR. It enables
auto-merge again only if the run ends fully green and the PR was built on the current `main`. A
run that stops before pushing leaves the PR as it was. The paint PR is always merged by the
maintainer.

- Never commit to either branch, rebase it, press "Update branch" on it, or resolve its conflicts.
  To refresh one, re-run its workflow: `gh workflow run catalog-acquire.yml --ref main -f
  mode=nightly` (about 2 h) or `gh workflow run paint-catalog-update.yml --ref main`. Leave the
  branch in place, because that carryover reads it.
- **After anything under `data/catalog/**` or `data/paints/**` merges to `main`, check the open
  bot PRs.** A bot PR built before that merge holds files derived from inputs `main` no longer
  has. It will either conflict, and resolving the conflict in the branch's favour reverts the
  merge, or merge cleanly and land a tree that no `resolve` produced. Re-run its workflow instead.
  An acquisition PR built before the merge does not auto-merge (its run checks that it was built
  on the current `main`), but it stays open until the next run rebuilds it, and the paint PR stays
  open until someone looks.

## Regenerating the paint catalog

`tools/WarHub.PaintCatalog.Tool` has no reconcile-only mode. Copy the arguments from the "Run paint
catalog tool" step of paint-catalog-update.yml, with the step's two prerequisites:

- a clone of `Arcturus5404/miniature-paints`, passed as `--source <clone>/paints`;
- `gen_paint_barcodes.py`, then `gen_paint_harvest.py`, run first, because the tool reads their
  output. Run these scripts, and `gen_set_contents.py` below, from the repo root as
  `uv run --with pyyaml python tools/acquisition/scripts/<name>`.

Then:

- `--barcodes` takes a file. Given a directory, it silently enriches nothing.
- `--brand` matches the display name in `Configuration/BrandRegistry.cs`, not the slug. It also
  rewrites `data/paints/manifest.yaml` from that one brand, so restore the manifest from git
  afterwards.
- Dropping `--scrape` locally is safe. Keep `--equivalences` whenever a paint identity has moved.
- On Windows the tool writes CRLF, so judge the result by `git diff`, never by a working-tree
  `diff -r`.
- Afterwards, run `gen_set_contents.py` (it reads the brand files), then run
  `uv run warhub-data report --data ../../data --ean-guard` from `tools/acquisition`. Exit 5 means
  a barcode HEAD attests (a confirmed primary, any `additionalEans` entry, any paint barcode) is
  now held by no record.

## Who writes which data file

Generated files are never hand-edited. Change the input and re-run the writer.

| path | writer |
|---|---|
| `data/evidence/**`, `data/snapshots/**` | `warhub-data acquire` |
| `data/catalog/products/*.yaml` | `warhub-data resolve`, then `categorize` |
| `data/catalog/set-contents/*.yaml` | `scripts/gen_set_contents.py` |
| `data/catalog/classifications/products.yaml` | `scripts/classify_local.py` (README, pipeline step 3) |
| `data/review/**` | the stage that reports into it |
| `data/paints/brands/`, `equivalences.yaml`, `manifest.yaml`; `data/state/paint-liveness.yaml` | the paint tool |
| `data/paints/barcodes/`, `harvest/`, `swatches/`, `stores/` | the `gen_paint_*.py` script named in each file's header. A harvest file carries its own prior output forward, so deleting an entry is how one is retired |

Hand-authored files hold the decisions: `data/catalog/matches.yaml`, `overrides.yaml`,
`set-refs.yaml`, `retained-eans.yaml` and `withdrawn-eans.yaml`; everything under
`data/catalog/sources/`, `taxonomy/` and `mappings/`; and `data/paints/overrides.yaml`,
`swatch-sources.yaml` and `store-sources.yaml`.

## Running things by hand

- To answer "did we ever publish barcode X?", ask git, not the evidence ledger:
  `git log -S X --oneline -- data/catalog/products data/paints/brands`. The ledger keeps only each
  source's latest observation, so a barcode no source asserts today may still have been
  published. Each listed commit added or removed the value, and
  `git tag --contains <added> --no-contains <removed>` names the releases that carried it.
- Always pass `--budget` to `warhub-data acquire`. The detail queue is unbounded by default, and
  a run persists nothing until it finishes.
- Measure a category-rule table change with `resolve`, then `categorize`. `categorize` alone
  re-decides only records whose basis is `unknown`, so an edited rule never reaches a record a
  table has already mapped.
- Counts in file headers and comments were measured on the date written beside them. Re-measure
  before relying on one.
- On Windows, write files with `newline="\n"`. `.gitattributes` normalises line endings on
  commit, but a CRLF working copy shows a whole-file diff.
- The catalog has no external consumers yet. Rework a stage rather than add a special case, and
  do not count changed output as a cost in itself. OBJECTIVES still binds: never drop evidence or
  a published barcode.
