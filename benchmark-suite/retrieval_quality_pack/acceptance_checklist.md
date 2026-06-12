# Acceptance Checklist

- [ ] Every result row has `benchmark_id=retrieval_quality_pack`.
- [ ] Required capabilities are present: reranker, query_rewriting, multi_query_hyde, embedding_shootout, retrieval_drift_suite.
- [ ] Query rewriting only passes when `recall_delta > false_positive_delta`.
- [ ] Reranker rows include model size, cold start, precision, latency/RSS notes, and default-enabled state.
- [ ] Multi-query/HyDE rows include fanout cost, duplicate rate, and sufficiency delta.
- [ ] Embedding rows keep `all-MiniLM-L6-v2` as the baseline unless all gates pass.
