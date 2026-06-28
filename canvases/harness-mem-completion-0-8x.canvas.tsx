import {
  BarChart,
  Callout,
  Card,
  CardBody,
  CardHeader,
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

const VERSION = "0.8.3";
const AS_OF = "2026-06-28";
const PYTEST_COUNT = 69;
const ROADMAP_DOC = "docs/roadmap.md";

const COMPLETION_DIMENSIONS = [
  { label: "核心产品闭环", value: 93, tone: "success" as const },
  { label: "公开面收敛", value: 90, tone: "success" as const },
  { label: "质量与治理", value: 91, tone: "success" as const },
  { label: "检索与可解释性", value: 85, tone: "success" as const },
  { label: "对外宣称边界", value: 80, tone: "info" as const },
];

const DELIVERED_SLICES = [
  { id: "core-loop", label: "wake→search→distill→review", value: 100 },
  { id: "v081", label: "0.8.1 公开基线重置", value: 100 },
  { id: "v082", label: "0.8.2 recall + audit", value: 100 },
  { id: "v083", label: "0.8.3 retrieval quality foundation", value: 100 },
  { id: "public-surface", label: "单 public memory surface", value: 100 },
  { id: "next-hardening", label: "0.8.4.x/0.8.5.x/0.8.6.x", value: 35 },
];

const CAPABILITIES = [
  { area: "Wake / Search", status: "已交付", note: "guided flow v5.13；0.8.3 recall steps + retrieval-quality baseline" },
  { area: "Distill / Review", status: "已交付", note: "默认 preview；durable write 仅经 /hm:review 显式 gate" },
  { area: "Dream 维护", status: "默认开启", note: "auto gate + audit ledger + undo；非第二套 metabolism 产品面" },
  { area: "MCP 单公开面", status: "已收敛", note: "无 profile 选择；registry 只注册 public memory tools" },
  { area: "CLI", status: "operator console", note: "init/doctor/config/integration/maintenance；import/purge 下沉且默认 dry-run" },
  { area: "State Audit", status: "0.8.2 新增", note: "append-only governance ledger；maintenance state-audit" },
  { area: "Storage 边界", status: "进行中", note: "TruthStore / CandidateStore / DerivedIndex 不变量测试已落；facade 继续下沉" },
  { area: "session-distill", status: "P1 专项", note: "KB/PRD 已删；packet→candidate→suggest-only export" },
  { area: "Skill governance", status: "已移出", note: "不进 MCP / CLI / Daily slash；迁出 memory 产品面" },
  { area: "Optional Rust", status: "可选加速", note: "Python-only path 可跑 core loop；不污染 package version 叙事" },
];

const ROADMAP_TRACK = [
  { id: "surface", content: "已收敛 — MCP 单 public memory surface；历史 profile/env gate 已删除", status: "completed" as const },
  { id: "distill", content: "已收敛 — /hm:distill 默认 preview；auto-review 不默认写 durable truth", status: "completed" as const },
  { id: "dream", content: "已收敛 — Dream 默认 Daily 能力；gate / ledger / undo 边界保留", status: "completed" as const },
  { id: "cli", content: "已收敛 — CLI 退回 operator console；顶层 import/purge 下沉 maintenance", status: "completed" as const },
  { id: "removed", content: "已收敛 — M10 wiki bridge / skill governance MCP / mark·prune slash 已移出产品面", status: "completed" as const },
  { id: "v082-recall", content: "0.8.2 — additive recall contract（search_memory / trace_relations）", status: "completed" as const },
  { id: "v082-audit", content: "0.8.2 — state audit ledger + relation scoring + causal benchmark smoke", status: "completed" as const },
  { id: "v083-benchmark", content: "0.8.3 — LLM-free retrieval-quality golden suite；stale / leak / abstain / vector-off fallback", status: "completed" as const },
  { id: "v084", content: "0.8.4.x — superseded/current hardening + recall explain polish", status: "pending" as const },
  { id: "v085", content: "0.8.5.x — filter-first hybrid ranking + adaptive RRF A/B + low-confidence abstention", status: "pending" as const },
  { id: "v086", content: "0.8.6.x — dream 输出 supersede candidate + why_it_matters/action hint", status: "pending" as const },
  { id: "tests", content: `${PYTEST_COUNT} pytest collected · public-smoke CI · storage/search invariant suite`, status: "completed" as const },
];

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
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={theme.stroke.primary} strokeWidth={1.5} markerEnd="url(#arrowhead-08x)" />
    </g>
  );

  return (
    <svg viewBox="0 0 720 360" width="100%" height="auto" role="img" aria-label="harness-mem 0.8.x 运行时架构">
      <defs>
        <marker id="arrowhead-08x" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.stroke.primary} />
        </marker>
      </defs>
      {box(20, 12, 680, 48, theme.fill.tertiary, "Agent 客户端 + /hm:* + 单一 MCP public surface", "status · wake · search · distill · review · dream")}
      {arrow(360, 60, 360, 78)}
      {box(20, 78, 680, 48, theme.fill.secondary, "harness_mem Python 编排", "MCP handlers · guided flow · candidate workflow · CLI maintenance")}
      {arrow(360, 126, 360, 144)}
      {box(20, 144, 220, 64, theme.fill.tertiary, "TruthStore", "confirmed memory / rules")}
      {box(250, 144, 220, 64, theme.fill.tertiary, "CandidateStore", "pending / rejected lifecycle")}
      {box(480, 144, 220, 64, theme.fill.tertiary, "DerivedIndex + SearchFacade", "FTS · optional vector · recall")}
      {arrow(130, 208, 130, 226)}
      {arrow(360, 208, 360, 226)}
      {arrow(590, 208, 590, 226)}
      {box(20, 226, 330, 56, theme.fill.quaternary, "Canonical SQLite", "local-first durable store")}
      {box(370, 226, 330, 56, theme.fill.quaternary, "State Audit Ledger", "governance append-only")}
      {box(20, 296, 680, 48, theme.fill.tertiary, "Optional native acceleration (Rust PyO3)", "Python-only fallback · 非产品版本叙事")}
      <text x={360} y={352} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        candidate → review gate → supersede · 无静默改写 confirmed truth
      </text>
    </svg>
  );
}

