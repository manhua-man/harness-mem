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
  TodoListCard,
  UsageBar,
  useHostTheme,
} from "cursor/canvas";

const MODEL_VERSION = "v1";
const AS_OF = "2026-08-12";
const RUNTIME_VERSION = "0.9.12";
const PYTEST_PASSED = 736;
const PYTEST_SKIPPED = 2;
const PYTEST_COUNT = PYTEST_PASSED + PYTEST_SKIPPED;

type TrackId = "l1" | "l2" | "l3" | "l4" | "l5" | "l6";

type ReadinessTrack = {
  id: TrackId;
  code: string;
  label: string;
  weight: number;
  score: number;
  tone: "success" | "warning" | "info";
  acceptance: string;
  signals: string;
  evidence: string;
};

const READINESS_TRACKS: ReadinessTrack[] = [
  {
    id: "l1",
    code: "L1",
    label: "记忆闭环",
    weight: 20,
    score: 96,
    tone: "success",
    acceptance: "wake → search → distill → review → dream 端到端可跑",
    signals: "guided-flow contract · 7 条 /hm:* Daily · phase=ready",
    evidence: "MCP public surface contract · daily slash 齐套",
  },
  {
    id: "l2",
    code: "L2",
    label: "真理与治理",
    weight: 25,
    score: 97,
    tone: "success",
    acceptance: "无静默改写 confirmed truth；候选 / 审计 / supersede 闭环",
    signals: "7 层 governance status · state audit ledger · finalize 语义终审",
    evidence: "0.8.8 auto-promote · 0.8.24 finalize 门禁测试",
  },
  {
    id: "l3",
    code: "L3",
    label: "检索与召回",
    weight: 15,
    score: 97,
    tone: "success",
    acceptance: "filter-first hybrid；vec0 KNN + batch cosine 回退",
    signals: "recall.steps 稳定 · 7 日 quality scorecard · abstention/exclusion",
    evidence: "60-case golden · 1k/10k scale · project-isolation fixtures",
  },
  {
    id: "l4",
    code: "L4",
    label: "证据与蒸馏",
    weight: 20,
    score: 99,
    tone: "success",
    acceptance: "无损转写账本 · 可恢复 chunk job · revision 幂等",
    signals: "exact offered-job claim · distinct cleanup/erase · migration receipts",
    evidence: "explicit migration rollback · native privacy lifecycle tests",
  },
  {
    id: "l5",
    code: "L5",
    label: "宿主集成",
    weight: 15,
    score: 99,
    tone: "success",
    acceptance: "hooks + MCP 入口 + install drift + per-host ingest",
    signals: "harness-mem-mcp · install_drift=无 · 七宿主全局命令",
    evidence: "integration_health 摘要 · cross-host transcript→wake contract",
  },
  {
    id: "l6",
    code: "L6",
    label: "运维与发布",
    weight: 5,
    score: 99,
    tone: "success",
    acceptance: "GitHub Release 通道 · doctor/CLI · MCP export CI",
    signals: "27 MCP tools · risk-classified Doctor · full Python/Rust gates",
    evidence: "public-smoke.yml · release-wheels 六目标 · Rust 6 tests",
  },
];

const WEIGHTED_READINESS = Math.round(
  READINESS_TRACKS.reduce((sum, t) => sum + (t.weight / 100) * t.score, 0),
);

type ScopeState = "shipped" | "in_progress" | "deferred" | "out_of_product";

type ScopeItem = {
  id: string;
  item: string;
  state: ScopeState;
  note: string;
};

