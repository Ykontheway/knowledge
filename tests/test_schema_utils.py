from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts.schema_utils import check_or_write, dump_json, insert_definition_strict


def test_dump_json_preserves_chinese_indentation_order_and_final_newline() -> None:
    rendered = dump_json({"标题": "中文", "items": [1, {"name": "测试"}]})
    assert rendered == (
        '{\n  "标题": "中文",\n  "items": [\n    1,\n    {\n      "name": "测试"\n    }\n  ]\n}\n'
    )
    assert rendered.encode("utf-8").endswith(b"}\n")
    assert dump_json({}) == "{}\n"


def test_insert_definition_strict_allows_identical_fragments() -> None:
    definitions: dict[str, Any] = {}
    fragment = {"type": "object", "properties": {"title": {"type": "string"}}}
    insert_definition_strict(definitions, "Example", fragment)
    insert_definition_strict(
        definitions, "Example", {"properties": {"title": {"type": "string"}}, "type": "object"}
    )
    assert definitions == {"Example": fragment}


@pytest.mark.parametrize(
    "message", ["conflicting schema definition", "conflicting schema fragment"]
)
def test_insert_definition_strict_rejects_conflict_without_overwriting(message: str) -> None:
    definitions: dict[str, Any] = {"Example": {"type": "string"}}
    with pytest.raises(ValueError) as error:
        insert_definition_strict(
            definitions, "Example", {"type": "integer"}, conflict_message=message
        )
    assert str(error.value) == f"{message}: Example"
    assert definitions == {"Example": {"type": "string"}}


def test_check_missing_output_does_not_create_file_or_parent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "missing" / "schema.json"
    assert (
        check_or_write(
            output,
            "{}\n",
            check=True,
            up_to_date_message="current",
            out_of_date_message="stale",
        )
        == 1
    )
    assert not output.exists()
    assert not output.parent.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "stale\n"


def test_check_mismatch_does_not_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "schema.json"
    original = b"stale\r\n"
    output.write_bytes(original)
    assert (
        check_or_write(
            output,
            "{}\n",
            check=True,
            up_to_date_message="current",
            out_of_date_message="stale",
        )
        == 1
    )
    assert output.read_bytes() == original
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "stale\n"


def test_check_matching_output_is_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "schema.json"
    output.write_text("{}\n", encoding="utf-8")

    def forbid_write(self: Path, *args: Any, **kwargs: Any) -> None:
        pytest.fail("--check must not write files or create directories")

    monkeypatch.setattr(Path, "write_text", forbid_write)
    monkeypatch.setattr(Path, "mkdir", forbid_write)
    assert (
        check_or_write(
            output,
            "{}\n",
            check=True,
            up_to_date_message="current",
            out_of_date_message="stale",
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "current\n"
    assert captured.err == ""


def test_normal_write_creates_parents_and_preserves_relative_path_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    output = Path("new directory/nested/schema.json")
    rendered = dump_json({"标题": "中文"})
    for content in (rendered, "{}\n"):
        assert (
            check_or_write(
                output,
                content,
                check=False,
                up_to_date_message="current",
                out_of_date_message="stale",
            )
            == 0
        )
        assert output.read_bytes() == content.encode("utf-8")
        captured = capsys.readouterr()
        assert captured.out == f"Wrote {output}\n"
        assert captured.err == ""
