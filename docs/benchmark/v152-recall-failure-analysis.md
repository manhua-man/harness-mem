# v1.5.2 Recall Failure Analysis

> Maintainer / benchmark artifact — paths below are from the machine that generated this report.

- Generated: 2026-05-16T16:20:35.691124+00:00
- Dataset: `<local-temp>/longmemeval_s_cleaned.json`
- Baseline: `benchmarks/results/results_harness_hybrid_temporal_compare_top5_20260512_fixed_baseline.json`
- Failed hybrid cases analyzed: 57

## Bucket Summary

| Bucket | Cases |
|--------|-------|
| fts_miss | 13 |
| vector_miss | 4 |
| fusion_sort_error | 26 |
| mixed_or_both_miss | 14 |

## Latency Snapshot

| Variant | Avg (ms) | P50 (ms) | P95 (ms) | Max (ms) |
|---------|----------|----------|----------|----------|
| fts | 1.63 | 1.53 | 2.23 | 4.69 |
| vector | 1002.96 | 552.73 | 620.65 | 26050.97 |
| hybrid | 560.22 | 561.30 | 631.01 | 672.24 |

## Per-Type Buckets

| Question Type | FTS Miss | Vector Miss | Fusion Sort Error | Mixed/Both |
|---------------|----------|-------------|-------------------|------------|
| multi-session | 8 | 2 | 12 | 7 |
| single-session-assistant | 0 | 0 | 1 | 0 |
| single-session-preference | 0 | 0 | 3 | 0 |
| single-session-user | 0 | 0 | 1 | 0 |
| temporal-reasoning | 5 | 2 | 9 | 7 |

## Representative Cases

### fts_miss

- `6d550036` [multi-session] How many projects have I led or am currently leading?
  Recall -> fts 0.000, vector 0.250, hybrid 0.250
  Latency -> fts 1.42ms, vector 534.09ms, hybrid 564.97ms
  Answer sessions: answer_ec904b3c_1, answer_ec904b3c_4, answer_ec904b3c_3, answer_ec904b3c_2
  Hybrid top-5: 2e4430d8_2, sharegpt_J7ZAFLd_0, sharegpt_zciCXP1_12, answer_ec904b3c_1, a9981dc6_3

- `60bf93ed_abs` [multi-session] How many days did it take for my iPad case to arrive after I bought it?
  Recall -> fts 0.000, vector 0.500, hybrid 0.500
  Latency -> fts 1.49ms, vector 567.88ms, hybrid 595.32ms
  Answer sessions: answer_e0956e0a_abs_2, answer_e0956e0a_abs_1
  Hybrid top-5: c1e170f0_1, a95d014c_3, 6cd203f7_2, 1e91cdf0, answer_e0956e0a_abs_2

- `b46e15ed` [temporal-reasoning] How many months have passed since I participated in two charity events in a row, on consecutive days?
  Recall -> fts 0.250, vector 0.500, hybrid 0.500
  Latency -> fts 1.59ms, vector 571.24ms, hybrid 570.43ms
  Answer sessions: answer_4bfcc250_4, answer_4bfcc250_3, answer_4bfcc250_2, answer_4bfcc250_1
  Hybrid top-5: sharegpt_KCGdZJP_0, answer_4bfcc250_1, answer_4bfcc250_3, sharegpt_cXkL3cR_28, ultrachat_396986

### vector_miss

- `1a8a66a6` [multi-session] How many magazine subscriptions do I currently have?
  Recall -> fts 0.500, vector 0.250, hybrid 0.500
  Latency -> fts 0.99ms, vector 566.01ms, hybrid 561.40ms
  Answer sessions: answer_2bd23659_3, answer_2bd23659_2, answer_2bd23659_4, answer_2bd23659_1
  Hybrid top-5: answer_2bd23659_1, sharegpt_sXKNzPE_29, ebb5d262, b01aafcb_2, answer_2bd23659_3

- `4dfccbf8` [temporal-reasoning] What did I do with Rachel on the Wednesday two months ago?
  Recall -> fts 0.500, vector 0.000, hybrid 0.500
  Latency -> fts 1.17ms, vector 542.10ms, hybrid 539.56ms
  Answer sessions: answer_4bebc783_1, answer_4bebc783_2
  Hybrid top-5: b4f63a70_3, a63ad8e3_3, edd89480_1, 87317e05_1, answer_4bebc783_1

- `gpt4_68e94288` [temporal-reasoning] What was the social media activity I participated 5 days ago?
  Recall -> fts 0.500, vector 0.000, hybrid 0.500
  Latency -> fts 1.32ms, vector 509.56ms, hybrid 506.10ms
  Answer sessions: answer_9793daa4_2, answer_9793daa4_1
  Hybrid top-5: c99dcd81, ultrachat_396489, 4c49e37f, answer_9793daa4_1, sharegpt_tIgSwQL_35

### fusion_sort_error

- `f4f1d8a4_abs` [single-session-user] What did my dad gave me as a birthday gift?
  Recall -> fts 1.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.22ms, vector 26050.97ms, hybrid 590.56ms
  Answer sessions: answer_f5b33470_abs
  Hybrid top-5: 1dd13331_1, ea3db78e_2, f252001e, 31299b8e_2, sharegpt_eVmxjQZ_0

- `10d9b85a` [multi-session] How many days did I spend attending workshops, lectures, and conferences in April?
  Recall -> fts 1.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.57ms, vector 540.04ms, hybrid 568.57ms
  Answer sessions: answer_e0585cb5_2, answer_e0585cb5_1
  Hybrid top-5: cbd1fe79_2, 84889496_1, 02b63d04_2, 4e59fb02_2, aa6afba8

- `06f04340` [single-session-preference] What should I serve for dinner this weekend with my homegrown ingredients?
  Recall -> fts 0.000, vector 1.000, hybrid 0.000
  Latency -> fts 1.49ms, vector 555.86ms, hybrid 549.93ms
  Answer sessions: answer_92d5f7cd
  Hybrid top-5: 91223fd5_1, 6e6fbb6b, 66bfa1db, b459f888_3, de1f4aec_2

### mixed_or_both_miss

- `gpt4_4929293b` [temporal-reasoning] What was the the life event of one of my relatives that I participated in a week ago?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.77ms, vector 603.69ms, hybrid 561.30ms
  Answer sessions: answer_add9b013_2, answer_add9b013_1
  Hybrid top-5: ultrachat_326769, 4090cbea, bda611f6_3, sharegpt_0V1N7Qc_0, sharegpt_KFhIUCO_0

- `eac54add` [temporal-reasoning] What was the significant buisiness milestone I mentioned four weeks ago?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.24ms, vector 513.79ms, hybrid 504.46ms
  Answer sessions: answer_0d4d0348_1, answer_0d4d0348_2
  Hybrid top-5: sharegpt_5YtukCb_0, 773aebbd_3, ultrachat_133409, 369695b4_2, ultrachat_275712

- `gpt4_8279ba03` [temporal-reasoning] What kitchen appliance did I buy 10 days ago?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.10ms, vector 545.48ms, hybrid 535.62ms
  Answer sessions: answer_56521e66_1
  Hybrid top-5: d9868305_1, 652c0717_3, bb107057_2, ultrachat_526748, 2ef55f49_3
