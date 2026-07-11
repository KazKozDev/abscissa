#!/usr/bin/env python3
"""Linear MCP server — full Linear API: teams, projects, users, issues.

All tools run through one stdio MCP server. Set LINEAR_API_KEY before starting.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

API_URL = "https://api.linear.app/graphql"
MAX_PAGE_SIZE = 50

mcp = FastMCP("abscissa")


def _api_key() -> str:
    key = os.getenv("LINEAR_API_KEY", "").strip()
    if not key:
        raise RuntimeError("LINEAR_API_KEY env var is not set.")
    return key


def _gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": _api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Linear API HTTP {exc.code}: {body[:500]}") from exc
    if "errors" in data:
        messages = [e.get("message", str(e)) for e in data["errors"]]
        raise RuntimeError("Linear API errors: " + "; ".join(messages))
    return data.get("data", {})


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _page(connection: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a Linear connection into a stable cursor-paginated response."""
    connection = connection or {}
    page_info = connection.get("pageInfo") or {}
    return {
        "items": connection.get("nodes") or [],
        "next_cursor": page_info.get("endCursor") if page_info.get("hasNextPage") else None,
    }


def _page_size(limit: int) -> int:
    return min(max(limit, 1), MAX_PAGE_SIZE)


def _resolve_team_id(identifier: str) -> str:
    """Resolve a team key (e.g. ART) or UUID to a UUID."""
    data = _gql(
        "query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes { id } } }",
        {"key": identifier},
    )
    nodes = (data.get("teams") or {}).get("nodes") or []
    if nodes:
        return nodes[0]["id"]
    return identifier


def _resolve_state_id(team_id: str, state_name: str) -> str | None:
    """Resolve a state name to its UUID for a given team."""
    data = _gql(
        "query($teamId: String!) { team(id: $teamId) { states { nodes { id name } } } }",
        {"teamId": team_id},
    )
    states = (data.get("team") or {}).get("states", {}).get("nodes") or []
    for state in states:
        if state["name"].lower() == state_name.lower():
            return state["id"]
    return None


# ── Issue tools ────────────────────────────────────────────────────────────


