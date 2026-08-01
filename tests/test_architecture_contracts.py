import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ARCHITECTURE_ROOT = Path(__file__).resolve().parent.parent / "docs" / "architecture"

CONTRACT_FIXTURES = [
    (
        ARCHITECTURE_ROOT / "schemas" / "normalized-change.schema.json",
        ARCHITECTURE_ROOT / "examples" / "normalized-change.example.json",
    ),
    (
        ARCHITECTURE_ROOT / "schemas" / "migration-evidence.schema.json",
        ARCHITECTURE_ROOT / "examples" / "migration-evidence.example.json",
    ),
]


@pytest.mark.parametrize(("schema_path", "example_path"), CONTRACT_FIXTURES)
def test_architecture_example_satisfies_contract(schema_path: Path, example_path: Path):
    schema = json.loads(schema_path.read_text())
    example = json.loads(example_path.read_text())

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
