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
