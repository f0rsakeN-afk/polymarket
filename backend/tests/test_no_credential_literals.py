"""No credential literals anywhere in the repository.

A hardcoded password in a repository is not a secret that merely looks like one.
It is a credential in every clone, of every fork, and of every mirror - and it is
in the git history permanently, so deleting the line does not retract it. If it
also happens to be written in a README, then it is not merely leaked, it is
published, and there is no version of "rotate it later" that makes it useful as
a credential again.

That is not hypothetical for this repository. Two literals - one in the seeder,
one in the load-test file - were flagged by GitHub's secret scanning and then
carried in three READMEs and a demo script, which is the worst of both worlds:
the scanning tool noticed, and a human had already printed it.

Scanning for "does this look like a password" is hopeless in general, because the
word appears in variable names and in prose. What is reliable here is narrower
and still catches the real cases: assert that the *scripts and harness* - the
only places in this repository that legitimately create accounts - contain no
literal fallback for a credential. An override with no default is required, which
means the value has to come from the environment or be minted at runtime.

It also pins the documentation, since that is where the value actually escaped to.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# Scanned relative to each root: scripts and harness live under `backend`, the
# docs at the repo root. Globbing both from one place silently matches nothing,
# and a test over an empty set passes forever while checking nothing.
CODE_GLOBS_BACKEND = ("scripts/**/*.py", "harness/**/*.py")
DOC_GLOBS_REPO = ("*.md", "docs/**/*.md", "backend/*.md")

# `os.environ.get("X", "literal")` / `environ("X", "literal")` on a name that
# looks like a credential: a default secret, which is the exact shape we forbid.
# A bare `os.environ.get("X")` is fine - it simply has no default.
FALLBACK_SECRET = re.compile(
    r"""(?:os\.)?environ(?:\.get)?\(\s*["'][A-Z_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY)[A-Z_]*["']\s*,\s*["'][^"']+["']""",
    re.IGNORECASE,
)


def _files(base: Path, globs: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for pattern in globs:
        found.extend(p for p in base.glob(pattern) if p.is_file())
    return sorted(found)


def _scan(paths: list[Path], check_docs: bool) -> list[str]:
    """Report any hardcoded credential fallback, in code or in documentation."""
    assert paths, "no files matched - the glob is wrong, and this test would pass vacuously"
    problems: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if FALLBACK_SECRET.search(line):
                problems.append(f"{_rel(path)}:{lineno}: credential default in code")

            # Documentation must not hand a credential value to a reader.
            #
            # This is deliberately *contextual* - a line that talks about a
            # credential, quoting a literal that looks like one - rather than a
            # bare shape match on every backticked word. The shape-only version
            # flagged `verifyMagic2fa` in the API reference, because a camelCase
            # identifier with a digit in it is shaped like a password. A check
            # that cries wolf on function names gets deleted, and then it catches
            # nothing.
            if check_docs and _talks_about_a_credential(line):
                for literal in re.findall(r"`([^`\s]{8,})`", line):
                    if _looks_like_a_credential(literal):
                        problems.append(
                            f"{_rel(path)}:{lineno}: quotes a credential in docs"
                        )
    return problems


def _talks_about_a_credential(line: str) -> bool:
    """Is this line handing out a credential?

    Two signals, because neither alone is enough.

    The obvious one is the word: a line that mentions a password and quotes a
    value is handing one over. But a credentials *table* never says so on the row
    that does it - the header says "Password" and the rows are just
    `| email | secret | role |`. Checking for the word missed exactly the case
    that mattered here, because the three READMEs were all tables.

    So the second signal is structural: an account identifier and a
    credential-shaped literal on the same line is a login being documented, no
    matter what the line calls itself.
    """
    if re.search(r"password|passwd|secret|api[_ ]?key|token", line, re.IGNORECASE):
        return True
    literals = re.findall(r"`([^`\s]+)`", line)
    has_account = any("@" in lit for lit in literals)
    has_secret = any(_looks_like_a_credential(lit) for lit in literals)
    return has_account and has_secret


def _looks_like_a_credential(value: str) -> bool:
    """A literal worth refusing in prose: mixed case, digits, length.

    Excludes camelCase identifiers, which is the whole point - `verifyMagic2fa`
    satisfies every other condition here and is obviously not a password.
    """
    if not value.isalnum():
        return False
    if re.fullmatch(r"[a-z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*", value):
        return False  # a camelCase identifier
    has_digit = any(c.isdigit() for c in value)
    has_alpha_lower = any(c.islower() for c in value)
    has_alpha_upper = any(c.isupper() for c in value)
    return has_digit and has_alpha_lower and has_alpha_upper and len(value) >= 10


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


@pytest.mark.parametrize("path", _files(BACKEND, CODE_GLOBS_BACKEND), ids=lambda p: p.name)
def test_no_script_carries_a_credential_default(path: Path):
    problems = _scan([path], check_docs=False)
    assert not problems, "\n".join(problems)


def test_no_documentation_quotes_a_credential_value():
    """The seeder's password reached three READMEs before anyone noticed.

    Documentation is not a lower-risk place for a credential than code - it is
    the *most* public, because it is rendered on the page. This is the check that
    would have caught it the first time.
    """
    problems = _scan(_files(REPO, DOC_GLOBS_REPO), check_docs=True)
    assert not problems, "\n".join(problems)


def test_the_seeder_still_works_without_an_explicit_password():
    """Removing the default must not mean there is no password.

    The obvious wrong way to satisfy the rule above is to leave the accounts
    unusable. `SEED_PASSWORD` overrides; without it, one is generated. Both paths
    have to exist, or the check is satisfied by breaking the tool.
    """
    source = (BACKEND / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert "SEED_PASSWORD" in source, "SEED_PASSWORD override was removed"
    assert "_generate_seed_password" in source, (
        "the seeder no longer has a generated fallback - the accounts would be "
        "unusable without SEED_PASSWORD, and the fix would be to put a literal "
        "back"
    )
    # The default must be genuinely absent, not merely not matched by the regex.
    assert '"testpass123"' not in source


def test_the_load_test_requires_an_explicit_password():
    """`LOCUST_PASSWORD` has no default and the file says so.

    A load test that will not start until a variable is set is a five-second fix.
    A published password that someone reuses against staging is permanent.
    """
    source = (BACKEND / "scripts" / "locustfile.py").read_text(encoding="utf-8")

    assert '"TstPsX79!bQ"' not in source
    assert "LOCUST_PASSWORD" in source
    assert "RuntimeError" in source, (
        "an unset LOCUST_PASSWORD must fail loudly - a silent empty password "
        "would authenticate as nobody and produce a load test that measures "
        "nothing while appearing to run"
    )