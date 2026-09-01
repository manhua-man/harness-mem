import {
  BarChart,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  UsageBar,
  useHostTheme,
} from "cursor/canvas";

const AS_OF = "2026-09-02";
const RUNTIME_VERSION = "0.9.26";
const PUBLIC_RELEASE_VERSION = "0.9.25";
const PYTEST_COUNT = 1027;
const MCP_TOOL_COUNT = 27;
const HOST_COUNT = 7;
const OUTCOME_CLAIM_COUNT = 14;

const MODULES: string[][] = [
  ["0 会话接入", "1 session + 1 immutable revision", "宿主接入 · chunk · job · receipt · 来源生命周期", "不判断陈述是否值得长期记忆"],
  ["1 提取", "0–12 promotion points / session", "窄 claim · 可重开 source location · 完整 manifest", "不验证证据 · 不写长期知识"],
  ["2 逐点验证", "1 promotion point", "reference integrity · Answer Gate fail-closed", "不决定 durable value · 不改长期知识"],
  ["3 归纳吸收", "1 verified point", "九处置 · 去重 · SQLite mutation · 自然模块", "不获取原始来源 · 不默认暴露 audit"],
  ["4 检索使用", "1 task / query", "干净 wake/search · 项目隔离 · bounded feedback", "normal 结果不暴露 transcript/candidate/ID"],
];

const STORAGE_ROLES: string[][] = [
  ["Transcript ledger", "证据 authority", "raw revision / chunk · 不是长期事实"],
  ["Job workspace", "临时材料", "candidate · evidence · proposed decision · 成功终态后按策略清理"],
  ["canonical.sqlite / knowledge_entries", "当前知识 authority", "稳定 ID · 模块路径 · 标题 · 一条正文 · 验证日期"],
  ["Derived FTS / vector / Markdown", "可重建投影", "不得反向成为写路径或 truth 源"],
];

const EXECUTION_PATHS: string[][] = [
  ["人工 distill", "当前宿主读取会话", "prepare → submit → finalize · 不走后台改道"],
  ["Hook SessionStop", "仅模块 0", "持久化 source/job · 唤醒 Dream · 不执行语义判断"],
  ["Dream", "唯一无人值守执行者", "已授权 → 所选 CLI Agent（默认当前宿主，也可明确指定）· 同一路验证与吸收"],
  ["Review", "事后审计支路", "纠错 · supersede · undo · 不替代逐点验证"],
];

const RELEASE_TRAIN: string[][] = [
  ["0.9.20", "六会话 frozen oracle · clean SQLite 知识库 · 14 项实际结果检查首次通过", "Released"],
  ["0.9.21", "code/ 物理迁移 · 授权 harness-mem legacy 收敛（项目隔离 · 可逆）", "Released"],
  ["0.9.22", "archive repair · clean search · Autopilot 边界 · truth archival 门禁", "Released"],
  ["0.9.23", "operator-owned provider profile · Dream 终态 source recheck · 凭证不进项目配置", "Released"],
  ["0.9.24", "Anthropic 兼容网关 strict JSON 无工具传输 · schema fail-closed", "Released"],
  ["0.9.25", "Hook→Dream 唯一路径 · 截断来源 fail-closed · undo/receipt/provider 终态", "Released"],
  ["0.9.26", "enabled + 默认当前宿主、也可指定 CLI · 诚实 {host}_cli 回执", "main 已实现；尚未发布"],
];

const OUT_OF_PRODUCT: string[][] = [
  ["PyPI 发布", "out_of_product", "GitHub Releases 为唯一包通道 · defer.md"],
  ["M10 wiki bridge", "out_of_product", "maturity-model · 非 memory core"],
  ["Graph DB 默认路线", "out_of_product", "roadmap Later/Labs · 非当前架构"],
  ["code/mcps/grok_com_github/**", "out_of_product", "defer.md · 非产品面"],
];

const OUTCOME_CLAIMS: string[][] = [
  ["codex_cleanup_liveness", "Native cleanup 只删 definitively inactive task"],
  ["archive_distill_batch_outcome", "Archive distill 全链路：Packet · Note · ledger · retrieval · cleanup"],
  ["codex_hook_lifecycle", "Desktop Hook start/post-turn 有 fresh receipt"],
  ["dream_execution", "Dream 在验证窗口内有 persisted successful run"],
  ["distill_user_artifacts", "已完成 distill 有可读 Session Note 或 audited-unavailable"],
  ["autonomous_distill_completion", "Detached Hook worker 完成语义蒸馏"],
  ["autonomous_note_materialization", "Autonomous completion 物化 job-bound Note"],
  ["autonomous_provider_isolation", "host CLI agent · execution_mode=agent · provider=<host>_cli · hook_reentry_count==0"],
  ["partial_distill_handoff", "Partial distill：独立 Answered 点 + handoff + 分离 Note"],
  ["distill_acceptance_matrix", "F1–F11 fixture 路径矩阵可执行验收"],
  ["multi_point_memory_assimilation", "多点独立 assimilation 与 SQLite 当前知识"],
  ["clean_retrieval_boundary", "normal wake/search 不泄漏 raw/audit/provisional"],
  ["distill_audit_summaries", "语义 audit summary 持久化"],
  ["durable_memory_retrieval", "写入后的长期知识经 intended 检索路径可读"],
];

