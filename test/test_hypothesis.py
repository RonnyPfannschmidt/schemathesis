from base64 import b64decode
from typing import Any, Type, TypeVar, Union

import pytest
from hypothesis import given, strategies

from schemathesis import Case, register_string_format
from schemathesis._hypothesis import PARAMETERS, get_case_strategy, get_examples
from schemathesis.exceptions import InvalidSchema
from schemathesis.models import Endpoint

T = TypeVar("T", bound=Union[Endpoint, Case])


def _make(cls: Type[T], **kwargs: Any) -> T:
    return cls("/users", "POST", **kwargs)


def make_endpoint(**kwargs: Any) -> Endpoint:
    return _make(Endpoint, definition={}, **kwargs)


def make_case(**kwargs: Any) -> Case:
    kwargs.setdefault("body", None)
    return _make(Case, **kwargs)


@pytest.mark.parametrize("name", sorted(PARAMETERS))
def test_get_examples(name):
    example = {"name": "John"}
    endpoint = make_endpoint(
        **{
            name: {
                "required": ["name"],
                "type": "object",
                "additionalProperties": False,
                "properties": {"name": {"type": "string"}},
                "example": example,
            }
        }
    )
    assert list(get_examples(endpoint)) == [make_case(**{name: example})]


def test_no_body_in_get():
    endpoint = Endpoint(
        path="/api/success",
        method="GET",
        definition={},
        query={
            "required": ["name"],
            "type": "object",
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}},
            "example": {"name": "John"},
        },
    )
    assert list(get_examples(endpoint))[0].body is None


def test_invalid_body_in_get():
    endpoint = Endpoint(
        path="/foo",
        method="GET",
        definition={},
        body={"required": ["foo"], "type": "object", "properties": {"foo": {"type": "string"}}},
    )
    with pytest.raises(InvalidSchema, match=r"^Body parameters are defined for GET request.$"):
        get_case_strategy(endpoint)


def test_warning():
    example = {"name": "John"}
    endpoint = make_endpoint(**{"query": {"example": example}})
    with pytest.warns(None) as record:
        assert list(get_examples(endpoint)) == [make_case(**{"query": example})]
    assert not record


@pytest.mark.filterwarnings("ignore:.*method is good for exploring strategies.*")
def test_custom_strategies():
    register_string_format("even_4_digits", strategies.from_regex(r"\A[0-9]{4}\Z").filter(lambda x: int(x) % 2 == 0))
    endpoint = make_endpoint(
        query={
            "required": ["id"],
            "type": "object",
            "additionalProperties": False,
            "properties": {"id": {"type": "string", "format": "even_4_digits"}},
        }
    )
    result = get_case_strategy(endpoint).example()
    assert len(result.query["id"]) == 4
    assert int(result.query["id"]) % 2 == 0


def test_register_default_strategies():
    # If schemathesis is imported
    import schemathesis

    # Default strategies should be registered
    from hypothesis_jsonschema._impl import STRING_FORMATS

    assert "binary" in STRING_FORMATS
    assert "byte" in STRING_FORMATS


@pytest.mark.filterwarnings("ignore:.*method is good for exploring strategies.*")
def test_default_strategies_binary():
    endpoint = make_endpoint(
        form_data={
            "required": ["file"],
            "type": "object",
            "additionalProperties": False,
            "properties": {"file": {"type": "string", "format": "binary"}},
        }
    )
    result = get_case_strategy(endpoint).example()
    assert isinstance(result.form_data["file"], bytes)


@pytest.mark.filterwarnings("ignore:.*method is good for exploring strategies.*")
def test_default_strategies_bytes():
    endpoint = make_endpoint(
        body={
            "required": ["byte"],
            "type": "object",
            "additionalProperties": False,
            "properties": {"byte": {"type": "string", "format": "byte"}},
        }
    )
    result = get_case_strategy(endpoint).example()
    assert isinstance(result.body["byte"], str)
    b64decode(result.body["byte"])


@pytest.mark.parametrize(
    "values, error",
    (
        (("valid", "invalid"), f"strategy must be of type {strategies.SearchStrategy}, not {str}"),
        ((123, strategies.from_regex(r"\d")), f"name must be of type {str}, not {int}"),
    ),
)
def test_invalid_custom_strategy(values, error):
    with pytest.raises(TypeError) as exc:
        register_string_format(*values)
    assert error in str(exc.value)


def test_valid_headers(base_url):
    endpoint = Endpoint(
        "/api/success",
        "GET",
        definition={},
        base_url=base_url,
        headers={
            "properties": {"api_key": {"name": "api_key", "in": "header", "type": "string"}},
            "additionalProperties": False,
            "type": "object",
            "required": ["api_key"],
        },
    )

    @given(case=get_case_strategy(endpoint))
    def inner(case):
        case.call()

    inner()
