# Embedding Model Shootout (v1.6.2)

## Baseline (v1.6.0 hybrid real)

| Question Type | R@5 |
|---------------|-----|
| knowledge-update | 1.000 |
| multi-session | 0.923 |
| single-session-assistant | 0.982 |
| single-session-preference | 0.967 |
| single-session-user | 1.000 |
| temporal-reasoning | 0.915 |

## Results

| Model | knowledge-update | multi-session | single-session-assistant | single-session-preference | single-session-user | temporal-reasoning |
|-------|------------------|---------------|--------------------------|---------------------------|---------------------|--------------------|
| all-MiniLM-L6-v2 | 1.000 | 0.923 | 0.982 | 0.967 | 1.000 | 0.915 |
| bge-small-en-v1.5 | 0.987 | 0.933 | 1.000 | 0.867 | 1.000 | 0.887 |
| nomic-embed-text-v1.5 | 0.968 | 0.871 | 1.000 | 0.900 | 0.943 | 0.865 |

## Delta from Baseline

| Model | knowledge-update | multi-session | single-session-assistant | single-session-preference | single-session-user | temporal-reasoning |
|-------|------------------|---------------|--------------------------|---------------------------|---------------------|--------------------|
| all-MiniLM-L6-v2 | +0.000 | +0.000 | +0.000 | -0.000 | +0.000 | -0.000 |
| bge-small-en-v1.5 | -0.013 | +0.010 | +0.018 | -0.100 | +0.000 | -0.028 |
| nomic-embed-text-v1.5 | -0.032 | -0.052 | +0.018 | -0.067 | -0.057 | -0.050 |

## Decision

**Selected model:** `all-MiniLM-L6-v2`

**Reason:** Rule 3: fallback (no model met rules 1 or 2)

## Decision Rules

1. All 6 dims ≥ baseline AND ≥2 dims +1pp (≥0.010)
2. ≥4 dims ≥ baseline AND ≥1 dim +2pp (≥0.020)
3. Fallback to all-MiniLM-L6-v2

Tiebreaker priority: bge-small-en-v1.5 > nomic-embed-text-v1.5 > all-MiniLM-L6-v2