const SCOPE_LEDGER: ScopeItem[] = [
  { id: "vec0", item: "vec0 KNN + scope-lock 0.8.15–18", state: "shipped", note: "batch cosine 仅回退" },
  { id: "gh-rel", item: "GitHub Releases 唯一包通道", state: "shipped", note: "0.8.23.3" },
  { id: "mcp-cmd", item: "harness-mem-mcp 安装入口", state: "shipped", note: "0.8.23.4" },
  { id: "lossless", item: "无损转写 + 可恢复蒸馏", state: "shipped", note: "0.8.24" },
  { id: "hosts-7", item: "7 host 转写适配器", state: "shipped", note: "含 Hermes / Antigravity" },
  { id: "hooks-boot", item: "status integration bootstrap", state: "shipped", note: "0.9.0" },
  { id: "distill-q", item: "Agent-active distill backlog diagnostics", state: "shipped", note: "0.9.3" },
  { id: "golden", item: "Golden CI + fixture 扩展", state: "shipped", note: "60 cases + scale gates" },
  { id: "admission", item: "confirm_* admission preflight", state: "deferred", note: "defer.md" },
  { id: "rrf", item: "RRF / adaptive IDF 调参", state: "deferred", note: "需 golden gate" },
  { id: "wiki", item: "M10 wiki bridge", state: "out_of_product", note: "主动删除" },
  { id: "pypi", item: "PyPI 发布", state: "out_of_product", note: "不计划" },
  { id: "graph", item: "Graph DB 默认路线", state: "out_of_product", note: "roadmap Later/Labs" },
];

const CLAIM_CHECKS = [
  { id: "c1", label: "公开文档不写 PyPI 为 canonical 通道", ok: true },
  { id: "c2", label: "不宣称全局 token / cost saving", ok: true },
  { id: "c3", label: "quality profile 不解锁 broad memory answer quality", ok: true },
  { id: "c4", label: "无 wiki-as-truth 或第二 truth store 叙事", ok: true },
  { id: "c5", label: "durable write 不经 review/finalize 门禁", ok: true },
  { id: "c6", label: "不默认宣称 graph / ANN / LanceDB 已启用", ok: true },
];

const LEGACY_MAP: string[][] = [
  ["① Wake", "L1 子能力"],
  ["② 存储", "L3 索引 + L4 ledger"],
  ["③ 检索", "L3"],
  ["④ Truth", "L2"],
  ["⑤ MCP", "L5 + L6"],
  ["⑥ 时序", "L1/L3 子能力"],
  ["⑦ Wiki", "Scope · out_of_product"],
  ["⑧ 成本", "Claim boundary"],
  ["⑨ 维护", "L1 dream + L4"],
  ["⑩ 证据", "L6 + 各轨契约测试"],
];

const BOTTLENECK = READINESS_TRACKS.reduce((min, t) => (t.score < min.score ? t : min), READINESS_TRACKS[0]);

function scopePill(state: ScopeState) {
  if (state === "shipped") return <Pill tone="success">shipped</Pill>;
  if (state === "in_progress") return <Pill tone="warning">in_progress</Pill>;
  if (state === "deferred") return <Pill tone="info">deferred</Pill>;
  return <Pill tone="neutral">out_of_product</Pill>;
}

