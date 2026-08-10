from warhub_acquisition.yamlio import dump_yaml, load_yaml


def test_numeric_like_strings_are_quoted() -> None:
    text = dump_yaml({"ean": "0812152031524", "sku": "99120110077", "n": 5})
    assert "ean: '0812152031524'" in text
    assert "sku: '99120110077'" in text
    assert "n: 5" in text


def test_date_like_strings_are_quoted() -> None:
    assert "firstSeen: '2026-07-07'" in dump_yaml({"firstSeen": "2026-07-07"})


def test_round_trip_preserves_leading_zeros() -> None:
    data = {"ean": "0812152031524"}
    assert load_yaml(dump_yaml(data)) == data


def test_multiline_uses_literal_block() -> None:
    text = dump_yaml({"description": "line one\nline two"})
    assert "description: |-" in text


def test_insertion_order_preserved_and_deterministic() -> None:
    data = {"b": 1, "a": 2}
    text = dump_yaml(data)
    assert text == "b: 1\na: 2\n"
    assert dump_yaml(data) == text


def test_long_urls_not_wrapped() -> None:
    url = "https://example.com/" + "x" * 300
    assert f"url: {url}\n" in dump_yaml({"url": url})


def test_nested_lists_are_indented() -> None:
    text = dump_yaml({"products": [{"id": "a", "name": "X"}]})
    assert text == "products:\n  - id: a\n    name: X\n"


def test_yaml12_numeric_like_strings_are_quoted() -> None:
    text = dump_yaml({"a": "5e3", "b": "1E10", "c": "-3e-2", "d": "1.5e10", "e": "0x1A", "f": "0o17"})
    assert "a: '5e3'" in text
    assert "b: '1E10'" in text
    assert "c: '-3e-2'" in text
    assert "d: '1.5e10'" in text
    assert "e: '0x1A'" in text
    assert "f: '0o17'" in text


def test_the_c_loader_agrees_with_the_pure_python_one() -> None:
    """`load_yaml`/`read_yaml` moved to libyaml's parser on 2026-08-06 for a 7.5x speedup.

    The swap is only safe because the two parsers agree, and the shapes worth checking are the
    ones this repo's own dumper deliberately produces: force-quoted number-like strings (barcodes
    with a leading zero, dotless scientific notation), literal blocks for embedded newlines, and
    unicode that `allow_unicode=True` writes raw. A silent divergence on any of those would
    corrupt an archive rather than fail a run.
    """
    import yaml

    from warhub_acquisition.yamlio import _Loader, dump_yaml

    sample = {
        "barcodes": ["0812152031524", "5011921182848", "5e3", "0x1f", "0o17"],
        "name": "Nightsahde Purple Dip",           # a real store typo, kept verbatim
        "unicode": "CHAR´S PINK 60ML. – Ätzend",   # real GSW/AK title characters
        "block": "line one\nline two\n",
        "nested": {"empty_list": [], "null": None, "zero": 0, "false": False},
        "floats": [3.7375, 2.125, 1e-3],
    }
    text = dump_yaml(sample)
    assert yaml.load(text, Loader=_Loader) == yaml.safe_load(text)
    assert yaml.load(text, Loader=_Loader) == sample

    # The barcodes must survive as STRINGS, not be re-read as ints/floats -- the reason
    # `_represent_str` force-quotes them in the first place.
    assert yaml.load(text, Loader=_Loader)["barcodes"] == sample["barcodes"]
