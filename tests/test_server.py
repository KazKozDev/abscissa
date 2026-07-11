import asyncio
import json

from abscissa import server


def test_page_size_is_bounded() -> None:
    assert server._page_size(-4) == 1
    assert server._page_size(10) == 10
    assert server._page_size(500) == 50


def test_get_current_user_returns_viewer(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_gql",
        lambda *_: {"viewer": {"id": "user-1", "name": "Ada", "email": "ada@example.com"}},
    )

    result = json.loads(server.get_current_user())

    assert result["id"] == "user-1"


def test_project_membership_tools_use_issue_update(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        return {"issueUpdate": {"issue": {"identifier": "ABS-1", "project": None}}}

    monkeypatch.setattr(server, "_gql", fake_gql)

    json.loads(server.set_issue_project("ABS-1", "project-1"))
    json.loads(server.remove_issue_from_project("ABS-1"))

    assert calls[0][1]["input"] == {"projectId": "project-1"}
    assert calls[1][1]["input"] == {"projectId": None}


def test_get_user_issues_resolves_authenticated_viewer(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        if "viewer" in query:
            return {"viewer": {"id": "viewer-1"}}
        return {
            "issues": {
                "nodes": [{"identifier": "ABS-1"}],
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-2"},
            }
        }

    monkeypatch.setattr(server, "_gql", fake_gql)

    result = json.loads(server.get_user_issues(limit=100))

    assert result == {"items": [{"identifier": "ABS-1"}], "next_cursor": "cursor-2"}
    assert calls[1][1]["filter"]["assignee"]["id"]["eq"] == "viewer-1"
    assert calls[1][1]["first"] == 50


def test_search_issues_returns_cursor_pagination(monkeypatch) -> None:
    captured = {}

    def fake_gql(query, variables=None):
        captured["query"] = query
        captured["variables"] = variables
        return {
            "issues": {
                "nodes": [{"identifier": "ABS-2"}],
                "pageInfo": {"hasNextPage": False, "endCursor": "unused"},
            }
        }

    monkeypatch.setattr(server, "_gql", fake_gql)

    result = json.loads(server.search_issues(query="test", limit=5, cursor="cursor-1"))

    assert result == {"items": [{"identifier": "ABS-2"}], "next_cursor": None}
    assert captured["variables"]["after"] == "cursor-1"
    assert captured["variables"]["first"] == 5


def test_cycle_tools_paginate_and_filter_by_team(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        if "teams(filter" in query:
            return {"teams": {"nodes": [{"id": "team-1"}]}}
        if "cycles(" in query:
            return {
                "cycles": {
                    "nodes": [{"id": "cycle-1", "name": "Sprint 1"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cycle-cursor"},
                }
            }
        return {
            "cycle": {
                "issues": {
                    "nodes": [{"identifier": "ABS-3"}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }

    monkeypatch.setattr(server, "_gql", fake_gql)

    cycles = json.loads(server.list_cycles(team_id="ABS", cursor="old-cursor"))
    issues = json.loads(server.list_cycle_issues("cycle-1"))

    assert cycles["next_cursor"] == "cycle-cursor"
    assert calls[1][1]["filter"]["team"]["id"]["eq"] == "team-1"
    assert calls[1][1]["after"] == "old-cursor"
    assert issues == {"items": [{"identifier": "ABS-3"}], "next_cursor": None}


def test_cycle_mutation_tools_use_exact_linear_inputs(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        if "teams(filter" in query:
            return {"teams": {"nodes": [{"id": "team-1"}]}}
        if "cycleCreate" in query:
            return {"cycleCreate": {"cycle": {"id": "cycle-1", "name": "Sprint 1"}}}
        if "cycleUpdate" in query:
            return {"cycleUpdate": {"cycle": {"id": "cycle-1", "name": "Sprint 2"}}}
        return {"cycleArchive": {"success": True}}

    monkeypatch.setattr(server, "_gql", fake_gql)

    created = json.loads(
        server.create_cycle(
            "ABS", "Sprint 1", "2026-07-13T09:00:00Z", "2026-07-27T09:00:00Z", "Planning cycle"
        )
    )
    updated = json.loads(server.update_cycle("cycle-1", name="Sprint 2"))
    archived = json.loads(server.archive_cycle("cycle-1", confirm=True))

    assert created == {"id": "cycle-1", "name": "Sprint 1"}
    assert calls[1][1]["input"] == {
        "teamId": "team-1",
        "name": "Sprint 1",
        "startsAt": "2026-07-13T09:00:00Z",
        "endsAt": "2026-07-27T09:00:00Z",
        "description": "Planning cycle",
    }
    assert updated == {"id": "cycle-1", "name": "Sprint 2"}
    assert calls[2][1] == {"id": "cycle-1", "input": {"name": "Sprint 2"}}
    assert archived == {"success": True}
    assert calls[3][1] == {"id": "cycle-1"}


def test_dependency_tools_preserve_direction_and_relation_id(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        if "issueRelationCreate" in query:
            return {"issueRelationCreate": {"issueRelation": {"id": "relation-3", "type": "blocks"}}}
        if "issueRelationDelete" in query:
            return {"issueRelationDelete": {"success": True}}
        return {
            "issue": {
                "relations": {
                    "nodes": [
                        {"id": "relation-1", "type": "blocks", "relatedIssue": {"identifier": "ABS-2"}},
                        {"id": "relation-other", "type": "related", "relatedIssue": {"identifier": "ABS-4"}},
                    ],
                    "pageInfo": {"hasNextPage": True, "endCursor": "blocks-cursor"},
                },
                "inverseRelations": {
                    "nodes": [{"id": "relation-2", "type": "blocks", "issue": {"identifier": "ABS-0"}}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }
        }

    monkeypatch.setattr(server, "_gql", fake_gql)

    dependencies = json.loads(server.list_issue_dependencies("ABS-1"))
    created = json.loads(server.add_issue_dependency("ABS-1", "ABS-2"))
    removed = json.loads(server.remove_issue_dependency("relation-3"))

    assert dependencies["blocks"] == [{"relation_id": "relation-1", "issue": {"identifier": "ABS-2"}}]
    assert dependencies["blocked_by"] == [{"relation_id": "relation-2", "issue": {"identifier": "ABS-0"}}]
    assert dependencies["next_cursors"] == {"blocks": "blocks-cursor", "blocked_by": None}
    assert created == {"id": "relation-3", "type": "blocks"}
    assert removed == {"success": True}
    assert calls[1][1]["input"] == {
        "issueId": "ABS-1",
        "relatedIssueId": "ABS-2",
        "type": "blocks",
    }


def test_destructive_operations_require_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(server, "_gql", lambda *_: (_ for _ in ()).throw(AssertionError("API called")))

    assert "requires explicit confirmation" in server.delete_issue("ABS-1")
    assert "requires explicit confirmation" in server.archive_issue("ABS-1")
    assert "requires explicit confirmation" in server.archive_project("project-1")
    assert "requires explicit confirmation" in server.archive_cycle("cycle-1")


def test_project_detail_tools_use_current_linear_project_fields(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        if "teams(filter" in query:
            return {"teams": {"nodes": [{"id": "team-1"}]}}
        return {
            "projectUpdate": {
                "project": {
                    "id": "project-1",
                    "priority": 2,
                    "startDate": "2026-07-11",
                }
            }
        }

    monkeypatch.setattr(server, "_gql", fake_gql)

    result = json.loads(
        server.update_project_details(
            "project-1",
            content="## Launch",
            lead_id="user-1",
            member_ids="user-1,user-2",
            priority=2,
            start_date="2026-07-11",
            target_date="2026-07-18",
            team_ids="ABS",
            clear_lead=True,
        )
    )

    assert result["id"] == "project-1"
    assert calls[1][1]["input"] == {
        "content": "## Launch",
        "leadId": None,
        "memberIds": ["user-1", "user-2"],
        "priority": 2,
        "startDate": "2026-07-11",
        "targetDate": "2026-07-18",
        "teamIds": ["team-1"],
    }


def test_project_label_tools_and_updates_use_expected_linear_operations(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        if "projectLabels" in query:
            return {
                "projectLabels": {
                    "nodes": [{"id": "label-1", "name": "growth"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "labels-cursor"},
                }
            }
        if "projectLabelCreate" in query:
            return {"projectLabelCreate": {"projectLabel": {"id": "label-2", "name": "launch"}}}
        if "projectAddLabel" in query:
            return {"projectAddLabel": {"project": {"id": "project-1", "name": "Abscissa"}}}
        if "projectRemoveLabel" in query:
            return {"projectRemoveLabel": {"project": {"id": "project-1", "name": "Abscissa"}}}
        if "projectUpdateCreate" in query:
            return {"projectUpdateCreate": {"projectUpdate": {"id": "update-1", "body": "Shipped"}}}
        return {
            "projectUpdates": {
                "nodes": [{"id": "update-1", "body": "Shipped"}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }

    monkeypatch.setattr(server, "_gql", fake_gql)

    labels = json.loads(server.list_project_labels(limit=100, cursor="old-cursor"))
    created_label = json.loads(server.create_project_label("launch", "#F59E0B", "Launch work"))
    attached = json.loads(server.add_project_label("project-1", "label-2"))
    removed = json.loads(server.remove_project_label("project-1", "label-2"))
    update = json.loads(server.create_project_update("project-1", "Shipped", "onTrack"))
    updates = json.loads(server.list_project_updates("project-1"))

    assert labels == {"items": [{"id": "label-1", "name": "growth"}], "next_cursor": "labels-cursor"}
    assert created_label == {"id": "label-2", "name": "launch"}
    assert attached["id"] == removed["id"] == "project-1"
    assert update == {"id": "update-1", "body": "Shipped"}
    assert updates == {"items": [{"id": "update-1", "body": "Shipped"}], "next_cursor": None}
    assert calls[0][1] == {"first": 50, "after": "old-cursor"}
    assert calls[1][1]["input"] == {
        "name": "launch",
        "color": "#F59E0B",
        "description": "Launch work",
    }
    assert calls[2][1] == {"id": "project-1", "labelId": "label-2"}
    assert calls[3][1] == {"id": "project-1", "labelId": "label-2"}
    assert calls[4][1]["input"] == {
        "projectId": "project-1",
        "body": "Shipped",
        "health": "onTrack",
    }
    assert calls[5][1] == {"projectId": "project-1", "first": 50, "after": None}


def test_project_status_updates_resolve_current_status_ids(monkeypatch) -> None:
    calls = []

    def fake_gql(query, variables=None):
        calls.append((query, variables))
        if "projectStatuses" in query:
            return {
                "projectStatuses": {
                    "nodes": [
                        {"id": "status-1", "name": "In Progress", "type": "started"},
                        {"id": "status-2", "name": "Canceled", "type": "canceled"},
                    ]
                }
            }
        return {"projectUpdate": {"project": {"id": "project-1", "name": "Abscissa"}}}

    monkeypatch.setattr(server, "_gql", fake_gql)

    updated = json.loads(server.update_project("project-1", state="started"))
    archived = json.loads(server.archive_project("project-1", confirm=True))

    assert updated["id"] == archived["id"] == "project-1"
    assert calls[1][1]["input"] == {"statusId": "status-1"}
    assert calls[3][1]["input"] == {"statusId": "status-2"}


def test_mcp_lists_all_tools_and_marks_destructive_ones() -> None:
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}

    assert len(tools) == 42
    assert tools["delete_issue"].annotations.destructiveHint is True
    assert tools["archive_issue"].annotations.destructiveHint is True
    assert tools["archive_project"].annotations.destructiveHint is True
    assert tools["archive_cycle"].annotations.destructiveHint is True
    assert tools["set_issue_project"].annotations.openWorldHint is True
    assert tools["add_issue_dependency"].annotations.openWorldHint is True
    assert tools["create_cycle"].annotations.openWorldHint is True
    assert tools["update_project_details"].annotations.openWorldHint is True
    assert tools["create_project_label"].annotations.openWorldHint is True
    assert tools["create_project_update"].annotations.openWorldHint is True