const CONTRACT_GATES: string[][] = [
  ["MCP 27-tool surface", "test_mcp_public_surface_contract.py · ensure_mcps_canonical.py"],
  ["Host replay / Hook", "test_host_replay_qualification.py · 各宿主 fixture"],
  ["Evidence admission", "test_evidence_admission.py"],
  ["Assimilation / truth", "test_assimilation_runtime.py · test_assimilation_shadow.py"],
  ["Clean retrieval", "test_clean_retrieval_outcome.py · test_user_facing_memory_flow_contract.py"],
  ["Dream / Review", "test_dream_maintenance_contract.py"],
  ["Distill lossless", "test_lossless_distill_mcp.py · test_transcript_evidence.py"],
  ["用户结果合同", "code/tools/outcome-verifier · .codex/outcomes.json"],
];

const SCOPE_LEDGER: string[][] = [
  ["Golden CI + fixture expansion", "shipped", "0.9.0 · defer.md"],
  ["Admission runtime metadata", "deferred", "Skills + govern_memory 已覆盖 admission"],
  ["RRF / adaptive IDF", "deferred", "需 golden-suite 可测改进"],
  ["Shared-container per-session 删除", "deferred", "Hermes/OpenCode/Antigravity replay 未齐"],
  ["Rust zero-copy", "deferred", "无 hotspot 证明"],
  ["历史会话 distill backlog", "in_progress", "运营吞吐 · maturity-model 标注非发布阻塞"],
  ["外部 web/API 来源重验", "deferred", "next-iteration-directions.md · 非交付承诺"],
];

const TEN_TO_SIX: string[][] = [
  ["① Wake", "L1 记忆闭环"],
  ["② 存储", "L3 索引 + L4 ledger + SQLite authority"],
  ["③ 检索", "L3 检索与召回"],
  ["④ Truth", "L2 真理与治理"],
  ["⑤ MCP", "L5 + L6"],
  ["⑥ 时序", "L1/L3 子能力"],
  ["⑦ Wiki", "Scope · out_of_product"],
  ["⑧ 成本", "Claim boundary"],
  ["⑨ 维护", "L1 dream + L4"],
  ["⑩ 证据", "L6 + 实际结果检查 + 契约测试"],
];

const CLAIM_BOUNDARY = [
  "公开文档不写 PyPI 为 canonical 通道（GitHub Releases only）",
  "不宣称全局 cost-savings（cost_budget 仅 advisory）",
  "retrieval_profile=quality alone 不解锁 broad memory answer quality",
  "无 wiki-as-truth 或第二 truth store 叙事",
  "无静默 durable write（须逐点验证 + assimilation / review 路径）",
  "completed / queued 字段本身不是用户结果证据",
  "mock 通过或配置存在不能替代实际运行检查",
];

const RETIRED_NARRATIVES = [
  "无 rubric、无证据列的旧十维/峰值雷达",
  "v5.x「31 accepted runs」类 maintainer 公开叙事",
  "旧 canvas 完成度百分比估算",
  "把单机 distill backlog 与仓库发布成熟度混成一个 headline 分",
];

/** 产品形态对比：摘自 docs/reference-projects/*.md，不是功能打分 */
const PRODUCT_SHAPE: string[][] = [
  ["定位", "local-first Agent memory backend", "coding agent observation / generation server", "distributed memory API + worker", "embeddable memory SDK", "temporal knowledge graph library"],
  ["Truth authority", "SQLite knowledge_entries", "Postgres canonical + SQLite legacy session path", "API/backend durable store", "vector store 为主 · SQLite history 审计", "graph edges · valid/expired_at 生命周期"],
  ["无人值守语义", "Dream（Hook · enabled + 宿主 CLI Agent）", "BullMQ generation worker", "DB queue poller workers", "无 · 调用方驱动 SDK", "LLM 驱动图谱写入"],
  ["任务/队列模型", "SQLite distill job · chunk lease · receipt", "transactional outbox · post-commit queue", "FOR UPDATE SKIP LOCKED · slot pool", "同步 API · 无持久队列", "图数据库事务 · 非 outbox"],
  ["Agent 日常面", "27 MCP tools · 7 host /hm:*", "HTTP compat · hook/server-beta", "REST API 客户端", "Python/TS SDK embed", "Python library · 非 Agent MCP 产品"],
  ["Graph / 外部 broker", "明确不做（defer / maturity-model）", "Redis/BullMQ · Postgres", "Postgres/Oracle 等多后端", "多 vector provider", "Neo4j/FalkorDB 等"],
  ["分发", "GitHub Releases wheel · 无 PyPI", "npm / server 部署", "服务化部署", "PyPI SDK", "库集成"],
  ["harness-mem 关系", "当前产品", "可靠性参考 · 非目标架构", "worker/lease 参考 · 非目标架构", "scoped deletion 参考 · 非 distill 蓝图", "时序检索参考 · 非 storage engine"],
];

