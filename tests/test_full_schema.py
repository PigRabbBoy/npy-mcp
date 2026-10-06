"""get-database --full-schema (issue #31).

One extractor in unpy-core (unpy.schema) feeds the CLI JSON, the CLI
markdown and the MCP get_database(full_schema=true) section, so the two
transports can't drift. Fixtures are raw collection records shaped like
Notion's internal API; no live calls.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-core", "src"))
_MCP = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src")
if _MCP not in sys.path:
    sys.path.insert(0, _MCP)

from unpy.collection import Collection
from unpy.schema import describe_schema, full_schema_markdown

TASKS = "coll-tasks"
PROJECTS = "coll-projects"


def _ptr(cid):
    return {"id": cid, "table": "collection", "spaceId": "space-1"}


def _fpp(pid, cid):
    return ["‣", [["fpp", {"property": pid, "collection": _ptr(cid)}]]]


TASKS_SCHEMA = {
    "title": {"name": "Name", "type": "title"},
    "st01": {
        "name": "Status",
        "type": "status",
        "options": [
            {"id": "o1", "value": "Not started", "color": "default"},
            {"id": "o2", "value": "In progress", "color": "blue"},
            {"id": "o3", "value": "Done", "color": "green"},
        ],
        "groups": [
            {"id": "g1", "name": "To-do", "color": "gray", "optionIds": ["o1"]},
            {"id": "g2", "name": "In progress", "color": "blue", "optionIds": ["o2"]},
            {"id": "g3", "name": "Complete", "color": "green", "optionIds": ["o3"]},
        ],
    },
    "se01": {
        "name": "Priority",
        "type": "select",
        "options": [{"id": "p1", "value": "High"}, {"id": "p2", "value": "Low"}],
    },
    "ms01": {
        "name": "Tags",
        "type": "multi_select",
        "options": [{"id": "t1", "value": "api"}, {"id": "t2", "value": "ui"}],
    },
    "gone": None,  # tombstoned: the Notion UI nulls deleted properties
    "dead": {"name": "Old", "type": "text", "alive": False},
    # two-way, single: synced property "Tasks" (rv01) lives on Projects
    "rl01": {
        "name": "Project",
        "type": "relation",
        "collection_id": PROJECTS,
        "collection_pointer": _ptr(PROJECTS),
        "limit": 1,
        "version": "v2",
        "property": "rv01",
        "autoRelate": {"enabled": False},
    },
    # one-way: no synced property
    "rl02": {
        "name": "See also",
        "type": "relation",
        "collection_id": PROJECTS,
        "collection_pointer": _ptr(PROJECTS),
        "version": "v2",
        "autoRelate": {"enabled": False},
    },
    # two-way self relation: each side points at the other in this schema
    "rl03": {
        "name": "Parent task",
        "type": "relation",
        "collection_id": TASKS,
        "collection_pointer": _ptr(TASKS),
        "limit": 1,
        "version": "v2",
        "property": "rl04",
    },
    "rl04": {
        "name": "Sub-tasks",
        "type": "relation",
        "collection_id": TASKS,
        "collection_pointer": _ptr(TASKS),
        "version": "v2",
        "property": "rl03",
    },
    # show_original is stored as an ABSENT aggregation field (issue #14)
    "ru01": {
        "name": "Project owner",
        "type": "rollup",
        "version": "v2",
        "rollup_type": "relation",
        "relation_property": "rl01",
        "target_property": "ow01",
        "target_property_type": "person",
    },
    "ru02": {
        "name": "Sub-task count",
        "type": "rollup",
        "version": "v2",
        "relation_property": "rl04",
        "target_property": "title",
        "aggregation": "count",
    },
    "fo01": {
        "name": "Signed",
        "type": "formula",
        "version": "v2",
        "formula2": {
            "code": [["contains(format("], _fpp("st01", TASKS), ['), "Signed")']],
            "result_type": {"type": "boolean"},
        },
    },
    # member access on a related page: the ref after "current." belongs to
    # the Projects collection
    "fo02": {
        "name": "Project code",
        "type": "formula",
        "version": "v2",
        "formula2": {
            "code": [
                _fpp("rl01", TASKS),
                [".map(current."],
                _fpp("cd01", PROJECTS),
                [")"],
            ]
        },
    },
}

PROJECTS_SCHEMA = {
    "title": {"name": "Project name", "type": "title"},
    "cd01": {"name": "Code", "type": "text"},
    "ow01": {"name": "Owner", "type": "person"},
    "rv01": {
        "name": "Tasks",
        "type": "relation",
        "collection_id": TASKS,
        "collection_pointer": _ptr(TASKS),
        "version": "v2",
        "property": "rl01",
    },
}


class _FakeParent:
    def __init__(self, bid):
        self.id = bid


class _FakeCollection:
    """Stands in for unpy.collection.Collection: schema via .get('schema')."""

    def __init__(self, cid, name, schema, client=None):
        self.id = cid
        self.name = name
        self._schema = schema
        self._client = client
        self.parent = _FakeParent(f"block-{cid}")

    def get(self, key, default=None):
        return {"schema": self._schema}.get(key, default)

    def get_schema_properties(self):
        return Collection.get_schema_properties(self)

    def get_rows(self, **kwargs):
        return []


class _FakeBlock:
    def __init__(self, bid, collection):
        self.id = bid
        self.collection = collection

    def get(self, key, default=None):
        return default


class _FakeClient:
    """get_collection serves the fixture collections and logs each load."""

    def __init__(self):
        self.loaded = []
        self.collections = {}
        self.blocks = {}

    def get_collection(self, cid, force_refresh=False):
        self.loaded.append(cid)
        return self.collections.get(cid)

    def get_block(self, bid, force_refresh=False):
        return self.blocks.get(bid)


def _workspace(tasks_schema=None):
    client = _FakeClient()
    tasks = _FakeCollection(TASKS, "Tasks", tasks_schema or TASKS_SCHEMA, client)
    projects = _FakeCollection(PROJECTS, "Projects", PROJECTS_SCHEMA, client)
    client.collections = {TASKS: tasks, PROJECTS: projects}
    client.blocks = {"block-tasks": _FakeBlock("block-tasks", tasks)}
    return client, tasks


def _by_name(entries):
    return {e["name"]: e for e in entries}


def _formula_schema(code):
    return {
        "title": {"name": "Name", "type": "title"},
        "st01": TASKS_SCHEMA["st01"],
        "fx": {"name": "F", "type": "formula", "formula2": {"code": code}},
    }


class TestDescribeSchema:
    def test_skips_tombstoned_and_keeps_schema_order(self):
        _, tasks = _workspace()
        ids = [e["id"] for e in describe_schema(tasks)]
        assert "gone" not in ids and "dead" not in ids
        live = [k for k, v in TASKS_SCHEMA.items() if v and v.get("alive") is not False]
        assert ids == live

    def test_every_entry_has_id_name_type(self):
        _, tasks = _workspace()
        title = _by_name(describe_schema(tasks))["Name"]
        assert title == {"id": "title", "name": "Name", "type": "title"}

    def test_select_and_multi_select_options_in_order(self):
        _, tasks = _workspace()
        e = _by_name(describe_schema(tasks))
        assert e["Priority"]["options"] == ["High", "Low"]
        assert e["Tags"]["options"] == ["api", "ui"]
        assert "groups" not in e["Priority"]

    def test_status_options_and_groups(self):
        _, tasks = _workspace()
        st = _by_name(describe_schema(tasks))["Status"]
        assert st["options"] == ["Not started", "In progress", "Done"]
        assert st["groups"] == [
            {"name": "To-do", "options": ["Not started"]},
            {"name": "In progress", "options": ["In progress"]},
            {"name": "Complete", "options": ["Done"]},
        ]

    def test_relation_two_way_resolves_reverse_name_on_target(self):
        _, tasks = _workspace()
        rel = _by_name(describe_schema(tasks))["Project"]
        assert rel["target"] == PROJECTS
        assert rel["single"] is True
        assert rel["reverse"] == "Tasks"
        assert rel["reverse_id"] == "rv01"

    def test_relation_one_way_has_no_reverse(self):
        _, tasks = _workspace()
        rel = _by_name(describe_schema(tasks))["See also"]
        assert rel["target"] == PROJECTS
        assert rel["single"] is False
        assert rel["reverse"] is None
        assert rel["reverse_id"] is None

    def test_relation_self_two_way_uses_own_schema(self):
        client, tasks = _workspace()
        e = _by_name(describe_schema(tasks))
        assert e["Parent task"]["target"] == TASKS
        assert e["Parent task"]["single"] is True
        assert e["Parent task"]["reverse"] == "Sub-tasks"
        assert e["Sub-tasks"]["reverse"] == "Parent task"
        # own schema comes from the collection itself, never re-fetched
        assert TASKS not in client.loaded

    def test_rollup_show_original_returns_names_and_ids(self):
        _, tasks = _workspace()
        ru = _by_name(describe_schema(tasks))["Project owner"]
        assert ru["relation_property"] == "Project"
        assert ru["relation_property_id"] == "rl01"
        assert ru["target_property"] == "Owner"
        assert ru["target_property_id"] == "ow01"
        assert ru["aggregation"] == "show_original"

    def test_rollup_count_over_self_relation(self):
        _, tasks = _workspace()
        ru = _by_name(describe_schema(tasks))["Sub-task count"]
        assert ru["relation_property"] == "Sub-tasks"
        assert ru["target_property"] == "Name"
        assert ru["target_property_id"] == "title"
        assert ru["aggregation"] == "count"

    def test_formula_refs_render_as_prop_name(self):
        _, tasks = _workspace()
        fo = _by_name(describe_schema(tasks))["Signed"]
        assert fo["expression"] == 'contains(format(prop("Status")), "Signed")'
        assert fo["raw_expression"] == 'contains(format({0}), "Signed")'
        assert fo["refs"] == [
            {"property": "st01", "collection_id": TASKS, "name": "Status"}
        ]

    def test_formula_member_ref_resolves_against_related_collection(self):
        _, tasks = _workspace()
        fo = _by_name(describe_schema(tasks))["Project code"]
        assert fo["expression"] == 'prop("Project").map(current.prop("Code"))'
        assert fo["raw_expression"] == "{0}.map(current.{1})"
        assert [r["name"] for r in fo["refs"]] == ["Project", "Code"]

    def test_formula_literal_braces_are_not_treated_as_refs(self):
        code = [['concat("{0}", '], _fpp("st01", TASKS), [")"]]
        _, coll = _workspace(_formula_schema(code))
        fo = _by_name(describe_schema(coll))["F"]
        assert fo["expression"] == 'concat("{0}", prop("Status"))'

    def test_formula_name_with_quote_is_escaped(self):
        schema = _formula_schema([["empty("], _fpp("q1", TASKS), [")"]])
        schema["q1"] = {"name": 'Say "hi"', "type": "text"}
        _, coll = _workspace(schema)
        fo = _by_name(describe_schema(coll))["F"]
        assert fo["expression"] == 'empty(prop("Say \\"hi\\""))'

    def test_unloadable_target_keeps_ids_and_does_not_crash(self):
        def broken(cid):
            raise RuntimeError("offline")

        _, tasks = _workspace()
        e = _by_name(describe_schema(tasks, load_schema=broken))
        assert e["Project"]["reverse"] is None
        assert e["Project"]["reverse_id"] == "rv01"
        assert e["Project owner"]["target_property"] is None
        assert e["Project owner"]["target_property_id"] == "ow01"
        assert e["Project code"]["refs"][1]["name"] is None
        assert e["Project code"]["refs"][1]["property"] == "cd01"
        # own-schema names still resolve
        assert e["Project owner"]["relation_property"] == "Project"

    def test_each_foreign_collection_loads_once(self):
        client, tasks = _workspace()
        describe_schema(tasks)
        assert client.loaded.count(PROJECTS) == 1

    def test_json_serializable(self):
        _, tasks = _workspace()
        json.dumps(describe_schema(tasks))


class TestEncodedFormulaRoundTrip:
    """Formulas written by create-database/add-column (encode_expr, name-only
    fpp metas) read back in the consumer's prop("Name") form."""

    def test_encode_expr_round_trips_to_prop_form(self):
        from unpy_mcp import formula_eval as fev

        code = fev.encode_expr('if(empty({"Status"}), false, true)')
        _, coll = _workspace(_formula_schema(code))
        fo = _by_name(describe_schema(coll))["F"]
        assert fo["expression"] == 'if(empty(prop("Status")), false, true)'

    def test_build_expr_shares_the_segment_walk(self):
        from unpy_mcp import formula_eval as fev

        _, tasks = _workspace()
        for e in describe_schema(tasks):
            if e["type"] == "formula":
                src, refs = fev.build_expr(TASKS_SCHEMA[e["id"]])
                assert src == e["raw_expression"]
                assert len(refs) == len(e["refs"])


