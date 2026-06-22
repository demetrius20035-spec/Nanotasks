import pytest

from nanotasks.textutil import load_yaml_lenient, strip_code_fences


def test_strip_plain():
    assert strip_code_fences("abc") == "abc"


def test_strip_fence():
    assert strip_code_fences("x\n```py\ncode line\n```\ny").strip() == "code line"


def test_strip_picks_longest_block():
    text = "```\na\n```\ntext\n```\nlonger block here\n```"
    assert "longer block here" in strip_code_fences(text)


def test_lenient_fenced():
    assert load_yaml_lenient("Вот ответ:\n```yaml\na: 1\nb: 2\n```") == {"a": 1, "b": 2}


def test_lenient_prose_then_yaml():
    assert load_yaml_lenient("Пояснение перед.\naudit: плохо\nfixes: []") == {
        "audit": "плохо", "fixes": []
    }


def test_lenient_raises_on_garbage():
    with pytest.raises(ValueError):
        load_yaml_lenient("просто строка текста без структуры")
