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
  PieChart,
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

const VERSION = "5.0.0";
const AS_OF = "2026-06-16";
const ACCEPTED_RUNS = 31;

const COMPLETION_DIMENSIONS = [
  { label: "核心产品能力", value: 90, tone: "success" as const },
  { label: "v4–v5 架构与证据", value: 94, tone: "success" as const },
  { label: "质量与治理", value: 93, tone: "success" as const },
  { label: "性能/成本证据", value: 86, tone: "success" as const },
  { label: "对外宣称边界", value: 52, tone: "warning" as const },
];

const DELIVERED_SLICES = [
  { id: "v15-v29", label: "v1.5–v2.9 基础闭环", value: 100 },
  { id: "v3x", label: "v3.x 高级能力", value: 100 },
  { id: "v40-v45", label: "v4.0–v4.5 地基", value: 100 },
  { id: "v46-v50", label: "v4.6–v5.0 证据链", value: 100 },
];

const CAPABILITIES = [
  { area: "Wake / Search", status: "已交付", note: "分层 wake、hybrid 检索、渐进披露" },
  { area: "Distill / 候选", status: "已交付", note: "LLM suggest + auto_review，无静默改 truth" },
  { area: "MCP / Slash", status: "已交付", note: "Cursor / Claude / Codex 跨客户端入口" },
  { area: "Storage v2", status: "规模证据已齐", note: "accepted 10k/100k/1m runs；默认 store 未自动切换" },
  { area: "Rust Core", status: "Native 已交付", note: "PyO3 harness_mem_core_rs + accepted hot-path artifact" },
  { area: "Index Fabric", status: "运行时证据已齐", note: "index_fabric_runtime_conformance accepted" },
  { area: "Auto Dream", status: "已交付", note: "opt-in 维护；host 默认 off；只写 ledger / 候选" },
  { area: "Cost/Token 证据", status: "Gate 已过", note: "cost_token_evidence.passed；全局 saving 宣称仍 blocked" },
  { area: "Default Change Gate", status: "Gate 就绪", note: "ready=true；不等于默认 storage/index 已切换" },
];

const EVIDENCE_TRACK = [
  { id: "v46", content: "v4.6 Cost / Token Evidence — cost_token_evidence.passed=true", status: "completed" as const },
  { id: "v47", content: "v4.7 Storage v2 Scale — accepted 10k / 100k / 1M profile runs", status: "completed" as const },
  { id: "v48", content: "v4.8 Index Fabric Runtime — index_fabric_runtime_conformance accepted", status: "completed" as const },
  { id: "v49", content: "v4.9 Rust Native Hot Path — harness_mem_core_rs + rust_core_hot_path accepted", status: "completed" as const },
  { id: "v50", content: "v5.0 Default Change Gate — default_change_decision_gate.ready=true", status: "completed" as const },
  { id: "snapshot", content: `release snapshot 合并 ${ACCEPTED_RUNS} 个 accepted runs · evidence_hardening_track 全通过`, status: "completed" as const },
  { id: "core", content: "v1.5 → v5.0 主路线连续收口（roadmap-status 2026-06-16）", status: "completed" as const },
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
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={theme.stroke.primary} strokeWidth={1.5} markerEnd="url(#arrowhead)" />
    </g>
  );

  return (
    <svg viewBox="0 0 720 340" width="100%" height="auto" role="img" aria-label="harness-mem 架构分层图">
      <defs>
        <marker id="arrowhead" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.stroke.primary} />
        </marker>
      </defs>
      {box(20, 16, 680, 52, theme.fill.tertiary, "Agent / Slash / Skill / MCP", "/hm:wake · /hm:search · /hm:distill")}
      {arrow(360, 68, 360, 88)}
      {box(20, 88, 680, 52, theme.fill.secondary, "harness_mem Python 编排层", "MCP server · CLI maintenance · candidate workflow")}
      {arrow(360, 140, 360, 160)}
      {box(20, 160, 330, 72, theme.fill.tertiary, "Rust Core (native PyO3)", "scan_jsonl · RRF · rank · Python fallback")}
      {box(370, 160, 330, 72, theme.fill.tertiary, "Index Fabric", "exact/word/trigram/vector sidecars")}
      {arrow(185, 232, 185, 252)}
      {arrow(535, 232, 535, 252)}
      {box(20, 252, 330, 72, theme.fill.quaternary, "Canonical SQLite Store", "payload · FTS5 · vec · lifecycle tiers")}
      {box(370, 252, 330, 72, theme.fill.quaternary, "Generated Sidecars", "manifest-last · lazy rebuild · 非 truth")}
      <text x={360} y={332} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        Truth governance: candidate → review → supersede → ledger（不可静默改写 confirmed truth）
      </text>
    </svg>
  );
}

