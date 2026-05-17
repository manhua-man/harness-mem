# v1.5.2 Recall Failure Analysis

- Generated: 2026-05-16T17:11:49.160306+00:00
- Dataset: `C:\Users\ManHua\AppData\Local\Temp\longmemeval_s_cleaned.json`
- Baseline: `benchmarks\results\results_harness_hybrid_real_confidence_rrf_top5_20260517.json`
- Failed hybrid cases analyzed: 52

## Bucket Summary

| Bucket | Cases |
|--------|-------|
| fts_miss | 14 |
| vector_miss | 3 |
| fusion_sort_error | 21 |
| mixed_or_both_miss | 14 |

## Latency Snapshot

| Variant | Avg (ms) | P50 (ms) | P95 (ms) | Max (ms) |
|---------|----------|----------|----------|----------|
| fts | 1.50 | 1.45 | 1.99 | 3.84 |
| vector | 1017.61 | 562.12 | 639.39 | 24353.64 |
| hybrid | 561.80 | 564.99 | 619.65 | 669.10 |

## Per-Type Buckets

| Question Type | FTS Miss | Vector Miss | Fusion Sort Error | Mixed/Both |
|---------------|----------|-------------|-------------------|------------|
| multi-session | 8 | 2 | 9 | 6 |
| single-session-assistant | 0 | 0 | 1 | 0 |
| single-session-preference | 0 | 0 | 2 | 0 |
| single-session-user | 0 | 0 | 1 | 0 |
| temporal-reasoning | 6 | 1 | 8 | 8 |

## Representative Cases

### fts_miss

- `60bf93ed_abs` [multi-session] How many days did it take for my iPad case to arrive after I bought it?
  Recall -> fts 0.000, vector 0.500, hybrid 0.500
  Latency -> fts 1.07ms, vector 583.95ms, hybrid 569.49ms
  Answer sessions: answer_e0956e0a_abs_2, answer_e0956e0a_abs_1
  Hybrid top-5: cdf068b1_3, sharegpt_vncOfEw_0, 1e91cdf0, answer_e0956e0a_abs_1, 841da171_2

- `b46e15ed` [temporal-reasoning] How many months have passed since I participated in two charity events in a row, on consecutive days?
  Recall -> fts 0.250, vector 0.500, hybrid 0.500
  Latency -> fts 1.58ms, vector 572.02ms, hybrid 576.40ms
  Answer sessions: answer_4bfcc250_4, answer_4bfcc250_3, answer_4bfcc250_2, answer_4bfcc250_1
  Hybrid top-5: sharegpt_KCGdZJP_0, answer_4bfcc250_1, ultrachat_396986, answer_4bfcc250_3, sharegpt_cXkL3cR_28

- `gpt4_d12ceb0e` [multi-session] What is the average age of me, my parents, and my grandparents?
  Recall -> fts 0.333, vector 0.667, hybrid 0.667
  Latency -> fts 1.42ms, vector 504.03ms, hybrid 509.51ms
  Answer sessions: answer_2504635e_3, answer_2504635e_2, answer_2504635e_1
  Hybrid top-5: answer_2504635e_2, 73f4798f, 2fe5510e_3, answer_2504635e_3, sharegpt_dxirwR4_25

### vector_miss

- `4dfccbf8` [temporal-reasoning] What did I do with Rachel on the Wednesday two months ago?
  Recall -> fts 0.500, vector 0.000, hybrid 0.500
  Latency -> fts 1.22ms, vector 556.24ms, hybrid 563.53ms
  Answer sessions: answer_4bebc783_1, answer_4bebc783_2
  Hybrid top-5: edd89480_1, b4f63a70_3, 87317e05_1, 1c177942_4, answer_4bebc783_1

- `gpt4_ab202e7f` [multi-session] How many kitchen items did I replace or fix?
  Recall -> fts 0.600, vector 0.400, hybrid 0.600
  Latency -> fts 1.63ms, vector 543.68ms, hybrid 543.63ms
  Answer sessions: answer_728deb4d_5, answer_728deb4d_2, answer_728deb4d_3, answer_728deb4d_1, answer_728deb4d_4
  Hybrid top-5: answer_728deb4d_2, answer_728deb4d_3, dcafb5b3_5, answer_728deb4d_5, e78617c5_2

- `gpt4_731e37d7` [multi-session] How much total money did I spend on attending workshops in the last four months?
  Recall -> fts 0.750, vector 0.500, hybrid 0.750
  Latency -> fts 1.04ms, vector 565.71ms, hybrid 565.90ms
  Answer sessions: answer_826d51da_3, answer_826d51da_4, answer_826d51da_2, answer_826d51da_1
  Hybrid top-5: answer_826d51da_3, answer_826d51da_4, 859fc064_1, 7e4aa7c2_1, answer_826d51da_1

### fusion_sort_error

- `f4f1d8a4_abs` [single-session-user] What did my dad gave me as a birthday gift?
  Recall -> fts 1.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.32ms, vector 24353.64ms, hybrid 583.35ms
  Answer sessions: answer_f5b33470_abs
  Hybrid top-5: 1dd13331_1, ea3db78e_2, sharegpt_n7xJvjp_0, f252001e, 793382f9_2

- `09d032c9` [single-session-preference] I've been having trouble with the battery life on my phone lately. Any tips?
  Recall -> fts 0.000, vector 1.000, hybrid 0.000
  Latency -> fts 2.24ms, vector 490.90ms, hybrid 485.14ms
  Answer sessions: answer_b10dce5e
  Hybrid top-5: b21bd3e2, 46bab85b, e8bfacec_2, ultrachat_37105, 21ef2d05_1

- `d6233ab6` [single-session-preference] I've been feeling nostalgic lately. Do you think it would be a good idea to attend my high school reunion?
  Recall -> fts 1.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.67ms, vector 566.48ms, hybrid 518.30ms
  Answer sessions: answer_b0fac439
  Hybrid top-5: 94bc18df_3, 0e726047, f916c63a_2, e419b7c3_4, ultrachat_49450

### mixed_or_both_miss

- `gpt4_4929293b` [temporal-reasoning] What was the the life event of one of my relatives that I participated in a week ago?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.17ms, vector 575.53ms, hybrid 580.75ms
  Answer sessions: answer_add9b013_2, answer_add9b013_1
  Hybrid top-5: ultrachat_326769, bda611f6_3, 4090cbea, sharegpt_KFhIUCO_0, sharegpt_0V1N7Qc_0

- `9a707b82` [temporal-reasoning] I mentioned cooking something for my friend a couple of days ago. What was it?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.19ms, vector 626.67ms, hybrid 619.65ms
  Answer sessions: answer_dba89488_2, answer_dba89488_1
  Hybrid top-5: 7a4d00b3_2, ultrachat_466884, 990f3ef9_2, 68d35085_1, fab41c07

- `eac54add` [temporal-reasoning] What was the significant buisiness milestone I mentioned four weeks ago?
  Recall -> fts 0.000, vector 0.000, hybrid 0.000
  Latency -> fts 1.26ms, vector 530.57ms, hybrid 531.27ms
  Answer sessions: answer_0d4d0348_1, answer_0d4d0348_2
  Hybrid top-5: sharegpt_5YtukCb_0, ultrachat_133409, ultrachat_275712, ultrachat_134291, 773aebbd_3
