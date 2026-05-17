# v1.5.2 Recall Failure Analysis

- Generated: 2026-05-16T19:00:16.715030+00:00
- Dataset: `C:\Users\ManHua\AppData\Local\Temp\longmemeval_s_cleaned.json`
- Baseline: `benchmarks\results\results_harness_hybrid_real_confidence_rrf_ftsmatch_top5_20260517.json`
- Failed hybrid cases analyzed: 54

## Bucket Summary

| Bucket | Cases |
|--------|-------|
| fts_miss | 8 |
| vector_miss | 3 |
| fusion_sort_error | 26 |
| mixed_or_both_miss | 17 |

## Latency Snapshot

| Variant | Avg (ms) | P50 (ms) | P95 (ms) | Max (ms) |
|---------|----------|----------|----------|----------|
| fts | 2.07 | 1.93 | 3.04 | 4.98 |
| vector | 1142.08 | 735.15 | 1548.13 | 14285.89 |
| hybrid | 802.33 | 745.04 | 1093.30 | 1878.57 |

## Per-Type Buckets

| Question Type | FTS Miss | Vector Miss | Fusion Sort Error | Mixed/Both |
|---------------|----------|-------------|-------------------|------------|
| multi-session | 4 | 2 | 16 | 8 |
| single-session-assistant | 0 | 0 | 1 | 0 |
| single-session-preference | 0 | 0 | 0 | 1 |
| temporal-reasoning | 4 | 1 | 9 | 8 |

## Representative Cases

### fts_miss

- `60bf93ed_abs` [multi-session] How many days did it take for my iPad case to arrive after I bought it?
  Recall -> fts 0.000, vector 0.500, hybrid 0.500
  Latency -> fts 1.93ms, vector 929.37ms, hybrid 810.92ms
  Answer sessions: answer_e0956e0a_abs_2, answer_e0956e0a_abs_1
  Hybrid top-5: cdf068b1_3, sharegpt_vncOfEw_0, c1e170f0_1, answer_e0956e0a_abs_1, 841da171_2

- `gpt4_7f6b06db` [temporal-reasoning] What is the order of the three trips I took in the past three months, from earliest to latest?
  Recall -> fts 0.333, vector 0.667, hybrid 0.667
  Latency -> fts 1.65ms, vector 721.20ms, hybrid 842.32ms
  Answer sessions: answer_5d8c99d3_1, answer_5d8c99d3_2, answer_5d8c99d3_3
  Hybrid top-5: sharegpt_CLjyR25_9, answer_5d8c99d3_1, 631e4016, ultrachat_139167, answer_5d8c99d3_2

- `gpt4_e061b84f` [temporal-reasoning] What is the order of the three sports events I participated in during the past month, from earliest to latest?
  Recall -> fts 0.000, vector 0.667, hybrid 0.667
  Latency -> fts 3.04ms, vector 999.22ms, hybrid 931.75ms
  Answer sessions: answer_8c64ce25_2, answer_8c64ce25_1, answer_8c64ce25_3
  Hybrid top-5: answer_8c64ce25_3, 0a6bf5e4_1, answer_8c64ce25_2, ultrachat_194928, 78d28576_2

### vector_miss

- `gpt4_68e94288` [temporal-reasoning] What was the social media activity I participated 5 days ago?
  Recall -> fts 0.500, vector 0.000, hybrid 0.500
  Latency -> fts 1.30ms, vector 683.82ms, hybrid 578.93ms
  Answer sessions: answer_9793daa4_2, answer_9793daa4_1
  Hybrid top-5: c99dcd81, ultrachat_396489, answer_9793daa4_1, sharegpt_tIgSwQL_35, ba80721c

- `d23cf73b` [multi-session] How many different cuisines have I learned to cook or tried out in the past few months?
  Recall -> fts 0.750, vector 0.500, hybrid 0.750
  Latency -> fts 4.57ms, vector 624.42ms, hybrid 663.06ms
  Answer sessions: answer_5a0d28f8_4, answer_5a0d28f8_2, answer_5a0d28f8_3, answer_5a0d28f8_1
  Hybrid top-5: answer_5a0d28f8_3, answer_5a0d28f8_1, ultrachat_375734, ultrachat_456819, answer_5a0d28f8_2

- `gpt4_731e37d7` [multi-session] How much total money did I spend on attending workshops in the last four months?
  Recall -> fts 0.750, vector 0.500, hybrid 0.750
  Latency -> fts 2.14ms, vector 622.60ms, hybrid 745.04ms
  Answer sessions: answer_826d51da_3, answer_826d51da_4, answer_826d51da_2, answer_826d51da_1
  Hybrid top-5: answer_826d51da_3, answer_826d51da_4, answer_826d51da_1, sharegpt_Qga4bRp_0, 7e4aa7c2_1

### fusion_sort_error

- `gpt4_21adecb5` [temporal-reasoning] How many months passed between the completion of my undergraduate degree and the submission of my master's thesis?
  Recall -> fts 1.000, vector 0.000, hybrid 0.000
  Latency -> fts 2.56ms, vector 1094.92ms, hybrid 836.43ms
  Answer sessions: answer_1e2369c9_1, answer_1e2369c9_2
  Hybrid top-5: sharegpt_ipLglky_42, sharegpt_pydqYVn_0, b99bd2df, 666d4c9e, sharegpt_MCmVQ20_0

- `4baee567` [single-session-assistant] I was looking back at our previous chat and I wanted to confirm, how many times did the Chiefs play the Jaguars at Arrowhead Stadium?
  Recall -> fts 1.000, vector 0.000, hybrid 0.000
  Latency -> fts 4.98ms, vector 761.16ms, hybrid 784.95ms
  Answer sessions: answer_sharegpt_i9adwQn_0
  Hybrid top-5: 6169ef55_1, sharegpt_Srdh9ZA_0, ultrachat_323343, 2c22e0e8_1, sharegpt_28Mwwk9_0

- `4dfccbf8` [temporal-reasoning] What did I do with Rachel on the Wednesday two months ago?
  Recall -> fts 0.500, vector 0.000, hybrid 0.000
  Latency -> fts 1.70ms, vector 632.70ms, hybrid 663.36ms
  Answer sessions: answer_4bebc783_1, answer_4bebc783_2
  Hybrid top-5: b4f63a70_3, edd89480_1, 87317e05_1, 1c177942_4, sharegpt_7EAenKv_0

### mixed_or_both_miss

- `d6233ab6` [single-session-preference] I've been feeling nostalgic lately. Do you think it would be a good idea to attend my high school reunion?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 2.63ms, vector 1448.63ms, hybrid 972.71ms
  Answer sessions: answer_b0fac439
  Hybrid top-5: 94bc18df_3, 0e726047, f916c63a_2, ultrachat_49450, e419b7c3_4

- `gpt4_4929293b` [temporal-reasoning] What was the the life event of one of my relatives that I participated in a week ago?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.23ms, vector 740.14ms, hybrid 615.42ms
  Answer sessions: answer_add9b013_2, answer_add9b013_1
  Hybrid top-5: ultrachat_326769, bda611f6_3, sharegpt_KFhIUCO_0, 4090cbea, sharegpt_0V1N7Qc_0

- `9a707b82` [temporal-reasoning] I mentioned cooking something for my friend a couple of days ago. What was it?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.51ms, vector 701.21ms, hybrid 648.06ms
  Answer sessions: answer_dba89488_2, answer_dba89488_1
  Hybrid top-5: fab41c07, ultrachat_466884, 990f3ef9_2, 68d35085_1, 7a4d00b3_2