function MemoryLoopDiagram() {
  const theme = useHostTheme();
  const nodes = [
    { x: 60, y: 70, label: "Session 历史", sub: "ingest / distill" },
    { x: 260, y: 70, label: "候选记忆", sub: "suggest_*" },
    { x: 460, y: 70, label: "人工/自动审核", sub: "auto_review" },
    { x: 660, y: 70, label: "Confirmed Truth", sub: "MemoryEntry / Rule" },
    { x: 360, y: 200, label: "Wake / Search", sub: "渐进式检索" },
  ];

  return (
    <svg viewBox="0 0 760 260" width="100%" height="auto" role="img" aria-label="记忆生命周期闭环">
      <defs>
        <marker id="loop-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
        </marker>
      </defs>
      {nodes.map((n) => (
        <g key={n.label}>
          <rect x={n.x - 70} y={n.y - 28} width={140} height={56} rx={8} fill={theme.fill.secondary} stroke={theme.stroke.secondary} strokeWidth={1} />
          <text x={n.x} y={n.y - 4} textAnchor="middle" fill={theme.text.primary} fontSize={11} fontWeight={600}>
            {n.label}
          </text>
          <text x={n.x} y={n.y + 14} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
            {n.sub}
          </text>
        </g>
      ))}
      <line x1={130} y1={70} x2={190} y2={70} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#loop-arrow)" />
      <line x1={330} y1={70} x2={390} y2={70} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#loop-arrow)" />
      <line x1={530} y1={70} x2={590} y2={70} stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#loop-arrow)" />
      <path d="M 660 98 Q 660 150 360 172" fill="none" stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#loop-arrow)" />
      <path d="M 290 200 Q 60 200 60 98" fill="none" stroke={theme.stroke.primary} strokeWidth={1.2} strokeDasharray="4 3" markerEnd="url(#loop-arrow)" />
      <text x={380} y={248} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        虚线：新 session 再次 ingest → 持续学习（仍走候选门控）
      </text>
    </svg>
  );
}

