import asyncio
import logging
import threading
from enum import Enum
from functools import wraps
from time import sleep
from typing import Any, Callable, Dict, List, Tuple

import click
import yaml
from aiohttp import web

from schemathesis.cli import CSVOption

try:
    from . import handlers
except ImportError:
    # Case if the app is started from the command line
    import handlers


class Endpoint(Enum):
    success = ("GET", "/api/success", handlers.success)
    failure = ("GET", "/api/failure", handlers.failure)
    slow = ("GET", "/api/slow", handlers.slow)
    path_variable = ("GET", "/api/path_variable/{key}", handlers.success)
    unsatisfiable = ("POST", "/api/unsatisfiable", handlers.unsatisfiable)
    invalid = ("POST", "/api/invalid", handlers.unsatisfiable)
    flaky = ("GET", "/api/flaky", handlers.flaky)
    multipart = ("POST", "/api/multipart", handlers.multipart)
    teapot = ("POST", "/api/teapot", handlers.teapot)
    text = ("GET", "/api/text", handlers.text)
    malformed_json = ("GET", "/api/malformed_json", handlers.malformed_json)
    invalid_response = ("GET", "/api/invalid_response", handlers.invalid_response)
    custom_format = ("GET", "/api/custom_format", handlers.success)
    invalid_path_parameter = ("GET", "/api/invalid_path_parameter/{id}", handlers.success)


def create_app(endpoints: Tuple[str, ...] = ("success", "failure")) -> web.Application:
    """Factory for aioHTTP app.

    Each endpoint except the one for schema saves requests in the list shared in the app instance and could be
    used to verify generated requests.

    >>> def test_something(app, server):
    >>>     # make some request to the app here
    >>>     assert app["incoming_requests"][0].method == "GET"
    """
    incoming_requests = []
    schema_requests = []

    async def schema(request: web.Request) -> web.Response:
        schema_data = request.app["config"]["schema_data"]
        content = yaml.dump(schema_data)
        schema_requests.append(request)
        return web.Response(body=content)

    def wrapper(handler: Callable) -> Callable:
        @wraps(handler)
        async def inner(request: web.Request) -> web.Response:
            if "Content-Type" in request.headers and not request.headers["Content-Type"].startswith("multipart/"):
                await request.read()
            incoming_requests.append(request)
            return await handler(request)

        return inner

    app = web.Application()
    app.add_routes(
        [web.get("/swagger.yaml", schema)]
        + [web.route(item.value[0], item.value[1], wrapper(item.value[2])) for item in Endpoint]
    )
    app["incoming_requests"] = incoming_requests
    app["schema_requests"] = schema_requests
    app["config"] = {"should_fail": True, "schema_data": make_schema(endpoints)}
    return app


def reset_app(app: web.Application, endpoints: Tuple[str, ...] = ("success", "failure")) -> None:
    """Clean up all internal containers of the application and resets its config."""
    app["incoming_requests"][:] = []
    app["schema_requests"][:] = []
    app["config"].update({"should_fail": True, "schema_data": make_schema(endpoints)})


def make_schema(endpoints: Tuple[str, ...]) -> Dict:
    """Generate a Swagger 2.0 schema with the given endpoints.

    Example:
        If `endpoints` is ("success", "failure")
        then the app will contain GET /success and GET /failure
    """
    template: Dict[str, Any] = {
        "swagger": "2.0",
        "info": {"title": "Example API", "description": "An API to test Schemathesis", "version": "1.0.0"},
        "host": "127.0.0.1:8888",
        "basePath": "/api",
        "schemes": ["http"],
        "produces": ["application/json"],
        "paths": {},
    }
    for endpoint in endpoints:
        method, path, _ = Endpoint[endpoint].value
        path = path.replace(template["basePath"], "")
        if endpoint == "unsatisfiable":
            schema = {
                "parameters": [
                    {
                        "name": "id",
                        "in": "body",
                        "required": True,
                        # Impossible to satisfy
                        "schema": {"allOf": [{"type": "integer"}, {"type": "string"}]},
                    }
                ]
            }
        elif endpoint == "flaky":
            schema = {"parameters": [{"name": "id", "in": "query", "required": True, "type": "integer"}]}
        elif endpoint == "path_variable":
            schema = {
                "parameters": [{"name": "key", "in": "path", "required": True, "type": "string", "minLength": 1}],
                "responses": {200: {"description": "OK"}},
            }
        elif endpoint == "invalid":
            schema = {"parameters": [{"name": "id", "in": "query", "required": True, "type": "int"}]}
        elif endpoint == "custom_format":
            schema = {
                "parameters": [{"name": "id", "in": "query", "required": True, "type": "string", "format": "digits"}]
            }
        elif endpoint == "multipart":
            schema = {
                "parameters": [
                    {"in": "formData", "name": "key", "required": True, "type": "string"},
                    {"in": "formData", "name": "value", "required": True, "type": "integer"},
                ]
            }
        elif endpoint == "teapot":
            schema = {"produces": ["application/json"], "responses": {200: {"description": "OK"}}}
        elif endpoint == "invalid_path_parameter/{id}":
            schema = {"parameters": [{"name": "id", "in": "path", "required": False, "type": "integer"}]}
        else:
            schema = {
                "responses": {
                    200: {
                        "description": "OK",
                        "schema": {
                            "type": "object",
                            "properties": {"success": {"type": "boolean"}},
                            "required": ["success"],
                        },
                    },
                    "default": {"description": "Default response"},
                }
            }
        template["paths"][path] = {method.lower(): schema}
    return template


def _run_server(app: web.Application, port: int) -> None:
    """Run the given app on the given port.

    Intended to be called as a target for a separate thread.
    NOTE. `aiohttp.web.run_app` works only in the main thread and can't be used here (or maybe can we some tuning)
    """
    # Set a loop for a new thread (there is no by default for non-main threads)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "127.0.0.1", port)
    loop.run_until_complete(site.start())
    loop.run_forever()


def run_server(app: web.Application, port: int, timeout: float = 0.05) -> None:
    """Start a thread with the given aiohttp application."""
    server_thread = threading.Thread(target=_run_server, args=(app, port))
    server_thread.daemon = True
    server_thread.start()
    sleep(timeout)


@click.command()
@click.argument("port", type=int)
@click.option("--endpoints", type=CSVOption(Endpoint))
def run_app(port: int, endpoints: List[Endpoint]) -> None:
    if endpoints is not None:
        prepared_endpoints = tuple(endpoint.name for endpoint in endpoints)
    else:
        prepared_endpoints = ("success", "failure")
    app = create_app(prepared_endpoints)
    web.run_app(app, port=port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    run_app()
