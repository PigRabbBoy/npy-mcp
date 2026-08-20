# Release — Full Reference

## Version rules (Semantic Versioning)

| Bump type | When to use | Example |
|---|---|---|
| **Patch** (0.2.0 → 0.2.1) | Bug fixes, docs, internal refactors — no new features | `fix:`, `docs:`, `chore:` |
| **Minor** (0.2.0 → 0.3.0) | New features, new tools, new commands — backward compatible | `feat:` |
| **Major** (0.2.0 → 1.0.0) | Breaking changes — API changes, removed tools, config format change | `BREAKING CHANGE`, `feat!:` |

### Version strings

Format: `MAJOR.MINOR.PATCH` (e.g. `0.2.1`)

- Git tag: `v0.2.1` (with `v` prefix)
- pyproject.toml: `0.2.1` (no `v` prefix)
- Docker tag: `0.2.1` (no `v` prefix)

## Files to bump

Always update ALL of these to the same version:

| File | Field |
|---|---|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `packages/npy-core/pyproject.toml` | `version = "X.Y.Z"` |
| `packages/npy-cli/pyproject.toml` | `version = "X.Y.Z"` |
| `packages/npy-mcp/pyproject.toml` | `version = "X.Y.Z"` |

## CHANGELOG.md format

Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/):

```markdown
# Changelog

All notable changes to npy-mcp are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-08-20

### Added
- New feature or tool

### Changed
- Something modified

### Fixed
- Bug fix

### Removed
- Something deleted

## [0.2.0] - 2026-08-20

### Added
- Initial monorepo structure
```

### Categories

| Category | Use for |
|---|---|
| `### Added` | New features, tools, commands, files |
| `### Changed` | Changes to existing functionality |
| `### Fixed` | Bug fixes |
| `### Removed` | Removed features/files |
| `### Security` | Security-related fixes (rare) |

### Generating changelog entries from commits

```bash
# List commits since last tag with full messages
git log --oneline $(git describe --tags --abbrev=0)..HEAD

# List only conventional commit types
git log --format='%s' $(git describe --tags --abbrev=0)..HEAD | grep -E '^[a-z]+:'
```

Map commit prefixes to changelog categories:

| Commit prefix | Changelog category |
|---|---|
| `feat:` | Added |
| `fix:` | Fixed |
| `docs:` | Changed (or skip if trivial) |
| `chore:` | Changed (or skip if trivial) |
| `refactor:` | Changed |
| `test:` | skip (internal) |
| `ci:` | skip (internal) |
| `BREAKING CHANGE` | Removed / Changed |

## gh release commands

### Create release from changelog file

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes-file CHANGELOG.md \
  -R PigRabbBoy/npy-mcp
```

Note: `--notes-file CHANGELOG.md` uses the full file. To use only the relevant
section, extract it first:

```bash
# Extract the X.Y.Z section from CHANGELOG.md
awk '/^## \[0\.2\.1\]/{found=1} /^## \[0\.2\.0\]/{exit} found' CHANGELOG.md > /tmp/release-notes.md
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file /tmp/release-notes.md -R PigRabbBoy/npy-mcp
```

### Create release with auto-generated notes

```bash
gh release create vX.Y.Z --generate-notes -R PigRabbBoy/npy-mcp
```

### List releases

```bash
gh release list -R PigRabbBoy/npy-mcp
```

### View a release

```bash
gh release view vX.Y.Z -R PigRabbBoy/npy-mcp
```

## Docker release

### Build + tag + push

```bash
cd packages/npy-mcp

# Build with version + latest tags
docker build -t pigrabbboy/npy-mcp:X.Y.Z -t pigrabbboy/npy-mcp:latest .

# Push both tags
docker push pigrabbboy/npy-mcp:X.Y.Z
docker push pigrabbboy/npy-mcp:latest
```

### Sync README to Docker Hub

```bash
# Login to Docker Hub API
TOKEN=$(curl -s -X POST https://hub.docker.com/v2/users/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"pigrabbboy","password":"YOUR_DOCKER_PAT"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Update repo description (full README as full_description)
curl -s -X PATCH https://hub.docker.com/v2/repositories/pigrabbboy/npy-mcp/ \
  -H "Authorization: JWT $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"full_description\": $(python3 -c 'import json; print(json.dumps(open("README.md").read()))')}"
```

## Rollback

If a release goes wrong, rollback in reverse order:

### 1. Delete GitHub Release

```bash
gh release delete vX.Y.Z -R PigRabbBoy/npy-mcp --yes
```

### 2. Delete git tag (local + remote)

```bash
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
```

### 3. Revert the release commit

```bash
git revert HEAD --no-edit
git push origin master
```

### 4. Restore previous version in pyproject.toml files

Manually revert the 4 `pyproject.toml` files to the previous version.

### 5. Docker (if pushed)

Docker Hub doesn't allow deleting tags via CLI easily. Delete via web UI at
https://hub.docker.com/repository/docker/pigrabbboy/npy-mcp/tags

## Quick reference: one-shot release

For a confirmed release (all checks pass, user approved):

```bash
# 1. Bump version in 4 pyproject.toml files
# 2. Update CHANGELOG.md
# 3. Commit + tag + push
git add -A && git commit -m "release: vX.Y.Z" && git tag vX.Y.Z && git push origin master --tags
# 4. GitHub Release
gh release create vX.Y.Z --generate-notes -R PigRabbBoy/npy-mcp
# 5. Docker (optional)
cd packages/npy-mcp && docker build -t pigrabbboy/npy-mcp:X.Y.Z -t pigrabbboy/npy-mcp:latest . && docker push pigrabbboy/npy-mcp:X.Y.Z && docker push pigrabbboy/npy-mcp:latest
```