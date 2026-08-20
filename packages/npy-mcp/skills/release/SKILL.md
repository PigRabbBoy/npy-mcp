---
name: release
description: >-
  Bump version, update changelog, tag, and create GitHub Release for npy-mcp.
  Use when the user says "release", "bump version", "cut a release", "tag a
  release", "publish a new version", or asks to create a GitHub release.
---

# Release

## Pre-release checklist

Before starting a release, verify ALL of these:

- [ ] All tests pass: `python -m pytest tests/ -v`
- [ ] No uncommitted changes: `git status --porcelain` returns empty
- [ ] On `master` branch: `git branch --show-current`
- [ ] `gh` authenticated: `gh auth status`
- [ ] Working tree is up to date: `git pull --ff-only origin master`

If any check fails, stop and fix it before proceeding.

## Release workflow

### Step 1 — Determine next version

Look at commits since the last tag:

```bash
git log --oneline $(git describe --tags --abbrev=0)..HEAD
```

Suggest a version based on [Conventional Commits](https://www.conventionalcommits.org/):

| Commit type | Version bump |
|---|---|
| `fix:` | patch (0.2.0 → 0.2.1) |
| `feat:` | minor (0.2.0 → 0.3.0) |
| `BREAKING CHANGE` or `!:` | major (0.2.0 → 1.0.0) |
| `docs:` / `chore:` / `test:` | no release needed (ask user) |

**Always ask the user to confirm** the version before proceeding. Don't auto-bump.

### Step 2 — Bump version in 4 files

Update `version = "X.Y.Z"` in all of these:

| File | Current |
|---|---|
| `pyproject.toml` | root |
| `packages/npy-core/pyproject.toml` | core lib |
| `packages/npy-cli/pyproject.toml` | CLI |
| `packages/npy-mcp/pyproject.toml` | MCP server |

All 4 must have the same version.

### Step 3 — Update CHANGELOG.md

1. Rename `[Unreleased]` section to `[X.Y.Z] - YYYY-MM-DD` (today's date).
2. Add a new empty `## [Unreleased]` section above it.
3. Categorize changes under `### Added`, `### Changed`, `### Fixed`, `### Removed`.
4. Source changes from git commits since last tag.

See [REFERENCE.md](./REFERENCE.md) for the full changelog format.

### Step 4 — Commit + tag

```bash
git add -A
git commit -m "release: vX.Y.Z"
git tag vX.Y.Z
```

### Step 5 — Push

```bash
git push origin master --tags
```

### Step 6 — GitHub Release

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file CHANGELOG.md -R PigRabbBoy/npy-mcp
```

Or auto-generate notes from commits:

```bash
gh release create vX.Y.Z --generate-notes -R PigRabbBoy/npy-mcp
```

### Step 7 — Docker (optional)

Ask the user if they want to publish a Docker image. If yes:

```bash
cd packages/npy-mcp
docker build -t pigrabbboy/npy-mcp:X.Y.Z -t pigrabbboy/npy-mcp:latest .
docker push pigrabbboy/npy-mcp:X.Y.Z
docker push pigrabbboy/npy-mcp:latest
```

Then sync README to Docker Hub (see [REFERENCE.md](./REFERENCE.md)).

## Confirmation gates

**STOP and ask the user before:**
- Step 4 (commit + tag) — show the version + changelog diff, get explicit "yes"
- Step 6 (GitHub Release) — show the release notes, get explicit "yes"
- Step 7 (Docker push) — ask if Docker is needed at all

Never auto-tag or auto-release without explicit user confirmation.

## Full reference

See [REFERENCE.md](./REFERENCE.md) for version rules, changelog format, gh/docker commands, and rollback procedures.