/** adopt / adapt / reject：各项目页结论摘要 · docs/reference-projects/ */
const REFERENCE_AAR: string[][] = [
  ["claude-mem", "持久任务状态是事实；transport 失败可恢复", "outbox → SQLite distill_jobs / checkpoint", "Redis/BullMQ · 常驻第二 worker · broker 状态当审计", "reference-projects/claude-mem.md"],
  ["Hindsight", "claim/lease/recover · 任务级 timeout · 迁移安全", "映射到现有 SQLite lease/backoff/receipt", "分布式 poller · 第二 scheduler · 多 DB 后端", "reference-projects/hindsight.md"],
  ["Mem0", "scoped · paginated deletion · 重复页检测", "用于 privacy erase / source cleanup 计划", "vector+SQLite 包装成原子删除 · 局部失败仍报 success", "reference-projects/mem0.md"],
  ["Graphiti", "valid/expired 过滤 · 分层检索 · 查询形状测试", "as-of / exclusion 语义（roadmap 0.9.7）", "图数据库 · LLM 图谱写入作 harness-mem storage", "reference-projects/graphiti.md"],
  ["Letta", "（无直接 adopt）", "wake/distill 诊断加 context_budget / compaction_outcome", "Letta agent runtime · cloud archival · block 作 truth", "reference-projects/letta.md"],
  ["sqlite-vec", "vec 表 membership/dimension 不变量", "optional FTS/vec 重建 · 非 truth", "vec 索引反向成为 authority", "reference-projects/sqlite-vec.md"],
  ["PrecisionMemBench / MemoryData / LongMemEval", "retrieval-isolated fixture · per-query 工件 · abstention 分列", "离线 golden / replay（非 release 依赖 LLM judge）", "外部 judge 作 release gate · oracle 当产品质量", "reference-projects/evidence-to-roadmap.md"],
];

const REFERENCE_CATALOG: string[][] = [
  ["claude-mem", "product/reliability", "outbox · queue recovery · health lifecycle"],
  ["Hindsight", "product/reliability", "leases · worker recovery · migration"],
  ["Mem0", "product/lifecycle", "scoped deletion · history · provider 边界"],
  ["Graphiti", "retrieval/temporal", "validity intervals · relation search"],
  ["sqlite-vec", "integration/index", "local vector invariants"],
  ["Letta", "research/product", "context budget · archival 边界（非 runtime）"],
  ["Pi", "host/session", "append-aware context · branch lineage"],
  ["BEAM / LoCoMo / LongMemEval / MemoryData", "evaluation", "fixture · adapter contract · 指标分列"],
];

/** 仍待吸收的参考教训（evidence-to-roadmap · 非「我们不如对方 x 分」） */
const OPEN_GAPS_FROM_REFS: string[][] = [
  ["Job 级 reconciliation / soak 报告", "Hindsight · claude-mem", "chunk lease 已有 · job 级仍 incomplete"],
  ["Host adapter 真实 replay 矩阵", "claude-mem · BEAM · Mem0", "test_host_replay_qualification 持续扩展"],
  ["Derived index generation 原子发布", "sqlite-vec · Tantivy", "generation-safe 部分已有 · 0.9.8 方向"],
  ["Independent long-session fixtures", "MemoryData · LoCoMo · LongMemEval", "60-case replay 已有 · 多样性仍 gap"],
  ["RRF / adaptive IDF 可测改进", "Graphiti · vstash（paper）", "defer.md · 需 golden-suite 证明"],
];

/** 本机 outcome-verifier 实测（2026-08-31 · harness-mem 仓库）— 比百分制分更优先 */
const OUTCOME_RUN_AT = "2026-08-31T03:14+08:00";
const OUTCOME_RUN_STATUS = "passed";
const OUTCOME_PASSED = 14;
const OUTCOME_FAILED = 0;

const OUTCOME_LIVE: string[][] = [
  ["codex_cleanup_liveness", "passed", "—"],
  ["archive_distill_batch_outcome", "passed", "—"],
  ["codex_hook_lifecycle", "passed", "—"],
  ["dream_execution", "passed", "—"],
  ["distill_user_artifacts", "passed", "—"],
  ["autonomous_distill_completion", "passed", "—"],
  ["autonomous_note_materialization", "passed", "—"],
  ["autonomous_provider_isolation", "passed", "provider.name=codex_cli"],
  ["partial_distill_handoff", "passed", "—"],
  ["distill_acceptance_matrix", "passed", "—"],
  ["multi_point_memory_assimilation", "passed", "—"],
  ["clean_retrieval_boundary", "passed", "—"],
  ["distill_audit_summaries", "passed", "—"],
  ["durable_memory_retrieval", "passed", "—"],
];

type VerifyTier = "verified_local" | "partial_local" | "failed_local" | "contract_only" | "documented_gap";

const TIER_LABEL: Record<VerifyTier, string> = {
  verified_local: "本机检查已通过",
  partial_local: "本机部分通过 / 有 defer",
  failed_local: "本机检查未通过",
  contract_only: "仅有仓库契约 · 本会话未跑",
  documented_gap: "文档登记 gap · 无探针",
};

