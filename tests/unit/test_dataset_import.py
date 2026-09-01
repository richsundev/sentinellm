import pytest

from sentinellm.services.dataset_import import (
    DatasetImportError,
    parse_csv,
    parse_dataset_file,
    parse_jsonl,
)


def test_parse_jsonl_happy_path() -> None:
    content = (
        '{"question": "Q1?", "context": "C1", "expected_answer": "A1"}\n'
        '{"question": "Q2?", "context": "C2", "expected_answer": "A2", "metadata": {"topic": "x"}}\n'
    )
    records = parse_jsonl(content)
    assert len(records) == 2
    assert records[0].question == "Q1?"
    assert records[0].context == "C1"
    assert records[1].metadata == {"topic": "x"}


def test_parse_jsonl_skips_blank_lines() -> None:
    content = '{"question": "Q1?"}\n\n\n{"question": "Q2?"}\n'
    assert len(parse_jsonl(content)) == 2


def test_parse_jsonl_infers_metadata_from_extra_fields() -> None:
    content = '{"question": "Q1?", "difficulty": "easy", "category": "billing"}\n'
    records = parse_jsonl(content)
    assert records[0].metadata == {"difficulty": "easy", "category": "billing"}


def test_parse_jsonl_rejects_invalid_json_with_line_number() -> None:
    content = '{"question": "Q1?"}\nnot json\n'
    with pytest.raises(DatasetImportError, match="line 2"):
        parse_jsonl(content)


def test_parse_jsonl_rejects_missing_question() -> None:
    content = '{"context": "C1"}\n'
    with pytest.raises(DatasetImportError, match="question"):
        parse_jsonl(content)


def test_parse_csv_happy_path() -> None:
    content = "question,context,expected_answer\nQ1?,C1,A1\nQ2?,C2,A2\n"
    records = parse_csv(content)
    assert len(records) == 2
    assert records[0].question == "Q1?"
    assert records[0].context == "C1"
    assert records[0].expected_answer == "A1"


def test_parse_csv_folds_extra_columns_into_metadata() -> None:
    content = "question,context,difficulty\nQ1?,C1,easy\n"
    records = parse_csv(content)
    assert records[0].metadata == {"difficulty": "easy"}


def test_parse_csv_rejects_missing_question_column() -> None:
    with pytest.raises(DatasetImportError, match="question"):
        parse_csv("context,expected_answer\nC1,A1\n")


def test_parse_csv_rejects_blank_question_value() -> None:
    with pytest.raises(DatasetImportError, match="row 2"):
        parse_csv("question,context\n,C1\n")


def test_parse_dataset_file_dispatches_by_extension() -> None:
    jsonl_records = parse_dataset_file("bench.jsonl", '{"question": "Q1?"}\n')
    csv_records = parse_dataset_file("bench.csv", "question\nQ1?\n")
    assert len(jsonl_records) == 1
    assert len(csv_records) == 1


def test_parse_dataset_file_rejects_unsupported_extension() -> None:
    with pytest.raises(DatasetImportError, match="unsupported file type"):
        parse_dataset_file("bench.txt", "question\nQ1?\n")


def test_parse_dataset_file_rejects_empty_result() -> None:
    with pytest.raises(DatasetImportError, match="no records"):
        parse_dataset_file("bench.jsonl", "\n\n")
