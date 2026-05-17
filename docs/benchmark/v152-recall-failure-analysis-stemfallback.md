# v1.5.2 Recall Failure Analysis

- Generated: 2026-05-16T20:06:02.980280+00:00
- Dataset: `C:\Users\ManHua\AppData\Local\Temp\longmemeval_s_cleaned.json`
- Baseline: `benchmarks\results\results_harness_hybrid_real_stemfallback_top5_20260517.json`
- Failed hybrid cases analyzed: 49

## Bucket Summary

| Bucket | Cases |
|--------|-------|
| fts_miss | 8 |
| vector_miss | 3 |
| fusion_sort_error | 22 |
| mixed_or_both_miss | 16 |

## Latency Snapshot

| Variant | Avg (ms) | P50 (ms) | P95 (ms) | Max (ms) |
|---------|----------|----------|----------|----------|
| fts | 1.58 | 1.50 | 2.29 | 3.15 |
| vector | 854.45 | 527.85 | 653.56 | 16134.06 |
| hybrid | 537.82 | 529.41 | 625.17 | 681.54 |

## Per-Type Buckets

| Question Type | FTS Miss | Vector Miss | Fusion Sort Error | Mixed/Both |
|---------------|----------|-------------|-------------------|------------|
| multi-session | 4 | 2 | 13 | 8 |
| single-session-assistant | 0 | 0 | 1 | 0 |
| single-session-preference | 0 | 0 | 0 | 1 |
| temporal-reasoning | 4 | 1 | 8 | 7 |

## Representative Cases

### fts_miss

- `gpt4_7f6b06db` [temporal-reasoning] What is the order of the three trips I took in the past three months, from earliest to latest?
  Recall -> fts 0.333, vector 0.667, hybrid 0.667
  Latency -> fts 1.20ms, vector 587.64ms, hybrid 582.89ms
  Answer sessions: answer_5d8c99d3_1, answer_5d8c99d3_2, answer_5d8c99d3_3
  Hybrid top-5: sharegpt_CLjyR25_9, answer_5d8c99d3_1, 631e4016, ultrachat_139167, answer_5d8c99d3_2

- `gpt4_e061b84f` [temporal-reasoning] What is the order of the three sports events I participated in during the past month, from earliest to latest?
  Recall -> fts 0.000, vector 0.667, hybrid 0.667
  Latency -> fts 1.99ms, vector 505.25ms, hybrid 505.19ms
  Answer sessions: answer_8c64ce25_2, answer_8c64ce25_1, answer_8c64ce25_3
  Hybrid top-5: answer_8c64ce25_3, 0a6bf5e4_1, answer_8c64ce25_2, ultrachat_194928, ultrachat_129606

- `gpt4_15e38248` [multi-session] How many pieces of furniture did I buy, assemble, sell, or fix in the past few months?
  Recall -> fts 0.500, vector 0.750, hybrid 0.750
  Latency -> fts 1.69ms, vector 525.99ms, hybrid 523.84ms
  Answer sessions: answer_8858d9dc_3, answer_8858d9dc_1, answer_8858d9dc_4, answer_8858d9dc_2
  Hybrid top-5: answer_8858d9dc_2, answer_8858d9dc_4, d4ab49f1, answer_8858d9dc_1, sharegpt_XK3KWPT_0

### vector_miss

- `gpt4_68e94288` [temporal-reasoning] What was the social media activity I participated 5 days ago?
  Recall -> fts 0.500, vector 0.000, hybrid 0.500
  Latency -> fts 1.27ms, vector 497.60ms, hybrid 499.26ms
  Answer sessions: answer_9793daa4_2, answer_9793daa4_1
  Hybrid top-5: c99dcd81, 4c49e37f, ultrachat_396489, answer_9793daa4_1, sharegpt_tIgSwQL_35

- `d23cf73b` [multi-session] How many different cuisines have I learned to cook or tried out in the past few months?
  Recall -> fts 0.750, vector 0.500, hybrid 0.750
  Latency -> fts 1.46ms, vector 527.85ms, hybrid 542.76ms
  Answer sessions: answer_5a0d28f8_4, answer_5a0d28f8_2, answer_5a0d28f8_3, answer_5a0d28f8_1
  Hybrid top-5: answer_5a0d28f8_1, answer_5a0d28f8_3, ultrachat_375734, answer_5a0d28f8_2, ultrachat_456819

- `gpt4_731e37d7` [multi-session] How much total money did I spend on attending workshops in the last four months?
  Recall -> fts 0.750, vector 0.500, hybrid 0.750
  Latency -> fts 3.14ms, vector 549.30ms, hybrid 552.01ms
  Answer sessions: answer_826d51da_3, answer_826d51da_4, answer_826d51da_2, answer_826d51da_1
  Hybrid top-5: answer_826d51da_3, answer_826d51da_4, answer_826d51da_1, 7e4aa7c2_1, sharegpt_Qga4bRp_0

### fusion_sort_error

- `4baee567` [single-session-assistant] I was looking back at our previous chat and I wanted to confirm, how many times did the Chiefs play the Jaguars at Arrowhead Stadium?
  Recall -> fts 1.000, vector 0.000, hybrid 0.000
  Latency -> fts 3.15ms, vector 658.94ms, hybrid 681.54ms
  Answer sessions: answer_sharegpt_i9adwQn_0
  Hybrid top-5: 6169ef55_1, sharegpt_Srdh9ZA_0, ultrachat_323343, 2c22e0e8_1, sharegpt_28Mwwk9_0

- `4dfccbf8` [temporal-reasoning] What did I do with Rachel on the Wednesday two months ago?
  Recall -> fts 0.500, vector 0.000, hybrid 0.000
  Latency -> fts 1.09ms, vector 530.86ms, hybrid 524.11ms
  Answer sessions: answer_4bebc783_1, answer_4bebc783_2
  Hybrid top-5: b4f63a70_3, edd89480_1, 87317e05_1, 1c177942_4, sharegpt_7EAenKv_0

- `10d9b85a` [multi-session] How many days did I spend attending workshops, lectures, and conferences in April?
  Recall -> fts 1.000, vector 0.000, hybrid 0.500
  Latency -> fts 2.29ms, vector 537.49ms, hybrid 530.77ms
  Answer sessions: answer_e0585cb5_2, answer_e0585cb5_1
  Hybrid top-5: cbd1fe79_2, 02b63d04_2, 84889496_1, answer_e0585cb5_2, 4e59fb02_2

### mixed_or_both_miss

- `d6233ab6` [single-session-preference] I've been feeling nostalgic lately. Do you think it would be a good idea to attend my high school reunion?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.98ms, vector 520.82ms, hybrid 486.44ms
  Answer sessions: answer_b0fac439
  Hybrid top-5: 94bc18df_3, 0e726047, f916c63a_2, ultrachat_49450, e419b7c3_4

- `gpt4_4929293b` [temporal-reasoning] What was the the life event of one of my relatives that I participated in a week ago?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.37ms, vector 562.04ms, hybrid 537.29ms
  Answer sessions: answer_add9b013_2, answer_add9b013_1
  Hybrid top-5: ultrachat_326769, bda611f6_3, 4090cbea, sharegpt_KFhIUCO_0, sharegpt_0V1N7Qc_0

- `9a707b82` [temporal-reasoning] I mentioned cooking something for my friend a couple of days ago. What was it?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.32ms, vector 653.56ms, hybrid 652.86ms
  Answer sessions: answer_dba89488_2, answer_dba89488_1
  Hybrid top-5: fab41c07, 68d35085_1, 990f3ef9_2, ultrachat_466884, 7a4d00b3_2