function CoreLoopDiagram() {
  const theme = useHostTheme();
  const nodes = [
    { x: 80, y: 60, label: "wake", sub: "项目简报" },
    { x: 240, y: 60, label: "search", sub: "recall + sources" },
    { x: 400, y: 60, label: "distill", sub: "evidence → 候选" },
    { x: 560, y: 60, label: "review", sub: "唯一 durable gate" },
    { x: 680, y: 160, label: "dream", sub: "默认维护 · gated" },
  ];

  return (
    <svg viewBox="0 0 760 220" width="100%" height="auto" role="img" aria-label="0.8.x 核心闭环">
      <defs>
        <marker id="loop-arrow-08x" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
        </marker>
      </defs>
      {nodes.slice(0, 4).map((n) => (
        <g key={n.label}>
          <rect x={n.x - 58} y={n.y - 26} width={116} height={52} rx={8} fill={theme.fill.secondary} stroke={theme.stroke.secondary} strokeWidth={1} />
          <text x={n.x} y={n.y - 2} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>
            {n.label}
          </text>
          <text x={n.x} y={n.y + 16} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
            {n.sub}
          </text>
        </g>
      ))}
      <line x1={138} y1={60} x2={182} y2={60} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#loop-arrow-08x)" />
      <line x1={298} y1={60} x2={342} y2={60} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#loop-arrow-08x)" />
      <line x1={458} y1={60} x2={502} y2={60} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#loop-arrow-08x)" />
      <g>
        <rect x={622} y={134} width={116} height={52} rx={8} fill={theme.fill.tertiary} stroke={theme.accent.primary} strokeWidth={1} strokeDasharray="4 3" />
        <text x={680} y={158} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>
          dream
        </text>
        <text x={680} y={174} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
          默认维护 · gated
        </text>
      </g>
      <path d="M 560 86 Q 620 120 680 134" fill="none" stroke={theme.stroke.primary} strokeWidth={1.2} strokeDasharray="4 3" markerEnd="url(#loop-arrow-08x)" />
      <text x={380} y={208} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        稳定版默认叙事：可读 · 可准备 · 可建议 · 可审查 · 可审计维护
      </text>
    </svg>
  );
}

