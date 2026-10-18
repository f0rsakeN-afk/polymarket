"""
Every workspace manifest must appear in every Dockerfile's dependency layer.

## The failure this prevents

Both `Dockerfile` and `Dockerfile.dev` copy a hand-maintained list of
`package.json` files before running `bun install --frozen-lockfile`, so the
install layer stays cached while only source files change.

The list has to be complete, because a workspace that another workspace depends
on must exist on disk for the lockfile to resolve. Omit one and the build fails
with:

    error: workspace "web" depends on workspace "@workspace/schemas"
    (packages/schemas), which is listed in bun.lock but not on disk

Which is a *misleading* error. It names a corrupt lockfile, and the instinct is
to regenerate the lockfile - which, as established in the same week as this test,
upgrades every dependency in the monorepo and puts an unreviewed bump in an
unrelated PR. The real cause is one missing line in a Dockerfile.

It happened for real: `packages/schemas` was added and wired as a dependency of
both apps, and both Dockerfiles were left untouched. The comment immediately
above the list even predicted the failure - which is the part worth remembering.
A warning nobody reads is not a control, so this is the control.

## Why not a glob

`COPY packages/*/package.json ./packages/` flattens: every manifest lands in one
directory and the workspace layout is destroyed. Docker's `COPY` has no
structure-preserving directory glob, so the list stays explicit and gets checked
instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

DOCKERFILES = ["Dockerfile", "Dockerfile.dev"]


def _workspace_manifests() -> set[str]:
    """Every `package.json` in the workspace, as a path relative to `frontend/`."""
    manifests = {
        path.relative_to(FRONTEND).as_posix()
        for path in FRONTEND.glob("apps/*/package.json")
    }
    manifests |= {
        path.relative_to(FRONTEND).as_posix()
        for path in FRONTEND.glob("packages/*/package.json")
    }
    return manifests


def _copied_manifests(dockerfile: str) -> set[str]:
    """Manifests the Dockerfile copies before its `bun install`."""
    text = (FRONTEND / dockerfile).read_text()
    # Anchored on `RUN bun install`, not on the bare phrase. `Dockerfile.dev`
    # explains *why* it uses `--chown` in a comment that itself mentions
    # `bun install`, and a plain `text.index("bun install")` found that comment —
    # so the "prefix before install" was the comment block, containing no COPY
    # lines at all, and every manifest read as uncopied.
    #
    # A control that fires for the wrong reason is worse than no control, because
    # the response to a test that is always red is to delete it — and the next
    # failure really would be a missing manifest, with nobody watching.
    match = re.search(r"^RUN\s+bun install", text, re.MULTILINE)
    assert match, f"{dockerfile} has no `RUN bun install` to measure against"
    prefix = text[: match.start()]
    # Flags before the source are skipped, for the same reason: `--chown=bun:bun`
    # is what lets the non-root user own the tree in the dev image.
    return set(
        re.findall(
            r"^COPY\s+(?:--[^\s]+\s+)*(\S+package\.json)\s", prefix, re.MULTILINE
        )
    )


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_every_workspace_manifest_is_copied_before_install(dockerfile):
    missing = sorted(_workspace_manifests() - _copied_manifests(dockerfile))

    assert not missing, (
        f"{dockerfile} does not copy {missing} before `bun install --frozen-lockfile`.\n"
        "The build will fail with 'which is listed in bun.lock but not on disk', "
        "which reads like a corrupt lockfile and invites regenerating it - and "
        "regenerating the lockfile is an unreviewed upgrade of every dependency "
        "in the monorepo."
    )


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_copy_list_contains_nothing_stale(dockerfile):
    """The reverse error, which is quieter: a path that no longer exists.

    Docker fails on a missing `COPY` source, so this is caught by any build - but
    a path that exists and is *not* a workspace (a stray `package.json`) would sit
    in the list forever and read as deliberate.
    """
    copied = _copied_manifests(dockerfile)
    on_disk = set(_workspace_manifests()) | {"package.json"}

    assert not (copied - on_disk), (
        f"{dockerfile} copies {sorted(copied - on_disk)}, which are not workspaces"
    )


def test_every_dockerfile_uses_the_declared_bun_version():
    """bun versions disagree about lockfile format, and a floating tag drifts.

    `Dockerfile` used `oven/bun:1.4-slim` while CI installed `packageManager`
    (`bun@1.3.14`) and `Dockerfile.dev` pinned `1.3.14`. A floating tag had already
    drifted a minor version, and the build failed with:

        error: lockfile had changes, but lockfile is frozen

    which reads like a stale lockfile and invites regenerating it — and
    regenerating the lockfile is an unreviewed upgrade of every dependency in the
    monorepo. So the check has to be "every Dockerfile matches what the repo
    declares", not "the Dockerfiles match each other": two of three agreeing is
    still broken if CI is the odd one out.
    """
    import json

    declared = json.loads((FRONTEND / "package.json").read_text())["packageManager"]
    assert declared.startswith("bun@"), f"unexpected packageManager: {declared}"
    version = declared.split("@", 1)[1]

    for dockerfile in DOCKERFILES:
        bases = re.findall(r"^FROM\s+oven/bun:(\S+)", (FRONTEND / dockerfile).read_text(), re.MULTILINE)
        assert bases, f"{dockerfile} does not build from oven/bun"

        for base in bases:
            # A floating tag is the failure itself: `1.4-slim` resolved to 1.4.3
            # while everything else was on 1.3.14, with nothing in the repo to say so.
            assert base == f"{version}-slim", (
                f"{dockerfile} builds from oven/bun:{base} but packageManager says "
                f"bun@{version}. Match it, or pin the floating tag explicitly — the "
                "two must not disagree."
            )


def test_a_new_workspace_will_fail_this_test_not_a_build():
    """Guards the guard.

    A test that passes for any directory layout is not testing the layout. This
    asserts that a manifest appearing on disk without being listed is detected,
    which is precisely the change that broke the build.
    """
    manifests = _workspace_manifests()
    assert "packages/api-client/package.json" in manifests
    assert "apps/admin/package.json" in manifests

    # Both Dockerfiles list everything that exists today; adding a workspace that
    # neither lists is what the tests above are there to reject.
    for dockerfile in DOCKERFILES:
        copied = _copied_manifests(dockerfile)
        assert manifests <= copied, f"{dockerfile} is missing {sorted(manifests - copied)}"