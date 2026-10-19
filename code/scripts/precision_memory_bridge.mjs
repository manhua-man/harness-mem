/** Thin no-model bridge to frozen PrecisionMemBench code (MIT, tenurehq).
 * Reuses its serializer, assertions and report summary without copying scores
 * into this project. This scoped replay is not the upstream AVA benchmark run.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';

const [mode, root, recorded] = process.argv.slice(2);
const read = path => readFileSync(resolve(root, path), 'utf8');
const sha = value => createHash('sha256').update(value).digest('hex');
const adapterSource = read('src/adapters/baseAdapter.ts');
const scorerSource = read('src/retrieval.external.eval.test.ts');
const summarySource = read('src/utils/buildRetrievalReport.ts');
const beliefs = JSON.parse(read('fixtures/beliefs.seed.json'));
const cases = JSON.parse(read('fixtures/retrieval.cases.json'));

function boundedSlice(source, start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first + start.length);
  if (first < 0 || last < 0 || source.indexOf(start, first + 1) >= 0)
    throw new Error('Frozen upstream structure changed; refuse a different scorer');
  return source.slice(first, last);
}

const method = boundedSlice(adapterSource, '  protected beliefToText(', '\n  }') + '\n  }';
const serializeSource = method.replace('  protected beliefToText', 'function serialize');
const serialize = new Function(`${stripTypeScriptTypes(serializeSource)}; return serialize;`)();
const scoring = boundedSlice(scorerSource,
  '    const pinned = JSON.parse(ctx.pinnedFactsJson)',
  '    t.is(failures.length, 0, failures.join(" | "));');
const score = new Function('tc', 'ctx', 'pinnedInSeed', 'buildStart', 'buildEnd', 'report',
  stripTypeScriptTypes(scoring));
const summary = await import('data:text/javascript;base64,' +
  Buffer.from(stripTypeScriptTypes(summarySource)).toString('base64'));

const selectedBeliefs = beliefs.filter(b => b.user_id === 'test-user' &&
  b.scope.includes('domain:code') && b.epistemic_status === 'active' &&
  !b.superseded_by && b.type !== 'open_question');
// This describes the actual representation. It does not emulate missing tiers
// or change cases/assertions to make their results look compatible.
const benchmarkQualification = {
  status: 'not_qualified_for_comparative_quality',
  rawAssertionsOnly: true,
  pinnedFactTierSupported: false,
  separateSearchableFieldsSupported: false,
  indexedRepresentation: 'title_and_full_serialized_statement_including_why_it_matters',
  pinnedHandling: 'ordinary_current_knowledge_without_pinned_exclusion',
  implicitPinnedIds: selectedBeliefs.filter(b => b.pinned).map(b => b._id),
  reasons: ['implicit_pinned_exclusion_not_represented', 'field_sensitive_assertions_not_represented'],
};
const selectedCases = [];
const unsupported = [];
for (const tc of cases) {
  const reasons = [];
  if (tc.userId && tc.userId !== 'test-user') reasons.push('separate_user_identity');
  if (tc.scope.length !== 1 || tc.scope[0] !== 'domain:code') reasons.push('other_or_multiple_scopes');
  if (tc.budget) reasons.push('upstream_item_count_budget');
  if (tc.expect.personaPrelude) reasons.push('persona_prelude');
  for (const feature of ['pinnedFacts', 'openQuestions']) {
    if (Object.values(tc.expect[feature] ?? {}).some(v => v.length)) reasons.push(feature);
  }
  if (!tc.expect.relevantBeliefs) reasons.push('no_relevant_belief_assertions');
  if (reasons.length) unsupported.push({ caseId: tc.caseId, reasons });
  else selectedCases.push(tc);
}
const provenance = {
  adapterSourceSha256: sha(adapterSource), scorerSourceSha256: sha(scorerSource),
  summarySourceSha256: sha(summarySource), scoringFragmentSha256: sha(scoring),
  serializerFragmentSha256: sha(method),
};

if (mode === 'prepare') {
  process.stdout.write(JSON.stringify({
    provenance, benchmarkQualification, unsupported, cases: selectedCases,
    beliefs: selectedBeliefs.map(b => ({ id: b._id, title: b.canonical_name, statement: serialize(b) })),
    scope: 'Fixed active code-domain state only; pinned items are ordinary knowledge; no extraction claim',
  }));
} else if (mode === 'score') {
  const observations = JSON.parse(readFileSync(recorded, 'utf8'));
  const selected = new Map(selectedCases.map(tc => [tc.caseId, tc]));
  const entries = [];
  const pinnedInSeed = new Set(beliefs.filter(b => b.pinned && b.user_id === 'test-user').map(b => b._id));
  for (const observation of observations.filter(row => !row.cold)) {
    const tc = selected.get(observation.caseId);
    if (!tc) throw new Error('Observation is outside the preselected applicable subset');
    const ctx = { personaPrelude: '', pinnedFactsJson: '[]', openQuestionsJson: '[]',
      relevantBeliefsJson: JSON.stringify(observation.ids.map(id => ({ id }))) };
    score(tc, ctx, pinnedInSeed, 0, observation.latencyMs, entries);
  }
  process.stdout.write(JSON.stringify({ provenance, benchmarkQualification, unsupported, entries,
    summary: summary.buildRetrievalSummary({ provider: 'harness-mem-scoped-replay', entries, caseCount: entries.length }),
    officialBenchmarkRun: false,
  }));
} else throw new Error('Use prepare or score; neither mode invokes a provider');