const DIMENSION_VERIFICATION: {
  code: string;
  label: string;
  weight: number | null;
  tier: VerifyTier;
  mappedOutcomes: string;
  contracts: string;
  note: string;
}[] = [
  {
    code: "L1",
    label: "记忆闭环",
    weight: 20,
    tier: "verified_local",
    mappedOutcomes: "PASS: distill_user_artifacts · dream · acceptance_matrix · partial_handoff · hook · autonomous_distill",
    contracts: "27-tool MCP · 7 /hm:*（未在本会话跑 pytest）",
    note: "本机 L1 对应检查全 PASS",
  },
  {
    code: "L2",
    label: "真理与治理",
    weight: 25,
    tier: "verified_local",
    mappedOutcomes: "PASS: multi_point_assimilation · clean_retrieval · archive_distill（含 sqlite authority 探针）",
    contracts: "test_assimilation_runtime · test_evidence_admission（未跑）",
    note: "本机没有失败的 truth 类检查；Dream undo 靠发布说明和单测，不在本次 14 项检查内",
  },
  {
    code: "L3",
    label: "检索与召回",
    weight: 15,
    tier: "verified_local",
    mappedOutcomes: "PASS: clean_retrieval_boundary · durable_memory_retrieval",
    contracts: "test_clean_retrieval_outcome · RRF deferred（defer.md）",
    note: "本机两项目检索检查均 PASS；live used/ignored 反馈仍少（maturity-model）",
  },
  {
    code: "L4",
    label: "证据与蒸馏",
    weight: 20,
    tier: "verified_local",
    mappedOutcomes: "PASS: archive_distill · acceptance_matrix · distill_user_artifacts · partial_handoff · audit_summaries",
    contracts: "test_lossless_distill_mcp · host replay（未跑）",
    note: "蒸馏主链本机检查全 PASS",
  },
  {
    code: "L5",
    label: "宿主集成",
    weight: 15,
    tier: "verified_local",
    mappedOutcomes: "PASS: codex_hook_lifecycle · autonomous_distill · autonomous_provider · autonomous_note",
    contracts: "test_host_replay_qualification（未跑）",
    note: "本机 hook+autonomous 四 claim 全 PASS（2026-08-26 合同对齐后）",
  },
  {
    code: "L6",
    label: "运维与发布",
    weight: 5,
    tier: "partial_local",
    mappedOutcomes: "（无直接实际结果检查）",
    contracts: "mcp/version pytest 已跑 · ensure_mcps OK",
    note: "契约项已跑通；public-smoke 未在本会话跑",
  },
  {
    code: "D7",
    label: "任务可靠性",
    weight: null,
    tier: "documented_gap",
    mappedOutcomes: "（无专用实际结果检查）",
    contracts: "chunk lease/backoff 已实现 · evidence-to-roadmap：job reconciliation incomplete",
    note: "不对参考项目打数字分；Hindsight/claude-mem 仅 adopt/adapt 来源",
  },
  {
    code: "D8",
    label: "删除与隐私",
    weight: null,
    tier: "partial_local",
    mappedOutcomes: "PASS: codex_cleanup_liveness",
    contracts: "shared-container per-session deletion deferred（defer.md）",
    note: "本机 cleanup liveness 已证；Hermes/OpenCode/Antigravity 共享容器仍 unsupported",
  },
];

/** docs/maturity-model.md § Mechanical score rubric — 每轨检查项满分 100，分数 = Σ(通过项 points) */
const SCORE_BANDS: string[][] = [
  ["90–100", "该轨对应检查全 PASS，且本会话已跑契约项亦 PASS"],
  ["80–89", "核心检查 PASS；仅次要 defer 或未跑契约扣分"],
  ["60–79", "主链部分 PASS；至少 1 条关键检查 FAIL"],
  ["40–59", "关键路径 FAIL 占 mapped 权重多数"],
  ["0–39", "该轨对应检查基本未证或 host/autonomous 全 FAIL"],
];

type CheckKind = "outcome" | "fact" | "contract" | "defer_cap";

type ScoreCheck = {
  id: string;
  label: string;
  points: number;
  kind: CheckKind;
  probe: string;
};

const OUTCOME_STATUS: Record<string, "passed" | "failed"> = Object.fromEntries(
  OUTCOME_LIVE.map(([id, status]) => [id, status as "passed" | "failed"]),
);

/** 本 canvas 会话内已核对静态事实（pyproject / pytest --collect-only） */
const FACT_VERIFIED: Record<string, boolean> = {
  runtime_version: true,
  pytest_collected: true,
  mcp_tool_count: true,
};

/** 契约测试本会话未跑 → 0 分；跑过后改 passed/failed 并重算 */
const CONTRACT_STATUS: Record<string, "passed" | "failed" | "not_run"> = {
  mcp_public_surface: "passed",
  version_alignment: "passed",
  ensure_mcps_canonical: "passed",
  host_replay_qualification: "not_run",
};

