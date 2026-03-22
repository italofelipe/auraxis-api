from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from graphql import build_schema, get_introspection_query, graphql_sync, print_schema
from graphql.type import GraphQLSchema

from app.graphql.docs_catalog import build_graphql_operations_manifest

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]
GraphQLDocsSource = Literal["runtime", "sdl"]

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPHQL_SCHEMA_PATH = REPO_ROOT / "schema.graphql"
GRAPHQL_INTROSPECTION_PATH = REPO_ROOT / "graphql.introspection.json"
GRAPHQL_OPERATIONS_MANIFEST_PATH = REPO_ROOT / "graphql.operations.manifest.json"


@dataclass(frozen=True)
class GraphQLDocsBundle:
    schema_sdl: str
    introspection: JsonObject
    operations_manifest: list[dict[str, object]]


def _normalize_json_object(value: object) -> JsonObject:
    return cast(JsonObject, json.loads(json.dumps(value, sort_keys=True)))


def _load_runtime_schema() -> GraphQLSchema:
    from app.graphql.schema import schema

    return cast(GraphQLSchema, schema.graphql_schema)


def _load_sdl_schema() -> GraphQLSchema:
    return build_schema(GRAPHQL_SCHEMA_PATH.read_text(encoding="utf-8"))


def _read_schema_sdl(source: GraphQLDocsSource, graphql_schema: GraphQLSchema) -> str:
    if source == "sdl":
        return GRAPHQL_SCHEMA_PATH.read_text(encoding="utf-8").strip() + "\n"
    return cast(str, print_schema(graphql_schema)).strip() + "\n"


def _build_introspection(graphql_schema: GraphQLSchema) -> JsonObject:
    query = get_introspection_query(
        descriptions=True,
        specified_by_url=True,
        directive_is_repeatable=True,
        schema_description=True,
        input_value_deprecation=True,
    )
    result = graphql_sync(graphql_schema, query)
    if result.errors:
        messages = "; ".join(error.message for error in result.errors)
        raise RuntimeError(f"Falha ao gerar introspection GraphQL: {messages}")
    return _normalize_json_object({"data": result.data})


def build_graphql_docs_bundle(
    source: GraphQLDocsSource = "runtime",
) -> GraphQLDocsBundle:
    graphql_schema = (
        _load_runtime_schema() if source == "runtime" else _load_sdl_schema()
    )
    return GraphQLDocsBundle(
        schema_sdl=_read_schema_sdl(source, graphql_schema),
        introspection=_build_introspection(graphql_schema),
        operations_manifest=build_graphql_operations_manifest(),
    )


def write_graphql_docs_bundle(bundle: GraphQLDocsBundle) -> None:
    GRAPHQL_SCHEMA_PATH.write_text(bundle.schema_sdl, encoding="utf-8")
    GRAPHQL_INTROSPECTION_PATH.write_text(
        json.dumps(bundle.introspection, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    GRAPHQL_OPERATIONS_MANIFEST_PATH.write_text(
        json.dumps(
            bundle.operations_manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_committed_graphql_docs_bundle() -> GraphQLDocsBundle:
    return GraphQLDocsBundle(
        schema_sdl=GRAPHQL_SCHEMA_PATH.read_text(encoding="utf-8"),
        introspection=cast(
            JsonObject,
            json.loads(GRAPHQL_INTROSPECTION_PATH.read_text(encoding="utf-8")),
        ),
        operations_manifest=cast(
            list[dict[str, object]],
            json.loads(GRAPHQL_OPERATIONS_MANIFEST_PATH.read_text(encoding="utf-8")),
        ),
    )