function ArchitectureDiagram() {
  const theme = useHostTheme();
  const box = (x: number, y: number, w: number, h: number, fill: string, label: string, sub?: string) => (
    <g key={`${x}-${y}-${label}`}>
      <rect x={x} y={y} width={w} height={h} rx={6} fill={fill} stroke={theme.stroke.secondary} strokeWidth={1} />
      <text x={x + w / 2} y={y + (sub ? 22 : 28)} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>
        {label}
      </text>
      {sub ? (
        <text x={x + w / 2} y={y + 40} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
          {sub}
        </text>
      ) : null}
    </g>
  );
  const arrow = (x1: number, y1: number, x2: number, y2: number) => (
    <g key={`${x1}-${y1}-${x2}-${y2}`}>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={theme.stroke.primary} strokeWidth={1.5} markerEnd="url(#rdy-arch-arrow)" />
    </g>
  );

  return (
    <svg viewBox="0 0 720 400" width="100%" height="auto" role="img" aria-label="harness-mem v0.9.3 运行时架构">
      <defs>
        <marker id="rdy-arch-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.stroke.primary} />
        </marker>
      </defs>
      {box(20, 12, 680, 48, theme.fill.tertiary, "Agent 客户端 + /hm:* + 单一 MCP public surface", "status · wake · search · distill · review · dream")}
      {arrow(360, 60, 360, 78)}
      {box(
        20,
        78,
        680,
        48,
        theme.fill.secondary,
        "harness_mem Python 编排",
        "MCP handlers · guided flow · lossless distill · integration_health · CLI",
      )}
      {arrow(360, 126, 360, 144)}
      {box(20, 144, 160, 64, theme.fill.tertiary, "TruthStore", "confirmed memory / rules")}
      {box(195, 144, 160, 64, theme.fill.tertiary, "CandidateStore", "7 层 governance lifecycle")}
      {box(370, 144, 160, 64, theme.fill.secondary, "Transcript Ledger", "无损 revision · SHA-256")}
      {box(545, 144, 155, 64, theme.fill.tertiary, "DerivedIndex", "FTS · vec0 KNN · recall")}
      {arrow(100, 208, 100, 226)}
      {arrow(275, 208, 275, 226)}
      {arrow(450, 208, 450, 226)}
      {arrow(622, 208, 622, 226)}
      {box(20, 226, 330, 56, theme.fill.quaternary, "Canonical SQLite", "truth · candidates · jobs · ledger")}
      {box(370, 226, 330, 56, theme.fill.quaternary, "State Audit Ledger", "governance append-only")}
      {box(20, 296, 680, 48, theme.fill.tertiary, "Optional native acceleration (Rust PyO3)", "RRF · batch cosine · index fabric · Python fallback")}
      <text x={360} y={368} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        auto-promote → review 审计 · finalize 门禁 · supersede · 无静默改写 confirmed truth
      </text>
      <text x={360} y={384} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        transcript ledger 为权威证据 · observations 为检索投影
      </text>
    </svg>
  );
}

function CoreLoopDiagram() {
  const theme = useHostTheme();
  const nodes = [
    { x: 80, y: 60, label: "wake", sub: "项目简报" },
    { x: 240, y: 60, label: "search", sub: "recall + sources" },
    { x: 400, y: 60, label: "distill", sub: "无损 evidence → 候选" },
    { x: 560, y: 60, label: "review", sub: "审计收件箱" },
    { x: 680, y: 160, label: "dream", sub: "默认维护 · gated" },
  ];

  return (
    <svg viewBox="0 0 760 220" width="100%" height="auto" role="img" aria-label="v0.9.3 核心闭环">
      <defs>
        <marker id="rdy-loop-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
        </marker>
      </defs>
      {nodes.slice(0, 4).map((n) => (
        <g key={n.label}>
          <rect
            x={n.x - 58}
            y={n.y - 26}
            width={116}
            height={52}
            rx={8}
            fill={n.label === "distill" ? theme.fill.secondary : theme.fill.tertiary}
            stroke={theme.stroke.secondary}
            strokeWidth={1}
          />
          <text x={n.x} y={n.y - 2} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>
            {n.label}
          </text>
          <text x={n.x} y={n.y + 16} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
            {n.sub}
          </text>
        </g>
      ))}
      <line x1={138} y1={60} x2={182} y2={60} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#rdy-loop-arrow)" />
      <line x1={298} y1={60} x2={342} y2={60} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#rdy-loop-arrow)" />
      <line x1={458} y1={60} x2={502} y2={60} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#rdy-loop-arrow)" />
      <g>
        <rect
          x={622}
          y={134}
          width={116}
          height={52}
          rx={8}
          fill={theme.fill.tertiary}
          stroke={theme.accent.primary}
          strokeWidth={1}
          strokeDasharray="4 3"
        />
        <text x={680} y={158} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>
          dream
        </text>
        <text x={680} y={174} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
          默认维护 · gated
        </text>
      </g>
      <path
        d="M 560 86 Q 620 120 680 134"
        fill="none"
        stroke={theme.stroke.primary}
        strokeWidth={1.2}
        strokeDasharray="4 3"
        markerEnd="url(#rdy-loop-arrow)"
      />
      <text x={380} y={208} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        公开默认路径 · hooks + Agent 自动触发 · /hm:* 为控制与回退面
      </text>
    </svg>
  );
}