const TRACK_SCORE_CHECKS: Record<string, ScoreCheck[]> = {
  L1: [
    { id: "l1_distill_artifacts", label: "distill_user_artifacts", points: 15, kind: "outcome", probe: "distill_user_artifacts" },
    { id: "l1_dream", label: "dream_execution", points: 15, kind: "outcome", probe: "dream_execution" },
    { id: "l1_partial", label: "partial_distill_handoff", points: 10, kind: "outcome", probe: "partial_distill_handoff" },
    { id: "l1_matrix", label: "distill_acceptance_matrix", points: 10, kind: "outcome", probe: "distill_acceptance_matrix" },
    { id: "l1_hook", label: "codex_hook_lifecycle", points: 25, kind: "outcome", probe: "codex_hook_lifecycle" },
    { id: "l1_auto_distill", label: "autonomous_distill_completion", points: 25, kind: "outcome", probe: "autonomous_distill_completion" },
  ],
  L2: [
    { id: "l2_assim", label: "multi_point_memory_assimilation", points: 35, kind: "outcome", probe: "multi_point_memory_assimilation" },
    { id: "l2_clean", label: "clean_retrieval_boundary", points: 30, kind: "outcome", probe: "clean_retrieval_boundary" },
    { id: "l2_archive", label: "archive_distill_batch", points: 35, kind: "outcome", probe: "archive_distill_batch_outcome" },
  ],
  L3: [
    { id: "l3_clean", label: "clean_retrieval_boundary", points: 50, kind: "outcome", probe: "clean_retrieval_boundary" },
    { id: "l3_durable", label: "durable_memory_retrieval", points: 50, kind: "outcome", probe: "durable_memory_retrieval" },
  ],
  L4: [
    { id: "l4_archive", label: "archive_distill_batch", points: 20, kind: "outcome", probe: "archive_distill_batch_outcome" },
    { id: "l4_matrix", label: "distill_acceptance_matrix", points: 20, kind: "outcome", probe: "distill_acceptance_matrix" },
    { id: "l4_artifacts", label: "distill_user_artifacts", points: 20, kind: "outcome", probe: "distill_user_artifacts" },
    { id: "l4_partial", label: "partial_distill_handoff", points: 15, kind: "outcome", probe: "partial_distill_handoff" },
    { id: "l4_audit", label: "distill_audit_summaries", points: 25, kind: "outcome", probe: "distill_audit_summaries" },
  ],
  L5: [
    { id: "l5_hook", label: "codex_hook_lifecycle", points: 35, kind: "outcome", probe: "codex_hook_lifecycle" },
    { id: "l5_auto_distill", label: "autonomous_distill_completion", points: 25, kind: "outcome", probe: "autonomous_distill_completion" },
    { id: "l5_provider", label: "autonomous_provider_isolation", points: 25, kind: "outcome", probe: "autonomous_provider_isolation" },
    { id: "l5_auto_note", label: "autonomous_note_materialization", points: 15, kind: "outcome", probe: "autonomous_note_materialization" },
  ],
  L6: [
    { id: "l6_version", label: "fact runtime_version aligned", points: 20, kind: "fact", probe: "runtime_version" },
    { id: "l6_pytest", label: "fact pytest collected count", points: 15, kind: "fact", probe: "pytest_collected" },
    { id: "l6_mcp", label: "contract test_mcp_public_surface_contract", points: 25, kind: "contract", probe: "mcp_public_surface" },
    { id: "l6_align", label: "contract test_version_alignment", points: 20, kind: "contract", probe: "version_alignment" },
    { id: "l6_mcps", label: "contract ensure_mcps_canonical", points: 20, kind: "contract", probe: "ensure_mcps_canonical" },
  ],
  D7: [
    { id: "d7_lease", label: "doc/code chunk lease · backoff · receipt", points: 55, kind: "fact", probe: "d7_lease_implemented" },
    { id: "d7_recon", label: "defer job reconciliation / soak", points: 45, kind: "defer_cap", probe: "d7_reconciliation_open" },
  ],
  D8: [
    { id: "d8_cleanup", label: "codex_cleanup_liveness", points: 70, kind: "outcome", probe: "codex_cleanup_liveness" },
    { id: "d8_shared", label: "defer shared-container per-session deletion", points: 30, kind: "defer_cap", probe: "d8_shared_container_deferred" },
  ],
};

FACT_VERIFIED.d7_lease_implemented = true;

type ResolvedCheck = { check: ScoreCheck; earned: number; status: string };

function resolveCheck(check: ScoreCheck): ResolvedCheck {
  if (check.kind === "outcome") {
    const s = OUTCOME_STATUS[check.probe];
    if (s === "passed") return { check, earned: check.points, status: "passed" };
    if (s === "failed") return { check, earned: 0, status: "failed" };
    return { check, earned: 0, status: "missing" };
  }
  if (check.kind === "fact") {
    const ok = FACT_VERIFIED[check.probe] === true;
    return { check, earned: ok ? check.points : 0, status: ok ? "verified" : "unverified" };
  }
  if (check.kind === "contract") {
    const s = CONTRACT_STATUS[check.probe];
    if (s === "passed") return { check, earned: check.points, status: "passed" };
    if (s === "failed") return { check, earned: 0, status: "failed" };
    return { check, earned: 0, status: "not_run" };
  }
  // defer_cap: open gap → 该项 earned=0（从满分中扣除）
  const open =
    (check.probe === "d7_reconciliation_open" && true) ||
    (check.probe === "d8_shared_container_deferred" && true);
  return { check, earned: open ? 0 : check.points, status: open ? "open_gap" : "closed" };
}

function scoreTrack(code: string): { score: number; resolved: ResolvedCheck[] } {
  const checks = TRACK_SCORE_CHECKS[code] ?? [];
  const resolved = checks.map(resolveCheck);
  const score = resolved.reduce((sum, r) => sum + r.earned, 0);
  return { score, resolved };
}

const TRACK_WEIGHTS: Record<string, number | null> = {
  L1: 20,
  L2: 25,
  L3: 15,
  L4: 20,
  L5: 15,
  L6: 5,
  D7: null,
  D8: null,
};

const TRACK_LABELS: Record<string, string> = {
  L1: "记忆闭环",
  L2: "真理与治理",
  L3: "检索与召回",
  L4: "证据与蒸馏",
  L5: "宿主集成",
  L6: "运维与发布",
  D7: "任务可靠性",
  D8: "删除与隐私",
};