@mcp.tool()
def get_current_user() -> str:
    """Return the authenticated Linear user behind the configured API key."""
    data = _gql("{ viewer { id name email } }")
    return _j(data.get("viewer"))


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def create_issue(
    title: str,
    team_id: str,
    description: str = "",
    priority: int = 0,
    state: str = "",
) -> str:
    """Create a new Linear issue.

    team_id accepts a team UUID or key (for example, ART). Priority is 0=none,
    1=urgent, 2=high, 3=normal, or 4=low.
    """
    team_uuid = _resolve_team_id(team_id)
    state_id = None
    if state:
        state_id = _resolve_state_id(team_uuid, state)
        if not state_id:
            return _j({"error": f"State '{state}' not found for team {team_id}"})

    inp: dict[str, Any] = {"teamId": team_uuid, "title": title}
    if description:
        inp["description"] = description
    if priority:
        inp["priority"] = priority
    if state_id:
        inp["stateId"] = state_id
    data = _gql(
        "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier title url priority state { name } team { key } } } }",
        {"input": inp},
    )
    issue = (data.get("issueCreate") or {}).get("issue")
    return _j(issue or {"error": "Failed to create issue"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def update_issue(
    issue_id: str,
    title: str = "",
    description: str = "",
    priority: int = -1,
    state: str = "",
    assignee_id: str = "",
) -> str:
    """Update an existing Linear issue. Use a UUID or identifier such as ART-5."""
    inp: dict[str, Any] = {}
    if title:
        inp["title"] = title
    if description:
        inp["description"] = description
    if priority >= 0:
        inp["priority"] = priority
    if assignee_id:
        inp["assigneeId"] = assignee_id
    if state:
        issue_data = _gql(
            "query($id: String!) { issue(id: $id) { team { id } } }",
            {"id": issue_id},
        )
        team_id = (issue_data.get("issue") or {}).get("team", {}).get("id")
        if team_id:
            state_id = _resolve_state_id(team_id, state)
            if state_id:
                inp["stateId"] = state_id
            else:
                return _j({"error": f"State '{state}' not found"})
    if not inp:
        return _j({"error": "No fields to update"})
    data = _gql(
        "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id identifier title priority state { name } assignee { id name } } } }",
        {"id": issue_id, "input": inp},
    )
    issue = (data.get("issueUpdate") or {}).get("issue")
    return _j(issue or {"error": "Failed to update issue"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def set_issue_project(issue_id: str, project_id: str) -> str:
    """Add an issue to a Linear project.

    Args:
        issue_id: Issue UUID or identifier such as ABS-1.
        project_id: Project UUID.
    """
    data = _gql(
        "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id identifier title project { id name } } } }",
        {"id": issue_id, "input": {"projectId": project_id}},
    )
    issue = (data.get("issueUpdate") or {}).get("issue")
    return _j(issue or {"error": "Failed to add issue to project"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def remove_issue_from_project(issue_id: str) -> str:
    """Remove an issue from its current Linear project."""
    data = _gql(
        "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id identifier title project { id name } } } }",
        {"id": issue_id, "input": {"projectId": None}},
    )
    issue = (data.get("issueUpdate") or {}).get("issue")
    return _j(issue or {"error": "Failed to remove issue from project"})


@mcp.tool()
def search_issues(
    query: str = "",
    team_id: str = "",
    state: str = "",
    assignee_id: str = "",
    priority: int = -1,
    limit: int = 10,
    cursor: str = "",
) -> str:
    """Search Linear issues with filters. Pass next_cursor as cursor for the next page."""
    filter_parts: dict[str, Any] = {}
    if query:
        filter_parts["title"] = {"containsIgnoreCase": query}
    if team_id:
        filter_parts["team"] = {"id": {"eq": _resolve_team_id(team_id)}}
    if state:
        filter_parts["state"] = {"name": {"eqIgnoreCase": state}}
    if assignee_id:
        filter_parts["assignee"] = {"id": {"eq": assignee_id}}
    if priority >= 0:
        filter_parts["priority"] = {"eq": priority}
    data = _gql(
        "query($filter: IssueFilter, $first: Int!, $after: String) { issues(filter: $filter, first: $first, after: $after) { nodes { id identifier title priority state { name } team { key } assignee { name } url } pageInfo { hasNextPage endCursor } } }",
        {"filter": filter_parts if filter_parts else None, "first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page(data.get("issues")))


@mcp.tool()
def get_user_issues(user_id: str = "", limit: int = 50, cursor: str = "") -> str:
    """Get a user's assigned issues; omit user_id to retrieve the authenticated user's issues."""
    target_user_id = user_id
    if not target_user_id:
        viewer = _gql("{ viewer { id } }").get("viewer") or {}
        target_user_id = viewer.get("id", "")
        if not target_user_id:
            return _j({"error": "Unable to resolve the authenticated Linear user"})
    data = _gql(
        "query($filter: IssueFilter, $first: Int!, $after: String) { issues(filter: $filter, first: $first, after: $after) { nodes { id identifier title priority state { name } team { key } url } pageInfo { hasNextPage endCursor } } }",
        {
            "filter": {"assignee": {"id": {"eq": target_user_id}}},
            "first": _page_size(limit),
            "after": cursor or None,
        },
    )
    return _j(_page(data.get("issues")))


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def add_comment(issue_id: str, body: str) -> str:
    """Add a markdown comment to a Linear issue."""
    data = _gql(
        "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success comment { id body url } } }",
        {"input": {"issueId": issue_id, "body": body}},
    )
    comment = (data.get("commentCreate") or {}).get("comment")
    return _j(comment or {"error": "Failed to add comment"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def assign_issue(issue_id: str, user_id: str) -> str:
    """Assign a user to an issue."""
    data = _gql(
        "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id identifier title assignee { id name } } } }",
        {"id": issue_id, "input": {"assigneeId": user_id}},
    )
    issue = (data.get("issueUpdate") or {}).get("issue")
    return _j(issue or {"error": "Failed to assign issue"})


@mcp.tool()
def get_issue(issue_id: str) -> str:
    """Get full issue details, including comments, labels, assignee, and dates."""
    data = _gql(
        """query($id: String!) { issue(id: $id) {
            id identifier title description priority url
            state { id name type }
            team { id key name }
            assignee { id name email }
            labels { nodes { id name color } }
            createdAt updatedAt
            parent { id identifier title }
            comments { nodes { id body createdAt user { id name } } }
        } }""",
        {"id": issue_id},
    )
    return _j(data.get("issue"))


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True))
def delete_issue(issue_id: str, confirm: bool = False) -> str:
    """Delete an issue permanently. Set confirm=true only after explicit user confirmation."""
    if not confirm:
        return _j({"error": "Deletion requires explicit confirmation: set confirm=true"})
    data = _gql(
        "mutation($id: String!) { issueDelete(id: $id) { success } }",
        {"id": issue_id},
    )
    return _j(data.get("issueDelete") or {"error": "Failed to delete issue"})


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True))
def archive_issue(issue_id: str, confirm: bool = False) -> str:
    """Archive an issue. Set confirm=true only after explicit user confirmation."""
    if not confirm:
        return _j({"error": "Archiving requires explicit confirmation: set confirm=true"})
    issue_data = _gql(
        "query($id: String!) { issue(id: $id) { team { id } } }",
        {"id": issue_id},
    )
    team_id = (issue_data.get("issue") or {}).get("team", {}).get("id")
    if not team_id:
        return _j({"error": "Cannot determine team for issue"})
    state_id = _resolve_state_id(team_id, "Canceled")
    if not state_id:
        state_id = _resolve_state_id(team_id, "Cancelled")
    if not state_id:
        return _j({"error": "Canceled/Cancelled state not found for team"})
    data = _gql(
        "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id identifier title state { name } } } }",
        {"id": issue_id, "input": {"stateId": state_id}},
    )
    issue = (data.get("issueUpdate") or {}).get("issue")
    return _j(issue or {"error": "Failed to archive issue"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def add_issue_label(issue_id: str, label_id: str) -> str:
    """Add a label to an issue."""
    data = _gql(
        "mutation($issueId: String!, $labelId: String!) { issueAddLabel(id: $issueId, labelId: $labelId) { success } }",
        {"issueId": issue_id, "labelId": label_id},
    )
    return _j(data.get("issueAddLabel") or {"error": "Failed to add label"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def remove_issue_label(issue_id: str, label_id: str) -> str:
    """Remove a label from an issue."""
    data = _gql(
        "mutation($issueId: String!, $labelId: String!) { issueRemoveLabel(id: $issueId, labelId: $labelId) { success } }",
        {"issueId": issue_id, "labelId": label_id},
    )
    return _j(data.get("issueRemoveLabel") or {"error": "Failed to remove label"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def set_issue_estimate(issue_id: str, estimate: float) -> str:
    """Set story points or an hour estimate on an issue."""
    data = _gql(
        "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { id identifier title estimate } } }",
        {"id": issue_id, "input": {"estimate": estimate}},
    )
    issue = (data.get("issueUpdate") or {}).get("issue")
    return _j(issue or {"error": "Failed to set estimate"})


@mcp.tool()
def list_issue_dependencies(
    issue_id: str,
    limit: int = 50,
    blocks_cursor: str = "",
    blocked_by_cursor: str = "",
) -> str:
    """List issues this issue blocks and issues that block it.

    The returned relation IDs can be passed to remove_issue_dependency. Use the
    matching cursor from next_cursors to retrieve another page for either side.
    """
    data = _gql(
        """query($id: String!, $first: Int!, $blocksAfter: String, $blockedByAfter: String) {
            issue(id: $id) {
                relations(first: $first, after: $blocksAfter) {
                    nodes { id type relatedIssue { id identifier title url state { name } } }
                    pageInfo { hasNextPage endCursor }
                }
                inverseRelations(first: $first, after: $blockedByAfter) {
                    nodes { id type issue { id identifier title url state { name } } }
                    pageInfo { hasNextPage endCursor }
                }
            }
        }""",
        {
            "id": issue_id,
            "first": _page_size(limit),
            "blocksAfter": blocks_cursor or None,
            "blockedByAfter": blocked_by_cursor or None,
        },
    )
    issue = data.get("issue") or {}
    outgoing = issue.get("relations") or {}
    incoming = issue.get("inverseRelations") or {}
    return _j(
        {
            "blocks": [
                {"relation_id": relation["id"], "issue": relation.get("relatedIssue")}
                for relation in outgoing.get("nodes") or []
                if relation.get("type") == "blocks"
            ],
            "blocked_by": [
                {"relation_id": relation["id"], "issue": relation.get("issue")}
                for relation in incoming.get("nodes") or []
                if relation.get("type") == "blocks"
            ],
            "next_cursors": {
                "blocks": _page(outgoing)["next_cursor"],
                "blocked_by": _page(incoming)["next_cursor"],
            },
        }
    )


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def add_issue_dependency(blocker_issue_id: str, blocked_issue_id: str) -> str:
    """Record that blocker_issue_id blocks blocked_issue_id in Linear."""
    data = _gql(
        "mutation($input: IssueRelationCreateInput!) { issueRelationCreate(input: $input) { success issueRelation { id type issue { id identifier } relatedIssue { id identifier } } } }",
        {
            "input": {
                "issueId": blocker_issue_id,
                "relatedIssueId": blocked_issue_id,
                "type": "blocks",
            }
        },
    )
    relation = (data.get("issueRelationCreate") or {}).get("issueRelation")
    return _j(relation or {"error": "Failed to add issue dependency"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def remove_issue_dependency(relation_id: str) -> str:
    """Remove an issue dependency by its relation ID."""
    data = _gql(
        "mutation($id: String!) { issueRelationDelete(id: $id) { success } }",
        {"id": relation_id},
    )
    return _j(data.get("issueRelationDelete") or {"error": "Failed to remove issue dependency"})


@mcp.tool()
def list_workflow_states(team_id: str, limit: int = 50, cursor: str = "") -> str:
    """List workflow states for a team. Pass next_cursor as cursor for the next page."""
    team_uuid = _resolve_team_id(team_id)
    data = _gql(
        "query($id: String!, $first: Int!, $after: String) { team(id: $id) { states(first: $first, after: $after) { nodes { id name type color position } pageInfo { hasNextPage endCursor } } } }",
        {"id": team_uuid, "first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page((data.get("team") or {}).get("states")))


@mcp.tool()
def list_issue_labels(team_id: str, limit: int = 50, cursor: str = "") -> str:
    """List labels for a team. Pass next_cursor as cursor for the next page."""
    team_uuid = _resolve_team_id(team_id)
    data = _gql(
        "query($teamId: ID!, $first: Int!, $after: String) { issueLabels(filter: { team: { id: { eq: $teamId } } }, first: $first, after: $after) { nodes { id name color } pageInfo { hasNextPage endCursor } } }",
        {"teamId": team_uuid, "first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page(data.get("issueLabels")))


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def create_label(team_id: str, name: str, color: str = "") -> str:
    """Create a label for a team."""
    team_uuid = _resolve_team_id(team_id)
    inp: dict[str, Any] = {"name": name, "teamId": team_uuid}
    if color:
        inp["color"] = color
    data = _gql(
        "mutation($input: IssueLabelCreateInput!) { issueLabelCreate(input: $input) { success issueLabel { id name color } } }",
        {"input": inp},
    )
    label = (data.get("issueLabelCreate") or {}).get("issueLabel")
    return _j(label or {"error": "Failed to create label"})


# ── Team / Project / User tools ────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def create_cycle(
    team_id: str,
    name: str,
    starts_at: str,
    ends_at: str,
    description: str = "",
) -> str:
    """Create a Linear cycle for a team.

    starts_at and ends_at must be ISO 8601 timestamps, for example
    2026-07-13T09:00:00Z. team_id accepts a team UUID or key.
    """
    inp: dict[str, Any] = {
        "teamId": _resolve_team_id(team_id),
        "name": name,
        "startsAt": starts_at,
        "endsAt": ends_at,
    }
    if description:
        inp["description"] = description
    data = _gql(
        "mutation($input: CycleCreateInput!) { cycleCreate(input: $input) { success cycle { id number name description startsAt endsAt team { id key } } } }",
        {"input": inp},
    )
    cycle = (data.get("cycleCreate") or {}).get("cycle")
    return _j(cycle or {"error": "Failed to create cycle"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def update_cycle(
    cycle_id: str,
    name: str = "",
    description: str = "",
    starts_at: str = "",
    ends_at: str = "",
) -> str:
    """Update a cycle's name, description, or ISO 8601 start and end timestamps."""
    inp: dict[str, Any] = {}
    if name:
        inp["name"] = name
    if description:
        inp["description"] = description
    if starts_at:
        inp["startsAt"] = starts_at
    if ends_at:
        inp["endsAt"] = ends_at
    if not inp:
        return _j({"error": "No fields to update"})
    data = _gql(
        "mutation($id: String!, $input: CycleUpdateInput!) { cycleUpdate(id: $id, input: $input) { success cycle { id number name description startsAt endsAt } } }",
        {"id": cycle_id, "input": inp},
    )
    cycle = (data.get("cycleUpdate") or {}).get("cycle")
    return _j(cycle or {"error": "Failed to update cycle"})


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True))
def archive_cycle(cycle_id: str, confirm: bool = False) -> str:
    """Archive a cycle. Set confirm=true only after explicit user confirmation."""
    if not confirm:
        return _j({"error": "Archiving requires explicit confirmation: set confirm=true"})
    data = _gql(
        "mutation($id: String!) { cycleArchive(id: $id) { success } }",
        {"id": cycle_id},
    )
    return _j(data.get("cycleArchive") or {"error": "Failed to archive cycle"})


@mcp.tool()
def list_cycles(team_id: str = "", limit: int = 50, cursor: str = "") -> str:
    """List workspace cycles, optionally filtered by a team key or UUID."""
    cycle_filter: dict[str, Any] = {}
    if team_id:
        cycle_filter["team"] = {"id": {"eq": _resolve_team_id(team_id)}}
    data = _gql(
        """query($filter: CycleFilter, $first: Int!, $after: String) {
            cycles(filter: $filter, first: $first, after: $after) {
                nodes { id number name description startsAt endsAt completedAt isActive isFuture isPast team { id key name } }
                pageInfo { hasNextPage endCursor }
            }
        }""",
        {"filter": cycle_filter or None, "first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page(data.get("cycles")))


@mcp.tool()
def list_cycle_issues(cycle_id: str, limit: int = 50, cursor: str = "") -> str:
    """List issues in a cycle. Pass next_cursor as cursor for the next page."""
    data = _gql(
        """query($id: String!, $first: Int!, $after: String) {
            cycle(id: $id) {
                issues(first: $first, after: $after) {
                    nodes { id identifier title priority state { name } assignee { id name } project { id name } url }
                    pageInfo { hasNextPage endCursor }
                }
            }
        }""",
        {"id": cycle_id, "first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page((data.get("cycle") or {}).get("issues")))


@mcp.tool()
def list_teams(limit: int = 50, cursor: str = "") -> str:
    """List teams. Pass next_cursor as cursor for the next page."""
    data = _gql(
        "query($first: Int!, $after: String) { teams(first: $first, after: $after) { nodes { id name key } pageInfo { hasNextPage endCursor } } }",
        {"first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page(data.get("teams")))


@mcp.tool()
def list_projects(limit: int = 50, cursor: str = "") -> str:
    """List projects. Pass next_cursor as cursor for the next page."""
    data = _gql(
        "query($first: Int!, $after: String) { projects(first: $first, after: $after) { nodes { id name teams { nodes { id key } } state } pageInfo { hasNextPage endCursor } } }",
        {"first": _page_size(limit), "after": cursor or None},
    )
    connection = data.get("projects") or {}
    nodes = connection.get("nodes") or []
    out = []
    for project in nodes:
        teams = [team.get("key") for team in (project.get("teams") or {}).get("nodes") or []]
        out.append({"id": project["id"], "name": project["name"], "teams": teams, "state": project.get("state")})
    return _j({**_page(connection), "items": out})


@mcp.tool()
def get_team(identifier: str) -> str:
    """Get a team by key (for example, ART) or UUID."""
    data = _gql(
        "query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes { id name key description } } }",
        {"key": identifier},
    )
    nodes = (data.get("teams") or {}).get("nodes") or []
    if nodes:
        return _j(nodes[0])
    try:
        data = _gql(
            "query($id: String!) { team(id: $id) { id name key description } }",
            {"id": identifier},
        )
    except RuntimeError:
        return _j({"error": f"Team not found: {identifier}"})
    return _j(data.get("team") or {"error": f"Team not found: {identifier}"})


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def create_project(name: str, team_ids: str = "", description: str = "") -> str:
    """Create a project; team_ids may be comma-separated team keys or UUIDs."""
    inp: dict[str, Any] = {"name": name}
    if team_ids:
        resolved = [_resolve_team_id(team.strip()) for team in team_ids.split(",") if team.strip()]
        if resolved:
            inp["teamIds"] = resolved
    if description:
        inp["description"] = description
    data = _gql(
        "mutation($input: ProjectCreateInput!) { projectCreate(input: $input) { success project { id name url teams { nodes { key } } } } }",
        {"input": inp},
    )
    project = (data.get("projectCreate") or {}).get("project")
    return _j(project or {"error": "Failed to create project"})


@mcp.tool()
def get_project(project_id: str) -> str:
    """Get a project by UUID."""
    data = _gql(
        "query($id: String!) { project(id: $id) { id name description state teams { nodes { id key name } } } }",
        {"id": project_id},
    )
    return _j(data.get("project"))


@mcp.tool()
def list_project_issues(project_id: str, limit: int = 50, cursor: str = "") -> str:
    """List a project's issues. Pass next_cursor as cursor for the next page."""
    data = _gql(
        """query($projectId: ID!, $first: Int!, $after: String) { issues(filter: { project: { id: { eq: $projectId } } }, first: $first, after: $after) {
            nodes { id identifier title priority state { name } assignee { id name } labels { nodes { id name } } url } pageInfo { hasNextPage endCursor }
        } }""",
        {"projectId": project_id, "first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page(data.get("issues")))


@mcp.tool()
def list_users(limit: int = 50, cursor: str = "") -> str:
    """List organization users. Pass next_cursor as cursor for the next page."""
    data = _gql(
        "query($first: Int!, $after: String) { users(first: $first, after: $after) { nodes { id name email } pageInfo { hasNextPage endCursor } } }",
        {"first": _page_size(limit), "after": cursor or None},
    )
    return _j(_page(data.get("users")))


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True))
def update_project(project_id: str, name: str = "", description: str = "", state: str = "") -> str:
    """Update a project. State may be planned, started, paused, completed, or canceled."""
    inp: dict[str, Any] = {}
    if name:
        inp["name"] = name
    if description:
        inp["description"] = description
    if state:
        inp["state"] = state
    if not inp:
        return _j({"error": "No fields to update"})
    data = _gql(
        "mutation($id: String!, $input: ProjectUpdateInput!) { projectUpdate(id: $id, input: $input) { success project { id name description state } } }",
        {"id": project_id, "input": inp},
    )
    project = (data.get("projectUpdate") or {}).get("project")
    return _j(project or {"error": "Failed to update project"})


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True))
def archive_project(project_id: str, confirm: bool = False) -> str:
    """Archive a project. Set confirm=true only after explicit user confirmation."""
    if not confirm:
        return _j({"error": "Archiving requires explicit confirmation: set confirm=true"})
    data = _gql(
        "mutation($id: String!, $input: ProjectUpdateInput!) { projectUpdate(id: $id, input: $input) { success project { id name state } } }",
        {"id": project_id, "input": {"state": "canceled"}},
    )
    project = (data.get("projectUpdate") or {}).get("project")
    return _j(project or {"error": "Failed to archive project"})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
