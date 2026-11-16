import pytest

from pwrhub import vdf


def test_nested_blocks_and_escapes():
    data = vdf.loads('"Root"\n{\n  // yorum\n  "Path" "C:\\\\Games\\\\Steam"\n  "sub" { "a" "1" }\n}')
    assert data == {"root": {"path": "C:\\Games\\Steam", "sub": {"a": "1"}}}


def test_braces_inside_strings_are_text():
    assert vdf.loads('"a" { "name" "Oyun {Özel}" }') == {"a": {"name": "Oyun {Özel}"}}


@pytest.mark.parametrize("bad", ['"a" {', '"a" "b" }', '"a" { "x" }', '"a" "yarım'])
def test_broken_input_raises(bad):
    with pytest.raises(vdf.VDFError):
        vdf.loads(bad)