const SCORED_TRACKS = ["L1", "L2", "L3", "L4", "L5", "L6", "D7", "D8"] as const;

const TRACK_SCORES = SCORED_TRACKS.map((code) => {
  const { score, resolved } = scoreTrack(code);
  return { code, label: TRACK_LABELS[code], weight: TRACK_WEIGHTS[code], score, resolved };
});

const WEIGHTED_TRACKS = TRACK_SCORES.filter((t) => t.weight !== null);
const HM_WEIGHTED_L6 = Math.round(
  WEIGHTED_TRACKS.reduce((sum, t) => sum + ((t.weight ?? 0) / 100) * t.score, 0),
);

const HM_BOTTLENECK = WEIGHTED_TRACKS.reduce((min, t) => (t.score < min.score ? t : min), WEIGHTED_TRACKS[0]);

const SCORE_CHECK_ROWS: string[][] = TRACK_SCORES.flatMap((t) =>
  t.resolved.map((r) => [
    t.code,
    r.check.label,
    String(r.check.points),
    String(r.earned),
    r.status,
  ]),
);

const LEGACY_TEN_TO_DIM: string[][] = [
  ["① Wake", "L1"],
  ["② 存储", "L3 + L4 + SQLite"],
  ["③ 检索", "L3"],
  ["④ Truth", "L2"],
  ["⑤ MCP", "L5 + L6"],
  ["⑥ 时序", "L3 + Graphiti 参考"],
  ["⑦ Wiki", "out_of_product"],
  ["⑧ 成本", "Claim boundary"],
  ["⑨ 维护", "L1 + L4 + D7"],
  ["⑩ 证据", "L6 + 实际结果检查"],
];

/** 发布叙事 vs 本机实测行 */
function releaseVsLocalRows(): string[][] {
  return [
    ["roadmap.md 发布记录", "frozen oracle + Desktop Hook + 14/14 实际结果检查通过", "仓库记录 · 非本机实时"],
    ["本机实际结果检查", `${OUTCOME_PASSED}/${OUTCOME_CLAIM_COUNT} passed · overall ${OUTCOME_RUN_STATUS}`, OUTCOME_RUN_AT],
    ["本机机械分（rubric）", `L1–L6 加权 ${HM_WEIGHTED_L6}/100 · Σ(weight×track_score)`, "可复算 · 见检查项表"],
    ["参考项目", "形态/adopt 对照 · 不共享本项目检查", "不打竞品综合分"],
  ];
}

function tierPill(tier: VerifyTier) {
  if (tier === "verified_local") return <Pill tone="success">{TIER_LABEL[tier]}</Pill>;
  if (tier === "partial_local") return <Pill tone="warning">{TIER_LABEL[tier]}</Pill>;
  if (tier === "failed_local") return <Pill tone="warning">{TIER_LABEL[tier]}</Pill>;
  if (tier === "contract_only") return <Pill tone="info">{TIER_LABEL[tier]}</Pill>;
  return <Pill tone="neutral">{TIER_LABEL[tier]}</Pill>;
}

function outcomePill(status: string) {
  if (status === "passed") return <Pill tone="success">passed</Pill>;
  return <Pill tone="warning">failed</Pill>;
}

function StorageDiagram() {
  const theme = useHostTheme();
  const box = (x: number, y: number, w: number, h: number, fill: string, title: string, sub: string) => (
    <g key={`${x}-${title}`}>
      <rect x={x} y={y} width={w} height={h} rx={6} fill={fill} stroke={theme.stroke.secondary} strokeWidth={1} />
      <text x={x + w / 2} y={y + 22} textAnchor="middle" fill={theme.text.primary} fontSize={11} fontWeight={600}>
        {title}
      </text>
      <text x={x + w / 2} y={y + 38} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        {sub}
      </text>
    </g>
  );

  return (
    <svg viewBox="0 0 720 200" width="100%" height="auto" role="img" aria-label="存储角色">
      <defs>
        <marker id="conv-store-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.stroke.primary} />
        </marker>
      </defs>
      {box(20, 20, 160, 56, theme.fill.tertiary, "Transcript ledger", "证据 authority")}
      {box(200, 20, 160, 56, theme.fill.quaternary, "Job workspace", "临时 processing")}
      {box(380, 20, 160, 56, theme.fill.secondary, "knowledge_entries", "当前知识 authority")}
      {box(560, 20, 140, 56, theme.fill.tertiary, "Derived index", "FTS · vec · MD")}
      <line x1={180} y1={48} x2={200} y2={48} stroke={theme.stroke.primary} markerEnd="url(#conv-store-arrow)" />
      <line x1={360} y1={48} x2={380} y2={48} stroke={theme.stroke.primary} markerEnd="url(#conv-store-arrow)" />
      <line x1={540} y1={48} x2={560} y2={48} stroke={theme.stroke.primary} strokeDasharray="4 3" markerEnd="url(#conv-store-arrow)" />
      <text x={360} y={110} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        来源：roadmap.md · AGENTS.md · memory-adoption.md
      </text>
      <text x={360} y={128} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        Observation / transcript = 证据 · normal wake/search = 当前 governed truth only
      </text>
    </svg>
  );
}

