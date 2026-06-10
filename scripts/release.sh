#!/usr/bin/env bash
# Tags and creates a GitHub release matching the VERSION file.
# Triggers publish.yml, snap.yml, and mac-release.yml on the GitHub side.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VERSION=$(cat VERSION)
TAG="v$VERSION"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Error: working tree has uncommitted changes." >&2
    exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Error: tag $TAG already exists." >&2
    exit 1
fi

echo "Releasing $TAG"
git push
git tag -a "$TAG" -m "Release $TAG"
git push origin "$TAG"
gh release create "$TAG" --title "$TAG" --generate-notes