class TestFullSchemaMarkdown:
    def test_section_lines(self):
        _, tasks = _workspace()
        lines = full_schema_markdown(describe_schema(tasks))
        text = "\n".join(lines)
        assert lines[0] == "## Full schema"
        assert "  - **Status** (status) [id: st01]" in lines
        assert "      options: ['Not started', 'In progress', 'Done']" in lines
        assert f"      target: {PROJECTS}" in lines
        assert "      single: yes" in lines
        assert "      reverse_name: Tasks [id: rv01]" in lines
        assert "      relation_property: Project [id: rl01]" in lines
        assert "      target_property: Owner [id: ow01]" in lines
        assert "      aggregation: show_original" in lines
        assert '      expression: contains(format(prop("Status")), "Signed")' in lines
        assert "{0}" not in text


def _section(text):
    """The '## Full schema' block, up to the next blank line."""
    out = []
    for line in text.split("## Full schema", 1)[1].split("\n")[1:]:
        if not line.strip():
            break
        out.append(line)
    return out


class TestCliFullSchema:
    def test_json_full_schema_entries(self):
        from unpy_cli.render import render_database

        _, tasks = _workspace()
        data = json.loads(
            render_database(tasks, sample_rows=0, format="json", full_schema=True)
        )
        assert data["data_source_id"] == TASKS
        assert data["schema"] == describe_schema(tasks)

    def test_json_default_stays_name_and_type(self):
        from unpy_cli.render import render_database

        _, tasks = _workspace()
        data = json.loads(render_database(tasks, sample_rows=0, format="json"))
        assert all(set(e) == {"name", "type"} for e in data["schema"])
        assert len(data["schema"]) == len(describe_schema(tasks))

    def test_markdown_full_schema_matches_mcp(self):
        from unittest.mock import patch

        import unpy_mcp.server as srv
        from unpy_cli.render import render_database

        client, tasks = _workspace()
        cli_md = render_database(tasks, sample_rows=0, full_schema=True)
        with patch.object(srv, "_get_client", return_value=client):
            mcp_md = srv.get_database("block-tasks", sample_rows=0, full_schema=True)
        assert _section(cli_md) == _section(mcp_md)
        assert _section(cli_md)  # not vacuous

    def test_markdown_without_flag_has_no_full_schema(self):
        from unpy_cli.render import render_database

        _, tasks = _workspace()
        assert "## Full schema" not in render_database(tasks, sample_rows=0)

    def test_cli_flag_end_to_end(self):
        from unittest.mock import patch

        from typer.testing import CliRunner
        from unpy_cli import cli as cli_mod

        client, _ = _workspace()
        with patch.object(cli_mod, "get_client", return_value=client):
            res = CliRunner().invoke(
                cli_mod.app,
                ["get-database", "block-tasks", "--full-schema", "--format", "json", "-s", "0"],
            )
        assert res.exit_code == 0, res.output
        rel = _by_name(json.loads(res.output)["schema"])["Project"]
        assert rel["reverse"] == "Tasks"


class TestMcpFullSchema:
    def test_mcp_shows_names_not_placeholders(self):
        from unittest.mock import patch

        import unpy_mcp.server as srv

        client, _ = _workspace()
        with patch.object(srv, "_get_client", return_value=client):
            out = srv.get_database("block-tasks", sample_rows=0, full_schema=True)
        section = "\n".join(_section(out))
        assert 'expression: contains(format(prop("Status")), "Signed")' in section
        assert "{0}" not in section
        assert "relation_property: Project [id: rl01]" in section
        assert "reverse_name: Tasks [id: rv01]" in section