export default function HarnessMemConvergenceCanvas() {
  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 1040, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>产品边界与收敛证据</H1>
          <Pill tone="info">source {RUNTIME_VERSION}</Pill>
          <Pill tone="success">public {PUBLIC_RELEASE_VERSION}</Pill>
          <Pill tone="info">仅可核对事实</Pill>
        </Row>
        <Text tone="secondary">
          核对 {AS_OF} · 数据源 AGENTS.md · roadmap.md · defer.md · maturity-model.md · .codex/outcomes.json · pyproject.toml
        </Text>
      </Stack>

      <Callout tone="info">
        数字分有标准：每轨 100 分 = 下方固定检查项之和；实际结果读取本机检查，契约项本会话未跑记 0 分，defer 项 open 则该项 0 分。
        规范见 docs/maturity-model.md § Mechanical score rubric。加权 {HM_WEIGHTED_L6}/100 · 最低轨 {HM_BOTTLENECK.code}（{HM_BOTTLENECK.score}）。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="源码版本" value={RUNTIME_VERSION} tone="info" />
        <Stat label="本机检查" value={`${OUTCOME_PASSED}/${OUTCOME_CLAIM_COUNT}`} tone="success" />
        <Stat label="L1–L6 加权分" value={String(HM_WEIGHTED_L6)} tone="success" />
        <Stat label="最低轨" value={`${HM_BOTTLENECK.code} ${HM_BOTTLENECK.score}`} tone="info" />
      </Grid>

      <Stack gap={6}>
        <H2>本机实际结果检查</H2>
        <Text tone="tertiary" size="small">
          命令：python code/tools/outcome-verifier/scripts/verify_outcomes.py --config .codex/outcomes.json · 报告 .tmp/outcome-verifier/harness-mem-report.json
        </Text>
      </Stack>

      <Table
        headers={["claim", "本机状态", "失败字段（若有）"]}
        rows={OUTCOME_LIVE.map((r) => [r[0], outcomePill(r[1]), r[2]])}
        striped
      />

      <Card>
        <CardHeader>发布叙事 vs 本机实测</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table headers={["视角", "陈述", "可信度"]} rows={releaseVsLocalRows()} />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>机械评分（L1–L6 + D7/D8）</H2>
        <Text tone="tertiary" size="small">
          公式：track_score = Σ earned_points · 数据源 {OUTCOME_RUN_AT} · 本机检查 {OUTCOME_PASSED}/{OUTCOME_CLAIM_COUNT} passed
        </Text>
      </Stack>

      <Card>
        <CardHeader>分值带 rubric（docs/maturity-model.md）</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table headers={["分值带", "定义"]} rows={SCORE_BANDS} framed={false} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>轨道得分 · harness-mem 本机</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["轨", "权重", "分", "档位（摘要）"]}
            rows={TRACK_SCORES.map((t) => {
              const dim = DIMENSION_VERIFICATION.find((d) => d.code === t.code);
              return [
                `${t.code} ${t.label}`,
                t.weight === null ? "—" : `${t.weight}%`,
                String(t.score),
                dim ? tierPill(dim.tier) : "—",
              ];
            })}
            striped
          />
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <BarChart
            horizontal
            height={280}
            categories={WEIGHTED_TRACKS.map((t) => `${t.code} ${t.label}`)}
            series={[{ name: "harness-mem 本机", data: WEIGHTED_TRACKS.map((t) => t.score), tone: "info" }]}
            yMin={0}
            yMax={100}
            referenceLines={[{ value: 80, label: "可用门槛 80", tone: "success" }]}
          />
          <Text tone="tertiary" size="small">
            纵轴：rubric 分 0–100 · 横轴：L1–L6 · 数据源：本机实际结果检查 + 静态事实 · 契约项未跑=0
          </Text>
          <Divider />
          <UsageBar
            total={100}
            topLeftLabel="加权贡献 weight×score"
            topRightLabel={String(HM_WEIGHTED_L6)}
            segments={WEIGHTED_TRACKS.map((t, i) => ({
              id: t.code,
              value: Math.round(((t.weight ?? 0) / 100) * t.score * 10) / 10,
              color: (["green", "blue", "purple", "orange", "yellow", "pink"] as const)[i],
            }))}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>检查项明细（可复算）</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["轨", "检查项", "满分", "得分", "状态"]}
            rows={SCORE_CHECK_ROWS}
            striped
          />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>八维档位摘要</H2>

      <Table
        headers={["维", "权重", "分", "本机档位", "对应检查", "说明"]}
        rows={DIMENSION_VERIFICATION.map((d) => {
          const scored = TRACK_SCORES.find((t) => t.code === d.code);
          return [
            `${d.code} ${d.label}`,
            d.weight === null ? "—" : `${d.weight}%`,
            scored ? String(scored.score) : "—",
            tierPill(d.tier),
            d.mappedOutcomes,
            d.note,
          ];
        })}
        striped
      />

      <Card>
        <CardHeader>档位定义</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["档位", "含义"]}
            rows={(Object.keys(TIER_LABEL) as VerifyTier[]).map((k) => [TIER_LABEL[k], k])}
            framed={false}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>旧十维 → 现八维</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table headers={["旧十维", "现维度"]} rows={LEGACY_TEN_TO_DIM} framed={false} />
        </CardBody>
      </Card>

      </Stack>

      <Stack gap={6}>
        <H2>外部产品对比（reference-projects · 无数字分）</H2>
        <Text tone="tertiary" size="small">
          真值索引 docs/reference-projects/index.md · 决策推导 evidence-to-roadmap.md · 复核基线 2026-08-02
        </Text>
      </Stack>

      <Callout tone="info">
        读法：其他项目是「借 invariant / fixture / failure 语义」，不是「抄 server / graph / broker 架构」。
        没有 adopt 的维度通常表示 deliberate 边界，不应读成「功能落后 x 分」。
      </Callout>

      <Card>
        <CardHeader>产品形态（事实对照 · 非评分）</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["维度", "harness-mem", "claude-mem", "Hindsight", "Mem0", "Graphiti"]}
            rows={PRODUCT_SHAPE}
            columnAlign={["left", "left", "left", "left", "left", "left"]}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>参考目录（当前跟踪集）</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table headers={["项目", "角色", "我们读什么"]} rows={REFERENCE_CATALOG} striped />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>adopt / adapt / reject 摘要</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["参考项目", "Adopt", "Adapt", "Reject", "页面"]}
            rows={REFERENCE_AAR}
            columnAlign={["left", "left", "left", "left", "left"]}
          />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H3>仍开放的参考差距（roadmap 输入）</H3>
        <Text tone="tertiary" size="small">来自 evidence-to-roadmap.md · 描述 harness-mem 还要补什么验证/契约，不是竞品分数</Text>
      </Stack>
      <Table headers={["差距", "主要参考", "仓库状态/方向"]} rows={OPEN_GAPS_FROM_REFS} striped />

      <Stack gap={6}>
        <H2>五模块功能架构（当前合同）</H2>
        <Text tone="tertiary" size="small">Review + Dream 是跨模块 3–4 的治理反馈，不是第六产品模块</Text>
      </Stack>
      <Table
        headers={["模块", "处理单位", "负责", "不负责"]}
        rows={MODULES}
        columnAlign={["left", "left", "left", "left"]}
        striped
      />

      <Stack gap={6}>
        <H2>存储与真值边界</H2>
      </Stack>
      <Card>
        <CardBody>
          <StorageDiagram />
          <Divider />
          <Table headers={["层", "角色", "仓库事实"]} rows={STORAGE_ROLES} framed={false} />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>执行入口（0.9.26 列车）</H2>
      </Stack>
      <Table headers={["入口", "谁编排", "合同要点"]} rows={EXECUTION_PATHS} striped />

      <Stack gap={6}>
        <H2>发布列车（已发布切片）</H2>
        <Text tone="tertiary" size="small">0.9.16–0.9.19 已折叠进 0.9.20 · 详见 roadmap.md 完整表</Text>
      </Stack>
      <Table headers={["版本", "主要变更", "状态"]} rows={RELEASE_TRAIN} striped />

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader>主动 out_of_product</CardHeader>
          <CardBody style={{ padding: 0 }}>
            <Table headers={["项", "状态", "依据"]} rows={OUT_OF_PRODUCT} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>Scope Ledger（defer.md + 运营面）</CardHeader>
          <CardBody style={{ padding: 0 }}>
            <Table headers={["项", "状态", "备注"]} rows={SCOPE_LEDGER} />
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={6}>
        <H2>14-claim 用户结果合同</H2>
        <Text tone="tertiary" size="small">.codex/outcomes.json · 必须实际运行检查，不能由单元测试单独替代</Text>
      </Stack>
      <Table headers={["claim id", "描述（摘要）"]} rows={OUTCOME_CLAIMS} striped />

      <Stack gap={6}>
        <H2>仓库契约测试门禁</H2>
        <Text tone="tertiary" size="small">AGENTS.md 定向验证表 · 通过只证明其声明范围</Text>
      </Stack>
      <Table headers={["范围", "最小相关测试 / 工具"]} rows={CONTRACT_GATES} striped />

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader>Claim boundary（maturity-model Layer 3）</CardHeader>
          <CardBody>
            <Stack gap={10}>
              {CLAIM_BOUNDARY.map((label) => (
                <Checkbox key={label} checked disabled label={label} />
              ))}
            </Stack>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>已废弃的叙事方式</CardHeader>
          <CardBody>
            <Stack gap={8}>
              {RETIRED_NARRATIVES.map((item) => (
                <Text key={item} tone="secondary" size="small">
                  · {item}
                </Text>
              ))}
            </Stack>
            <Divider />
            <Text tone="tertiary" size="small">
              现用八维 + rubric；十维 → 六轨/八维映射见上文
            </Text>
            <Table headers={["旧十维", "新归属（readiness）"]} rows={TEN_TO_SIX} framed={false} />
          </CardBody>
        </Card>
      </Grid>

      <Callout tone="info">
        相关面板：readiness-v3.canvas.tsx（六轨 Readiness + 权重分，须带轨道 breakdown）·
        docs/canvases/harness-mem-readiness-v1.canvas.tsx（0.9.26 精简架构边界，与 test_package_version_alignment 对齐）。
      </Callout>

        <Text tone="tertiary" size="small">
          验证：pytest --collect-only（{PYTEST_COUNT}）· outcome-verifier · 参考项目页本地 HEAD 见 index.md
        </Text>
    </Stack>
  );
}
