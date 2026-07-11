<p align="center">
  <img src="https://raw.githubusercontent.com/KazKozDev/abscissa/main/docs/assets/banner.png" alt="Abscissa" width="350">
</p>

<!-- mcp-name: io.github.KazKozDev/abscissa -->

Abscissa is a Python stdio MCP server for [Linear](https://linear.app/). It turns Linear's GraphQL
API into 35 tools for an MCP client: issues, projects, cycles, dependencies,
comments, labels, workflow states, teams, and users.

The design priority is deliberate control over project data. Read operations
return cursor-paginated results; `get_user_issues()` resolves the authenticated
Linear user; archive and delete tools require an explicit `confirm=true` before
they make a destructive API call. The server stores no credentials and reads
`LINEAR_API_KEY` from its process environment.

Abscissa uses the stdio transport from the
[Model Context Protocol](https://modelcontextprotocol.io/). Any client that
supports stdio MCP can launch it as a local tool process.

## Run it

You need Python 3.10+ and a [Linear personal API key](https://linear.app/settings/api).

```sh
git clone https://github.com/KazKozDev/abscissa.git
cd abscissa
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export LINEAR_API_KEY='lin_api_…'
.venv/bin/abscissa
```

You can also install Abscissa directly from PyPI:

```sh
pip install abscissa
```

The final command starts the MCP server on standard input and output. Register
`.venv/bin/abscissa` as a stdio command in your MCP client, and pass
`LINEAR_API_KEY` through that client's environment or secret manager.

The key remains outside the repository. The `.gitignore` excludes common local
environment files, including `.env` and `.venv`.

## Example prompts

Once Abscissa is registered in your MCP client, try prompts like:

```text
Show my open Linear issues grouped by project.
Create an issue in ENG for fixing onboarding copy.
List issues blocked by GEN-32.
```

## Tools

| Area | Tools |
| --- | --- |
| Identity | `get_current_user` |
| Issues | `create_issue`, `update_issue`, `search_issues`, `get_user_issues`, `get_issue`, `assign_issue`, `add_comment`, `set_issue_estimate` |
| Issue lifecycle | `archive_issue`, `delete_issue` |
| Dependencies | `list_issue_dependencies`, `add_issue_dependency`, `remove_issue_dependency` |
| Labels and workflow | `list_workflow_states`, `list_issue_labels`, `create_label`, `add_issue_label`, `remove_issue_label` |
| Teams and people | `list_teams`, `get_team`, `list_users` |
| Projects | `create_project`, `get_project`, `list_projects`, `list_project_issues`, `set_issue_project`, `remove_issue_from_project`, `update_project`, `archive_project` |
| Cycles | `create_cycle`, `update_cycle`, `archive_cycle`, `list_cycles`, `list_cycle_issues` |

Search and list tools accept `limit` and `cursor`. Their responses keep the same
shape:

```json
{
  "items": [],
  "next_cursor": null
}
```

Pass a non-null `next_cursor` back as `cursor` to request the next page.

`list_issue_dependencies` returns separate `blocks` and `blocked_by` lists.
Each item includes its `relation_id`; use it to remove that dependency. Its
`next_cursors` object has separate cursors for each direction.

## Destructive actions

`archive_issue`, `archive_project`, and `delete_issue` are marked with MCP's
`destructiveHint`. They refuse to call Linear until the client invokes them
with `confirm=true`.

```text
Deletion requires explicit confirmation: set confirm=true
```

This prevents an accidental tool call from deleting or archiving data. It does
not replace Linear's own access controls: the API key still determines which
resources the server may read or change.

## Verify the checkout

```sh
.venv/bin/ruff check .
.venv/bin/python -m pytest
```

The current checkout produces:

```text
All checks passed!
..........                                                               [100%]
10 passed
```

The tests cover pagination bounds and response shape, authenticated-user issue
resolution, project membership, cycle queries, dependency direction, confirmation
guards, cycle lifecycle operations, and MCP tool registration. GitHub Actions
runs the same lint and test commands on Python 3.10, 3.11, 3.12, and 3.13.

## Limitations

Abscissa is a local stdio server, not an HTTP service. It needs a running
MCP-capable client and a valid Linear API key. The automated suite avoids
mutating a real Linear workspace; create, update, archive, and delete behavior
is therefore protected by unit tests rather than a live write test.

## License

[MIT](LICENSE)