function LoopStripDiagram() {
  const theme = useHostTheme();
  const steps = ["wake", "search", "distill", "review", "dream"];
  const xs = [30, 150, 270, 390, 510];

  return (
    <svg viewBox="0 0 640 72" width="100%" height="auto" role="img" aria-label="L1 memory loop">
      <defs>
        <marker id="rdy-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.stroke.primary} />
        </marker>
      </defs>
      {steps.map((label, i) => (
        <g key={label}>
          <rect
            x={xs[i]}
            y={16}
            width={96}
            height={40}
            rx={6}
            fill={label === "distill" ? theme.fill.secondary : theme.fill.tertiary}
            stroke={theme.stroke.secondary}
            strokeWidth={1}
          />
          <text x={xs[i] + 48} y={41} textAnchor="middle" fill={theme.text.primary} fontSize={11} fontWeight={600}>
            {label}
          </text>
          {i < steps.length - 1 ? (
            <line
              x1={xs[i] + 96}
              y1={36}
              x2={xs[i + 1]}
              y2={36}
              stroke={theme.stroke.primary}
              strokeWidth={1.5}
              markerEnd="url(#rdy-arrow)"
            />
          ) : null}
        </g>
      ))}
    </svg>
  );
}

export default function HarnessMemReadinessV1Canvas() {
  const trackRows: string[][] = READINESS_TRACKS.map((t) => [
    `${t.code} ${t.label}`,
    `${t.weight}%`,
    String(t.score),
    t.acceptance,
    t.evidence,
  ]);

  const scopeRows: string[][] = SCOPE_LEDGER.map((s) => [s.item, s.state, s.note]);

  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 1000, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>Readiness Ladder</H1>
          <Pill tone="info">model {MODEL_VERSION}</Pill>
          <Pill tone="success">runtime {RUNTIME_VERSION}</Pill>
        </Row>
        <Text tone="secondary">
          harness-mem 成熟度 · 规范 docs/maturity-model.md · 核对 {AS_OF} · 替代十维雷达 headline
        </Text>
      </Stack>

      <Callout tone="info">
        加权就绪度 {WEIGHTED_READINESS}/100 — 主要拉低项 {BOTTLENECK.code} {BOTTLENECK.label}（{BOTTLENECK.score}）。
        ⑦ Wiki 等「主动不做」项已移入 Scope Ledger，不再扣综合分。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="加权就绪度" value={`${WEIGHTED_READINESS}`} tone="success" />
        <Stat label="最低轨" value={`${BOTTLENECK.code} ${BOTTLENECK.score}`} tone="warning" />
        <Stat label="Pytest" value={`${PYTEST_PASSED}/${PYTEST_COUNT}`} tone="info" />
        <Stat label="Claim 边界" value={`${CLAIM_CHECKS.filter((c) => c.ok).length}/${CLAIM_CHECKS.length}`} tone="success" />
      </Grid>

      <Stack gap={6}>
        <H2>Layer 1 — 六轨 Readiness</H2>
        <Text tone="tertiary" size="small">
          纵轴：轨道得分 (0–100) · 横轴：L1–L6 · 参考线 80 · 权重见表
        </Text>
      </Stack>
      <Card>
        <CardBody>
          <BarChart
            horizontal
            height={260}
            categories={READINESS_TRACKS.map((t) => `${t.code} ${t.label}`)}
            series={[{ name: "轨道得分", data: READINESS_TRACKS.map((t) => t.score), tone: "info" }]}
            yMin={70}
            yMax={100}
            referenceLines={[{ value: 80, label: "可用门槛 80", tone: "success" }]}
          />
          <Divider />
          <UsageBar
            total={100}
            topLeftLabel="加权贡献（weight × score）"
            topRightLabel={`合计 ${WEIGHTED_READINESS}`}
            segments={READINESS_TRACKS.map((t, i) => ({
              id: t.id,
              value: Math.round((t.weight / 100) * t.score * 10) / 10,
              color: (["green", "blue", "purple", "orange", "yellow", "pink"] as const)[i],
            }))}
          />
        </CardBody>
      </Card>

      <Table
        headers={["轨", "权重", "分", "验收句", "证据锚点"]}
        rows={trackRows}
        columnAlign={["left", "right", "right", "left", "left"]}
        striped
      />

      <Stack gap={6}>
        <H2>运行时架构</H2>
        <Text tone="tertiary" size="small">
          单一 MCP 面 · transcript ledger + store 分层 · vec0 可选 · Rust 加速非版本叙事
        </Text>
      </Stack>
      <Card>
        <CardBody>
          <ArchitectureDiagram />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>核心闭环</H2>
        <Text tone="tertiary" size="small">公开默认路径 · dream 为并行默认维护（虚线侧路）</Text>
      </Stack>
      <Card>
        <CardBody>
          <CoreLoopDiagram />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>L1 记忆闭环（简图）</H2>
        <Text tone="tertiary" size="small">与上节详图对照 · 用于 Readiness 轨 L1 速览</Text>
      </Stack>
      <Card>
        <CardBody>
          <LoopStripDiagram />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>Layer 2 — Scope Ledger</H2>
        <Text tone="tertiary" size="small">四态枚举 · 不计入百分制 · 对齐 docs/roadmap/defer.md</Text>
      </Stack>
      <Table
        headers={["项", "状态", "备注"]}
        rows={scopeRows}
        columnAlign={["left", "left", "left"]}
      />
      <Row gap={8} wrap>
        {(["shipped", "in_progress", "deferred", "out_of_product"] as ScopeState[]).map((s) => (
          <Row key={s} gap={4} align="center">
            {scopePill(s)}
            <Text tone="tertiary" size="small">
              {SCOPE_LEDGER.filter((i) => i.state === s).length}
            </Text>
          </Row>
        ))}
      </Row>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader>Layer 3 — Claim boundary</CardHeader>
          <CardBody>
            <Stack gap={10}>
              {CLAIM_CHECKS.map((c) => (
                <Checkbox key={c.id} checked={c.ok} disabled label={c.label} />
              ))}
            </Stack>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>十维 → 六轨迁移</CardHeader>
          <CardBody style={{ padding: 0 }}>
            <Table headers={["旧十维", "新归属"]} rows={LEGACY_MAP} framed={false} />
            <Divider />
            <Text tone="tertiary" size="small">
              历史对比保留：canvases/harness-mem-convergence-before-after.canvas.tsx
            </Text>
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={6}>
        <H3>下一轨改进（L3）</H3>
        <TodoListCard
          todos={[
            {
              id: "l5-1",
              content: "用新增 outcome / abstention / exclusion 数据校准排序多样性",
              status: "pending",
            },
            {
              id: "l5-2",
              content: "只有 golden suite 证明提升时才调整 RRF / adaptive IDF",
              status: "pending",
            },
            {
              id: "l5-3",
              content: "保留 graph DB、第二 store 和后台语义 Agent 为非目标",
              status: "pending",
            },
          ]}
          defaultExpanded
        />
      </Stack>

      <Card variant="borderless">
        <CardBody>
          <Text tone="secondary" size="small">
            Source: get_project_status · CHANGELOG 0.9.12 · docs/maturity-model.md · {PYTEST_PASSED} pytest passed / {PYTEST_SKIPPED} skipped ({PYTEST_COUNT} collected)
          </Text>
        </CardBody>
      </Card>
    </Stack>
  );
}