export default function HarnessMemCompletionCanvas() {
  const theme = useHostTheme();
  const avgProduct = Math.round(
    COMPLETION_DIMENSIONS.slice(0, 3).reduce((s, d) => s + d.value, 0) / 3,
  );
  const avgEvidence = Math.round(
    COMPLETION_DIMENSIONS.slice(3).reduce((s, d) => s + d.value, 0) / 2,
  );

  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 960, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>harness-mem 完成度全景</H1>
          <Pill tone="info">v{VERSION}</Pill>
        </Row>
        <Text tone="secondary">
          memory-lab 工作区 · 主产品 harness-mem/ · 数据源 docs/roadmap-status.md · 核对日期 {AS_OF}
        </Text>
      </Stack>

      <Callout tone="info">
        v5.0 已收口 Evidence Hardening Track（v4.6–v5.0）：artifact gate 全通过，default_change_decision_gate.ready=true。public claim 边界不变——仍不能说全局 token 节省、Storage v2 公开 speedup，也不因 gate ready 自动切换默认项。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="当前版本" value={`v${VERSION}`} tone="info" />
        <Stat label="产品能力均值" value={`${avgProduct}%`} tone="success" />
        <Stat label="证据链均值" value={`${avgEvidence}%`} tone="success" />
        <Stat label="Accepted runs" value={`${ACCEPTED_RUNS}`} tone="info" />
      </Grid>

      <Stack gap={6}>
        <H2>五维完成度</H2>
        <Text tone="tertiary" size="small">主观评估 · 百分制 · 基于 roadmap-status 与代码结构</Text>
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
            纵轴：完成度 (%) · 横轴：评估维度 · 参考线：80% 日常可用门槛 · 来源：项目文档与模块盘点
          </Text>
        </CardBody>
      </Card>

      <Grid columns={2} gap={12}>
        <Card>
          <CardHeader>版本线交付占比</CardHeader>
          <CardBody>
            <Text tone="tertiary" size="small">已交付切片 vs 规划中证据链</Text>
            <PieChart
              size={200}
              data={DELIVERED_SLICES.map((s) => ({ label: s.label, value: s.value }))}
            />
            <Text tone="tertiary" size="small">
              切片权重示意（非工时）· v4.6–v5.0 已收口 · 来源：CHANGELOG 5.0.0 / roadmap-status.md
            </Text>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>产品成熟度条</CardHeader>
          <CardBody>
            <Text tone="tertiary" size="small">功能交付 vs 证据硬门槛</Text>
            <Stack gap={16}>
              <UsageBar
                total={100}
                topLeftLabel="功能交付"
                topRightLabel={`${avgProduct}%`}
                segments={[{ id: "product", value: avgProduct, color: "green" }]}
              />
              <UsageBar
                total={100}
                topLeftLabel="证据 / 宣称门槛"
                topRightLabel={`${avgEvidence}%`}
                segments={[{ id: "evidence", value: avgEvidence, color: "orange" }]}
              />
              <UsageBar
                total={100}
                topLeftLabel="综合（加权示意）"
                topRightLabel={`${Math.round(avgProduct * 0.65 + avgEvidence * 0.35)}%`}
                segments={[
                  { id: "p", value: Math.round(avgProduct * 0.65), color: "blue" },
                  { id: "e", value: Math.round(avgEvidence * 0.35), color: "yellow" },
                ]}
              />
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={6}>
        <H2>运行时架构分层</H2>
        <Text tone="tertiary" size="small">v5.0 形态 · Python 编排 + native Rust PyO3 + Index Fabric</Text>
      </Stack>
      <Card>
        <CardBody>
          <ArchitectureDiagram />
        </CardBody>
      </Card>

      <Stack gap={6}>
        <H2>记忆生命周期闭环</H2>
        <Text tone="tertiary" size="small">AI-led Memory Candidate Loop</Text>
      </Stack>
      <Card>
        <CardBody>
          <MemoryLoopDiagram />
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
                    c.status === "已交付" || c.status === "Native 已交付"
                      ? "success"
                      : c.status === "未就绪"
                        ? "warning"
                        : c.status === "Gate 已过" || c.status === "Gate 就绪"
                          ? "success"
                          : "info"
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
        <CardHeader trailing="已完成">Evidence Hardening Track</CardHeader>
        <CardBody>
          <TodoListCard todos={EVIDENCE_TRACK} defaultExpanded />
        </CardBody>
      </Card>

      <Divider />

      <Stack gap={8}>
        <H3>工作区边界</H3>
        <Grid columns={2} gap={8}>
          <Text>
            <Text weight="semibold">harness-mem/</Text> — 主产品源码、测试、MCP、插件
          </Text>
          <Text>
            <Text weight="semibold">tests/benchmarks/</Text> — 实验室级 benchmark 资源
          </Text>
          <Text>
            <Text weight="semibold">docs/</Text> — 跨目录架构与规划文档
          </Text>
          <Text>
            <Text weight="semibold">upstreams/</Text> — 参考镜像（非主代码）
          </Text>
        </Grid>
        <Text tone="tertiary" size="small">
          Canvas 数据内嵌自 CHANGELOG 5.0.0 与 roadmap-status.md（2026-06-16）· 打开后可与聊天并排查看
        </Text>
      </Stack>
    </Stack>
  );
}
