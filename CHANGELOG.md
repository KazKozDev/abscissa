# Changelog

All notable changes to Abscissa are documented in this file.

## [0.1.3] - 2026-07-11

### Added

- Project-detail updates for content, lead, members, priority, dates, teams,
  icon, and color.
- Project-label listing, creation, assignment, and removal tools.
- Project-update creation and cursor-paginated listing tools.

### Fixed

- Project status updates and project archiving now use Linear's current
  `statusId` API field.

## [0.1.2] - 2026-07-11

### Changed

- Add MCP Registry metadata and README ownership verification for the PyPI
  package.
- Add example prompts to make first-use workflows clearer.

## [0.1.1] - 2026-07-11

### Changed

- Add the README banner image and use an absolute raw GitHub URL so it renders
  on PyPI as well as GitHub.

## [0.1.0] - 2026-07-11

### Added

- 35 stdio MCP tools for Linear issues, projects, cycles, labels, teams, users,
  comments, and issue dependencies.
- Cursor pagination for search and list operations.
- Explicit confirmation and MCP destructive annotations for deletion and archive
  operations.
- Python package metadata, command-line entry point, automated tests, and CI.

### Verified

- Unit and MCP registration tests.
- Authenticated end-to-end reads against Linear.
- End-to-end creation, update, archive, and deletion paths on temporary Linear
  data.
