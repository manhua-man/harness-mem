"""Small offline checks of bridge capability labels and unchanged raw scoring."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


BRIDGE = Path(__file__).resolve().parents[1] / "scripts/precision_memory_bridge.mjs"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for the offline bridge")


@pytest.fixture
def upstream(tmp_path):
    root = tmp_path / "upstream"
    (root / "src/adapters").mkdir(parents=True)
    (root / "src/utils").mkdir()
    (root / "fixtures").mkdir()
    (root / "src/adapters/baseAdapter.ts").write_text(
        '  protected beliefToText(belief: any): string {\n'
        '    return [belief.canonical_name, ...belief.aliases, belief.content, belief.why_it_matters].filter(Boolean).join(" ");\n'
        '  }\n', encoding="utf-8")
    (root / "src/retrieval.external.eval.test.ts").write_text(
        '    const pinned = JSON.parse(ctx.pinnedFactsJson);\n'
        '    const relevant = JSON.parse(ctx.relevantBeliefsJson);\n'
        '    const failures = relevant.filter(x => !tc.expect.relevantBeliefs.shouldOnlyInclude.includes(x.id));\n'
        '    report.push({caseId: tc.caseId, passed: failures.length === 0, pinnedCount: pinned.length});\n'
        '    t.is(failures.length, 0, failures.join(" | "));\n', encoding="utf-8")
    (root / "src/utils/buildRetrievalReport.ts").write_text(
        'export function buildRetrievalSummary({entries}) { return {totalCases: entries.length}; }\n',
        encoding="utf-8")
    beliefs = [{"_id": identifier, "canonical_name": identifier, "aliases": [], "content": "A frozen fact.",
                "why_it_matters": "Explanatory context.", "scope": ["domain:code"], "user_id": "test-user",
                "epistemic_status": "active", "type": "decision", "pinned": pinned}
               for identifier, pinned in (("fixed", True), ("ordinary", False))]
    cases = [{"caseId": "one", "scope": ["domain:code"], "query": "frozen",
              "expect": {"relevantBeliefs": {"shouldOnlyInclude": ["ordinary"]}}}]
    (root / "fixtures/beliefs.seed.json").write_text(json.dumps(beliefs), encoding="utf-8")
    (root / "fixtures/retrieval.cases.json").write_text(json.dumps(cases), encoding="utf-8")
    return root, cases


def run_bridge(mode, root, recorded=None):
    command = ["node", "--disable-warning=ExperimentalWarning", str(BRIDGE), mode, str(root)]
    if recorded is not None:
        command.append(str(recorded))
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
    return json.loads(result.stdout)


def test_prepare_keeps_cases_and_marks_implicit_capability_gaps(upstream):
    root, cases = upstream
    prepared = run_bridge("prepare", root)
    assert prepared["cases"] == cases
    assert {row["id"] for row in prepared["beliefs"]} == {"fixed", "ordinary"}
    assessment = prepared["benchmarkQualification"]
    assert assessment["status"] == "not_qualified_for_comparative_quality"
    assert assessment["implicitPinnedIds"] == ["fixed"]
    assert assessment["pinnedFactTierSupported"] is False
    assert assessment["separateSearchableFieldsSupported"] is False
    assert "why_it_matters" in assessment["indexedRepresentation"]


def test_score_keeps_unexpected_fixed_fact_in_raw_failure(upstream, tmp_path):
    root, _cases = upstream
    observed = tmp_path / "observed.json"
    observed.write_text(json.dumps([{"caseId": "one", "cold": False, "latencyMs": 1,
                                    "ids": ["ordinary", "fixed"]}]), encoding="utf-8")
    scored = run_bridge("score", root, observed)
    assert scored["entries"][0]["passed"] is False
    assert scored["entries"][0]["pinnedCount"] == 0
    assert scored["summary"]["totalCases"] == 1
    assert scored["benchmarkQualification"]["rawAssertionsOnly"] is True