export default function HarnessMemCompletion08xCanvas() {
  const avgProduct = Math.round(
    COMPLETION_DIMENSIONS.slice(0, 3).reduce((s, d) => s + d.value, 0) / 3,
  );
  const avgEvidence = Math.round(
    COMPLETION_DIMENSIONS.slice(3).reduce((s, d) => s + d.value, 0) / 2,
  );
  const doneTrack = ROADMAP_TRACK.filter((t) => t.status === "completed").length;

  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 960, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>harness-mem 完成度全景</H1>
          <Pill tone="info">v{VERSION}</Pill>
          <Pill tone="neutral">公开基线</Pill>
        </Row>
        <Text tone="secondary">
          harness-mem 仓库 · 数据源 {ROADMAP_DOC} · CHANGELOG · 核对日期 {AS_OF}
        </Text>
      </Stack>

      <Callout tone="info">
        0.8.x 是公开产品基线：local-first、可审计、可插拔 Agent memory backend。默认公开面已经收回
        wake→search→distill→review；Dream 为默认维护能力。旧版 v5.x 证据链 canvas 仍保留作历史对照。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="包版本" value={`v${VERSION}`} tone="info" />
        <Stat label="产品/收敛均值" value={`${avgProduct}%`} tone="success" />
        <Stat label="检索/宣称均值" value={`${avgEvidence}%`} tone="success" />
        <Stat label="pytest" value={`${PYTEST_COUNT}`} tone="info" />
      </Grid>

      <Stack gap={6}>
        <H2>五维完成度</H2>
        <Text tone="tertiary" size="small">主观评估 · 百分制 · 基于 0.8.x roadmap 与 0.8.3 代码/测试</Text>
      </Stack>
      <Card>
        <CardBody>
          <BarChart
            horizontal
            height={220}
            categories={COMPLETION_DIMENSIONS.map((d) => d.label)}
            series={[{ name: "完成度 (%)", data: COMPLETION_DIMENSIONS.map((d) => d.value), tone: "info" }]}
            yMin={0}
            yMax={100}
            referenceLines={[{ value: 80, label: "可用门槛 80%", tone: "success" }]}
          />
          <Text tone="tertiary" size="small">
            纵轴：完成度 (%) · 横轴：评估维度 · 参考线 80% · 来源：{ROADMAP_DOC}
          </Text>
        </CardBody>
      </Card>

      <Grid columns={2} gap={12}>
        <Card>
          <CardHeader>交付切片权重</CardHeader>
          <CardBody>
            <Text tone="tertiary" size="small">0.8.x 公开基线 + 后续硬化线（示意，非工时）</Text>
            <BarChart
              horizontal
              height={180}
              categories={DELIVERED_SLICES.map((s) => s.label)}
              series={[{ name: "进度 (%)", data: DELIVERED_SLICES.map((s) => s.value), tone: "info" }]}
              yMin={0}
              yMax={100}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>成熟度条</CardHeader>
          <CardBody>
            <Stack gap={16}>
              <UsageBar
                total={100}
                topLeftLabel="产品 + 收敛"
                topRightLabel={`${avgProduct}%`}
                segments={[{ id: "product", value: avgProduct, color: "green" }]}
              />
              <UsageBar
                total={100}
                topLeftLabel="检索 + 宣称边界"
                topRightLabel={`${avgEvidence}%`}
                segments={[{ id: "evidence", value: avgEvidence, color: "orange" }]}
              />
              <UsageBar
                total={100}
                topLeftLabel="路线项完成"
                topRightLabel={`${doneTrack}/${ROADMAP_TRACK.length}`}
                segments={[
                  { id: "done", value: Math.round((doneTrack / ROADMAP_TRACK.length) * 100), color: "blue" },
                ]}
              />
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={6}>
        <H2>0.8.x 运行时架构</H2>
        <Text tone="tertiary" size="small">单一 MCP 面 · 0.8.x trust/retrieval/maintenance hardening · labs 不进默认叙事</Text>
      </Stack>
      <Card>
        <CardBody>
          <ArchitectureDiagram />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>核心闭环</H2>
        <Text tone="tertiary" size="small">公开默认路径 · dream 为并行默认维护</Text>
      </Stack>
      <Card>
        <CardBody>
          <CoreLoopDiagram />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>能力矩阵</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["能力域", "状态", "说明"]}
            rows={CAPABILITIES.map((c) => [
              c.area,
              (
                <Pill
                  tone={
                    c.status === "已交付" || c.status === "已收敛" || c.status === "0.8.2 新增"
                      ? "success"
                      : c.status === "已移出"
                        ? "neutral"
                        : c.status === "默认开启"
                          ? "info"
                          : "warning"
                  }
                  size="sm"
                >
                  {c.status}
                </Pill>
              ),
              c.note,
            ])}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader trailing={`${doneTrack}/${ROADMAP_TRACK.length} done`}>0.8.x 路线与已收敛边界</CardHeader>
        <CardBody>
          <TodoListCard todos={ROADMAP_TRACK} defaultExpanded />
        </CardBody>
      </Card>

      <Divider />

      <Stack gap={8}>
        <H3>与旧版 canvas 的关系</H3>
        <Grid columns={2} gap={8}>
          <Text>
            <Text weight="semibold">harness-mem-completion.canvas.tsx</Text> — v5.0 证据链时代快照（保留）
          </Text>
          <Text>
            <Text weight="semibold">本文件</Text> — 0.8.x 公开基线 + 后续版本路线
          </Text>
        </Grid>
        <Text tone="tertiary" size="small">
          数据内嵌自 CHANGELOG 0.8.3、{ROADMAP_DOC}、{PYTEST_COUNT} pytest（{AS_OF}）
        </Text>
      </Stack>
    </Stack>
  );
}
