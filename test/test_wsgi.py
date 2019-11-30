import pytest
from flask import Flask, jsonify
from hypothesis import given

import schemathesis

EXAMPLE_USERS = [{"name": "test"}]


@pytest.fixture(scope="session")
def flask_app(simple_schema):
    app = Flask("test_app")

    @app.route("/schema.json")
    def schema():
        return simple_schema

    @app.route("/v1/users", methods=["GET"])
    def users():
        return jsonify(EXAMPLE_USERS)

    return app


@pytest.fixture(scope="session")
def schema(flask_app):
    return schemathesis.from_wsgi(flask_app, "/schema.json")


def test_from_wsgi(schema, simple_schema):
    assert schema.raw_schema == simple_schema


def test_call(schema, simple_schema):
    strategy = schema.endpoints["/v1/users"]["GET"].as_strategy()

    @given(case=strategy)
    def test(case):
        response = case.wsgi_call()
        assert response.status_code == 200
        assert response.json == EXAMPLE_USERS

    test()
