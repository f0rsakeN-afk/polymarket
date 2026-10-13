"""Alert rules must reference metrics that exist.

This is the failure mode alerting is worst at.

A Prometheus rule naming a metric that is never exported is **valid, loads
without complaint, and never fires**. Nothing breaks. The dashboard is empty, the
alert list is empty, and the stack looks perfectly healthy - so the one thing it
exists to do, it silently does not do, and nobody finds out until the incident it
was supposed to catch.

That is exactly the state this repository was in before `monitoring/` existed:
the app exported `/metrics`, several counters described the failure modes of the
realtime path precisely, and nothing read any of it. The publish queue exists to
stop frames being dropped, and a dropped-frame counter nobody watched would have
made it decorative.

So the rule files are parsed here and every metric they reference is checked
against the ones the application actually declares. Renaming a metric without
updating the rules fails this test instead of quietly disarming the alert.

Checked against the *source* rather than a running server so it works in CI,
where no application is listening.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "monitoring" / "rules"
METRICS_SOURCE = ROOT / "app" / "middleware" / "metrics.py"

# `ws_` is the realtime namespace these rules are written against. Anything
# outside it is either a typo or a rule that drifted onto another subsystem.
PREFIX = "ws_"


def _metric_names_in_source() -> set[str]:
    """Every metric the application declares, from its own source.

    Reads the *name string* passed to the collector rather than the Python
    variable. Those differ (`WS_PUBLISH_FAILURES` declares
    `ws_publish_failures_total`), and only the string is what Prometheus
    actually exports - matching the variable would have passed while checking
    names nothing ever emits.
    """
    source = METRICS_SOURCE.read_text(encoding="utf-8")
    return set(
        re.findall(
            r'=\s*(?:Counter|Gauge|Histogram|Summary)\(\s*\n\s*"(ws_[A-Za-z0-9_]+)"',
            source,
        )
    )


def _rule_files() -> list[Path]:
    files = sorted(RULES_DIR.glob("*.yml"))
    assert files, f"no alert rules found in {RULES_DIR}"
    return files


def _metrics_referenced() -> dict[str, set[str]]:
    """Metric names each rule file references, ignoring functions and keywords."""
    keywords = {
        "rate", "increase", "sum", "max", "min", "avg", "by", "without",
        "clamp_min", "clamp_max", "and", "or", "unless", "on", "ignoring",
        "group_left", "group_right", "absent", "offset", "bool",
    }
    found: dict[str, set[str]] = {}
    for path in _rule_files():
        names = set()
        for raw in re.split(r"[^\w:]", path.read_text(encoding="utf-8")):
            name = raw.strip()
            if not name.startswith(PREFIX):
                continue
            base = name.split(":")[0].split("{")[0]
            if base and base not in keywords:
                names.add(base)
        found[str(path.name)] = names
    return found


def test_alert_rules_reference_only_real_metrics():
    declared = _metric_names_in_source()
    assert declared, "found no ws_* metrics declared - has the naming moved?"

    unknown: dict[str, set[str]] = {}
    for filename, referenced in _metrics_referenced().items():
        missing = {m for m in referenced if m not in declared}
        if missing:
            unknown[filename] = missing

    assert not unknown, (
        "alert rules reference metrics the application does not export. These "
        "rules would load cleanly and never fire, which is worse than no "
        f"alerting at all:\n{unknown}\n\ndeclared: {sorted(declared)}"
    )


def test_every_rule_has_a_severity_and_an_annotation():
    """An alert nobody can act on is noise.

    Severity drives routing and inhibition; without it a root cause and its
    consequences page identically. Annotations are what a person reads at 3am -
    a bare metric name is not a runbook.
    """
    for path in _rule_files():
        rules = yaml.safe_load(path.read_text(encoding="utf-8"))
        for group in rules.get("groups", []):
            for rule in group.get("rules", []):
                name = rule.get("alert", "<unnamed>")
                assert rule.get("expr"), f"{name} has no expression"
                labels = rule.get("labels", {})
                assert labels.get("severity") in {"critical", "warning"}, (
                    f"{name} needs severity critical|warning to route and inhibit"
                )
                annotations = rule.get("annotations", {})
                assert annotations.get("summary"), f"{name} needs a summary"
                assert annotations.get("description"), f"{name} needs a description"


def test_the_metrics_that_matter_are_actually_alerted_on():
    """Guard the specific gap this whole exercise exists to close.

    It is possible to write a thorough rules file that happens to cover none of
    the failures that have actually occurred here. This asserts the ones that
    have: dropped frames, a queue nobody is draining, and reconciliation debt.
    """
    referenced: set[str] = set()
    for names in _metrics_referenced().values():
        referenced |= names

    for metric in (
        "ws_publish_dropped_total",
        "ws_publish_failures_total",
        "ws_publish_queue_depth",
        "ws_publish_spill_owed_total",
        "ws_publish_queued_total",
    ):
        assert metric in referenced, (
            f"{metric} is instrumented but not alerted on - which is the same as "
            "not instrumenting it"
        )


def test_alerting_is_wired_into_production_compose():
    """Rules nothing executes are just YAML.

    The app exposing `/metrics` was true long before this directory existed, and
    it bought nothing. The rules only matter if something loads them.
    """
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "prom/prometheus" in compose, "no Prometheus service in production compose"
    assert "prom/alertmanager" in compose, "no Alertmanager, so alerts have nowhere to go"
    assert "./monitoring/rules" in compose, "rule files are not mounted into Prometheus"