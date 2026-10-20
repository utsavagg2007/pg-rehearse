from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from psycopg.types.numeric import DecimalBinaryDumper, NumericBinaryLoader

from pg_rehearse.errors import ConfigurationError, UnsupportedInputError
from pg_rehearse.fixtures.seed import verify_baseline
from pg_rehearse.fixtures.validate import validate_fixtures
from pg_rehearse.migration.classify import baseline_catalog
from pg_rehearse.migration.preflight import parse_document
from pg_rehearse.models import FixtureSpec, Scalar
from pg_rehearse.workload.assertions import normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1e2", "100"),
        ("-0.00", "0.00"),
        ("-0e2", "0"),
        ("1e-9", "1E-9"),
        ("12.50", "12.50"),
        (
            "-1.234567890123456789012345678901234567890",
            "-1.234567890123456789012345678901234567890",
        ),
        ("1e-200", "1E-200"),
    ],
)
def test_numeric_normalization_matches_postgres_binary_codec(raw: str, expected: str) -> None:
    value = Decimal(raw)
    readback = NumericBinaryLoader(1700).load(DecimalBinaryDumper(Decimal).dump(value))
    with localcontext() as context:
        context.prec = 6
        assert normalize(value) == normalize(readback) == expected


@pytest.mark.parametrize("raw", ["1e2", "-0.00", "1e-200", "12345678901234567890.12345678900"])
def test_baseline_verification_accepts_exact_numeric_readback(raw: str) -> None:
    schema = parse_document("CREATE TABLE t (value numeric NOT NULL)", "schema.sql")
    fixtures = FixtureSpec(tables={"t": [{"value": raw}]})
    readback = NumericBinaryLoader(1700).load(DecimalBinaryDumper(Decimal).dump(Decimal(raw)))
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.description = [SimpleNamespace(name="value")]
    cursor.__iter__.return_value = iter([(readback,)])
    evidence = verify_baseline(connection, schema, fixtures, 42)
    assert evidence.success
    assert evidence.table_rows == {"t": 1}
    assert evidence.data_sha256


@pytest.mark.parametrize("readback", [Decimal("12.5"), Decimal("12.51")])
def test_baseline_verification_still_rejects_scale_or_value_changes(readback: Decimal) -> None:
    schema = parse_document("CREATE TABLE t (value numeric NOT NULL)", "schema.sql")
    fixtures = FixtureSpec(tables={"t": [{"value": "12.50"}]})
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.description = [SimpleNamespace(name="value")]
    cursor.__iter__.return_value = iter([(readback,)])
    evidence = verify_baseline(connection, schema, fixtures, 42)
    assert not evidence.success
    assert evidence.error_kind == "verification_error"


@pytest.mark.parametrize(
    "kind,literal,expected",
    [
        ("double precision", "1.5", 1.5),
        ("double precision", "1e2", 100.0),
        ("double precision", "-1.5", -1.5),
        ("double precision", "1", 1.0),
        ("bigint", "2147483648", 2147483648),
        ("bigint", "-2147483649", -2147483649),
        ("bigint", "9223372036854775807", 9223372036854775807),
        ("bigint", "-9223372036854775808", -9223372036854775808),
        ("numeric", "1e2", Decimal("1e2")),
        (
            "numeric",
            "12345678901234567890.12345678900",
            Decimal("12345678901234567890.12345678900"),
        ),
        ("text", "'1.5'", "1.5"),
        ("boolean", "false", False),
        ("integer", "1", 1),
    ],
)
def test_omitted_fixture_defaults_use_declared_numeric_type(
    kind: str, literal: str, expected: object
) -> None:
    schema = parse_document(
        f"CREATE TABLE t (value {kind} NOT NULL DEFAULT {literal})", "schema.sql"
    )
    rows = validate_fixtures(FixtureSpec(tables={"t": [{}]}), baseline_catalog(schema), "fixtures")
    actual = rows["t"][0]["value"]
    assert type(actual) is type(expected)
    assert actual == expected
    if isinstance(actual, Decimal):
        assert actual.as_tuple() == expected.as_tuple()


@pytest.mark.parametrize(
    "kind,literal",
    [
        ("double precision", "'1.5'"),
        ("double precision", "true"),
        ("double precision", "1e400"),
        ("bigint", "'2147483648'"),
        ("bigint", "1.5"),
        ("bigint", "1e2"),
        ("bigint", "9223372036854775808"),
        ("bigint", "-9223372036854775809"),
        ("integer", "2147483648"),
        ("smallint", "32768"),
        ("boolean", "1.5"),
        ("numeric", "true"),
    ],
)
def test_numeric_defaults_preserve_type_and_bounds_checks(kind: str, literal: str) -> None:
    schema = parse_document(
        f"CREATE TABLE t (value {kind} NOT NULL DEFAULT {literal})", "schema.sql"
    )
    with pytest.raises(ConfigurationError):
        validate_fixtures(FixtureSpec(tables={"t": [{}]}), baseline_catalog(schema), "fixtures")


def test_oversized_integer_default_is_an_input_error() -> None:
    schema = parse_document(
        "CREATE TABLE t (value bigint DEFAULT " + "9" * 4301 + ")", "schema.sql"
    )
    with pytest.raises(ConfigurationError, match="supported bounds"):
        baseline_catalog(schema)


@pytest.mark.parametrize("literal", ["1 + 2", "1.5::double precision", "abs(-1)"])
def test_defaults_still_require_scalar_literals(literal: str) -> None:
    with pytest.raises(UnsupportedInputError, match="scalar literals"):
        baseline_catalog(
            parse_document(f"CREATE TABLE t (value numeric DEFAULT {literal})", "schema.sql")
        )


@pytest.mark.parametrize("kind,value", [("double precision", "1.5"), ("bigint", "2147483648")])
def test_fixture_strings_do_not_gain_numeric_default_coercions(kind: str, value: Scalar) -> None:
    schema = parse_document(f"CREATE TABLE t (value {kind})", "schema.sql")
    with pytest.raises(ConfigurationError):
        validate_fixtures(
            FixtureSpec(tables={"t": [{"value": value}]}), baseline_catalog(schema), "fixtures"
        )
