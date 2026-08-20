import {
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
  useHostTheme,
} from "cursor/canvas";

type Theme = ReturnType<typeof useHostTheme>;
type FlowNode = {
  x: number;
  y: number;
  width: number;
  title: string;
  detail: string;
  emphasis?: boolean;
};

const HOSTS = ["Codex", "Claude Code", "Cursor", "Grok", "Hermes", "OpenCode", "Antigravity"];
const DAILY_ACTIONS = ["status", "wake", "search", "search-all", "distill", "review", "dream"];

function Node({ node, theme }: { node: FlowNode; theme: Theme }) {
  return (
    <g>
      <rect
        x={node.x}
        y={node.y}
        width={node.width}
        height={60}
        rx={8}
        fill={node.emphasis ? theme.fill.secondary : theme.fill.tertiary}
        stroke={node.emphasis ? theme.accent.primary : theme.stroke.secondary}
        strokeWidth={node.emphasis ? 1.5 : 1}
      />
      <text
        x={node.x + node.width / 2}
        y={node.y + 25}
        textAnchor="middle"
        fill={theme.text.primary}
        fontSize={12}
        fontWeight={600}
      >
        {node.title}
      </text>
      <text
        x={node.x + node.width / 2}
        y={node.y + 43}
        textAnchor="middle"
        fill={theme.text.tertiary}
        fontSize={10}
      >
        {node.detail}
      </text>
    </g>
  );
}

function Arrow({
  x1,
  y1,
  x2,
  y2,
  theme,
  marker,
  dashed = false,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  theme: Theme;
  marker: string;
  dashed?: boolean;
}) {
  return (
    <line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={dashed ? theme.stroke.primary : theme.accent.primary}
      strokeWidth={1.5}
      strokeDasharray={dashed ? "5 4" : undefined}
      markerEnd={`url(#${marker})`}
    />
  );
}

function SurfaceDiagram() {
  const theme = useHostTheme();
  const nodes: FlowNode[] = [
    { x: 20, y: 34, width: 220, title: "7 hosts", detail: "同一套产品语义" },
    { x: 270, y: 34, width: 220, title: "7 Daily actions", detail: "自然语言 / 宿主命令" },
    { x: 520, y: 34, width: 220, title: "27 public MCP tools", detail: "Agent 调用 · 用户无需背诵", emphasis: true },
  ];

  return (
    <svg viewBox="0 0 760 190" width="100%" height="auto" role="img" aria-label="七宿主、七个 Daily 动作与 27 个公开 MCP 工具">
      <defs>
        <marker id="surface-arrow-0910" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
        </marker>
      </defs>
      {nodes.map((node) => <Node key={node.title} node={node} theme={theme} />)}
      <Arrow x1={240} y1={64} x2={270} y2={64} theme={theme} marker="surface-arrow-0910" />
      <Arrow x1={490} y1={64} x2={520} y2={64} theme={theme} marker="surface-arrow-0910" />
      <text x={130} y={126} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        {HOSTS.slice(0, 4).join(" · ")}
      </text>
      <text x={130} y={143} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        {HOSTS.slice(4).join(" · ")}
      </text>
      <text x={380} y={126} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        {DAILY_ACTIONS.slice(0, 4).join(" · ")}
      </text>
      <text x={380} y={143} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        {DAILY_ACTIONS.slice(4).join(" · ")}
      </text>
      <text x={630} y={134} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        内部服务不构成额外产品入口
      </text>
      <text x={380} y={177} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        日常入口保持小而稳定；CLI 仅负责 setup · doctor · config · integration · maintenance
      </text>
    </svg>
  );
}

function CoreLoopDiagram() {
  const theme = useHostTheme();
  const steps = [
    { x: 20, label: "wake", detail: "恢复项目上下文" },
    { x: 168, label: "search", detail: "按需检索证据" },
    { x: 316, label: "distill", detail: "整理历史会话" },
    { x: 464, label: "review", detail: "事后纠错 / undo" },
    { x: 612, label: "dream", detail: "自动治理维护" },
  ];

  return (
    <svg viewBox="0 0 760 154" width="100%" height="auto" role="img" aria-label="wake search distill review dream 核心闭环">
      <defs>
        <marker id="loop-arrow-0910" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
        </marker>
      </defs>
      {steps.map((step, index) => (
        <g key={step.label}>
          <rect
            x={step.x}
            y={28}
            width={128}
            height={56}
            rx={8}
            fill={step.label === "distill" || step.label === "dream" ? theme.fill.secondary : theme.fill.tertiary}
            stroke={step.label === "review" ? theme.stroke.primary : theme.stroke.secondary}
            strokeDasharray={step.label === "review" ? "4 3" : undefined}
          />
          <text x={step.x + 64} y={52} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>
            {step.label}
          </text>
          <text x={step.x + 64} y={70} textAnchor="middle" fill={theme.text.tertiary} fontSize={9.5}>
            {step.detail}
          </text>
          {index < steps.length - 1 ? (
            <Arrow
              x1={step.x + 128}
              y1={56}
              x2={steps[index + 1].x}
              y2={56}
              theme={theme}
              marker="loop-arrow-0910"
              dashed={step.label === "distill"}
            />
          ) : null}
        </g>
      ))}
      <text x={380} y={119} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        这是稳定的 Daily 动作地图，不表示每条候选都要等人工 review
      </text>
      <text x={380} y={137} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        默认自动链由 distill → challenge → Dream 完成；review 是用户主动审计与纠错支路
      </text>
    </svg>
  );
}

function DistillPipelineDiagram() {
  const theme = useHostTheme();
  const top: FlowNode[] = [
    { x: 18, y: 24, width: 132, title: "Native transcript", detail: "宿主原始会话" },
    { x: 168, y: 24, width: 132, title: "Raw ledger", detail: "immutable revision" },
    { x: 318, y: 24, width: 132, title: "Append projection", detail: "验证前缀 · 只算尾部", emphasis: true },
    { x: 468, y: 24, width: 132, title: "Tool-safe windows", detail: "turn / tool 不拆散", emphasis: true },
    { x: 618, y: 24, width: 124, title: "Distill", detail: "语义候选" },
  ];
  const bottom: FlowNode[] = [
    { x: 72, y: 142, width: 164, title: "Zero-candidate challenge", detail: "证据不足 / 价值不足复核", emphasis: true },
    { x: 298, y: 142, width: 164, title: "Dream validation", detail: "自动验证 · 冲突判断", emphasis: true },
    { x: 524, y: 142, width: 164, title: "Finalize outcome", detail: "promoted / no_candidate", emphasis: true },
  ];

  return (
    <svg viewBox="0 0 760 280" width="100%" height="auto" role="img" aria-label="0.9.10 append-aware semantic distill 流程">
      <defs>
        <marker id="distill-arrow-0910" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
        </marker>
      </defs>
      {top.map((node) => <Node key={node.title} node={node} theme={theme} />)}
      {bottom.map((node) => <Node key={node.title} node={node} theme={theme} />)}
      {top.slice(0, -1).map((node, index) => (
        <Arrow
          key={node.title}
          x1={node.x + node.width}
          y1={54}
          x2={top[index + 1].x}
          y2={54}
          theme={theme}
          marker="distill-arrow-0910"
        />
      ))}
      <path d="M 680 84 Q 680 116 154 142" fill="none" stroke={theme.accent.primary} strokeWidth={1.5} markerEnd="url(#distill-arrow-0910)" />
      <Arrow x1={236} y1={172} x2={298} y2={172} theme={theme} marker="distill-arrow-0910" />
      <Arrow x1={462} y1={172} x2={524} y2={172} theme={theme} marker="distill-arrow-0910" />
      <text x={384} y={231} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        projection receipt 记录 revision、覆盖范围、hash、token basis 与 drilldown pointer
      </text>
      <text x={384} y={250} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        前缀或 hash 不匹配时自动全量重建；projection receipt 不是 Memory
      </text>
      <text x={384} y={269} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        review 可对已产生的结果纠错、驳回或恢复，但不阻塞默认自动完成
      </text>
    </svg>
  );
}

function TruthAndCacheDiagram() {
  const theme = useHostTheme();
  return (
    <svg viewBox="0 0 760 285" width="100%" height="auto" role="img" aria-label="唯一 canonical truth、派生缓存和删除闭环">
      <defs>
        <marker id="storage-arrow-0910" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
        </marker>
      </defs>
      <rect x={24} y={26} width={712} height={100} rx={10} fill={theme.fill.secondary} stroke={theme.accent.primary} strokeWidth={1.5} />
      <text x={380} y={51} textAnchor="middle" fill={theme.text.primary} fontSize={13} fontWeight={700}>
        Canonical SQLite contract — 唯一权威状态
      </text>
      <rect x={48} y={68} width={205} height={40} rx={6} fill={theme.fill.tertiary} stroke={theme.stroke.secondary} />
      <rect x={278} y={68} width={205} height={40} rx={6} fill={theme.fill.tertiary} stroke={theme.stroke.secondary} />
      <rect x={508} y={68} width={205} height={40} rx={6} fill={theme.fill.tertiary} stroke={theme.stroke.secondary} />
      <text x={150} y={92} textAnchor="middle" fill={theme.text.primary} fontSize={11}>Transcript / Observation evidence</text>
      <text x={380} y={92} textAnchor="middle" fill={theme.text.primary} fontSize={11}>Candidate / job / receipt</text>
      <text x={610} y={92} textAnchor="middle" fill={theme.text.primary} fontSize={11}>Memory / Rule / Handoff</text>

      <rect x={88} y={166} width={250} height={58} rx={8} fill={theme.fill.tertiary} stroke={theme.stroke.secondary} strokeDasharray="5 4" />
      <text x={213} y={189} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>Derived semantic cache</text>
      <text x={213} y={207} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>projection · outline · window</text>
      <rect x={422} y={166} width={250} height={58} rx={8} fill={theme.fill.tertiary} stroke={theme.stroke.secondary} strokeDasharray="5 4" />
      <text x={547} y={189} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>Derived retrieval cache</text>
      <text x={547} y={207} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>FTS · vector · trigram · sidecar</text>
      <Arrow x1={260} y1={126} x2={213} y2={166} theme={theme} marker="storage-arrow-0910" dashed />
      <Arrow x1={500} y1={126} x2={547} y2={166} theme={theme} marker="storage-arrow-0910" dashed />
      <path d="M 338 195 Q 380 238 422 195" fill="none" stroke={theme.stroke.primary} strokeWidth={1.4} strokeDasharray="5 4" markerEnd="url(#storage-arrow-0910)" />
      <text x={380} y={252} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        source cleanup / privacy erase → 同步失效 projection 与索引 → receipt 校验无残留 → 后续按新 revision 重建
      </text>
      <text x={380} y={271} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        派生缓存随 revision 清理、可随时重建，永远不能成为第二套 truth
      </text>
    </svg>
  );
}

const OUTCOME_ROWS = [
  ["promoted", "Dream 验证后自动形成长期 Memory / Rule", "review 可事后纠错、supersede 或 undo"],
  ["no_candidate", "挑战后确认没有值得长期保留的内容", "同一 revision 完成，不再反复进入待办"],
  ["cleanup receipt", "记录 retained / deleted / partial_failure / unsupported", "失败进入重试；不能静默声称删除成功"],
];

const BOUNDARY_ROWS = [
  ["Observation", "证据，可回溯；不是长期事实"],
  ["Semantic projection", "可重建派生缓存；不是第二会话库"],
  ["Candidate", "Dream 的治理输入；不是 wake 默认真值"],
  ["Memory / Rule / Handoff", "唯一可被长期消费的已治理状态"],
  ["Review", "事后审计、纠错与 undo；不是日常人工门"],
];

export default function HarnessMemHowItWorks0910Canvas() {
  return (
    <Stack gap={24} style={{ padding: 20, maxWidth: 1040, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>harness-mem 怎么运行</H1>
          <Pill tone="success">0.9.10 current</Pill>
          <Pill tone="info">单一真值 · 自动治理</Pill>
        </Row>
        <Text tone="secondary">
          七宿主共享同一条记忆链路；0.9.10 重点是增量投影、工具安全窗口、零候选挑战与可审计清理。
        </Text>
      </Stack>

      <Callout tone="info">
        用户只需使用 Daily 动作或自然语言。27 个 MCP 工具是 Agent 的稳定能力面；不会出现另一套隐藏命令、会话存储或长期真值。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="Hosts" value="7" tone="info" />
        <Stat label="Daily actions" value="7" tone="info" />
        <Stat label="Public MCP tools" value="27" tone="success" />
        <Stat label="Canonical truth" value="1" tone="success" />
      </Grid>

      <Card>
        <CardHeader>入口面：一次安装，各宿主同一语义</CardHeader>
        <CardBody><SurfaceDiagram /></CardBody>
      </Card>

      <Stack gap={6}>
        <H2>Daily 核心闭环</H2>
        <Text tone="tertiary" size="small">稳定动作地图保持 wake → search → distill → review → dream；status 与 search-all 是只读辅助入口。</Text>
      </Stack>
      <Card><CardBody><CoreLoopDiagram /></CardBody></Card>

      <Stack gap={6}>
        <H2>0.9.10 会话整理主链</H2>
        <Text tone="tertiary" size="small">只复用 hash 验证过的语义前缀；任何异常改写都会回退全量重建。</Text>
      </Stack>
      <Card><CardBody><DistillPipelineDiagram /></CardBody></Card>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader>完成意味着什么</CardHeader>
          <CardBody style={{ padding: 0 }}>
            <Table headers={["结果", "自动行为", "治理保障"]} rows={OUTCOME_ROWS} framed={false} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>产品边界</CardHeader>
          <CardBody style={{ padding: 0 }}>
            <Table headers={["对象", "语义"]} rows={BOUNDARY_ROWS} framed={false} />
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={6}>
        <H2>存储与删除闭环</H2>
        <Text tone="tertiary" size="small">Canonical state 与 derived cache 明确分层；删除原文时不允许遗留可反向恢复内容的投影。</Text>
      </Stack>
      <Card><CardBody><TruthAndCacheDiagram /></CardBody></Card>

      <Divider />
      <Grid columns={3} gap={12}>
        <Card>
          <CardHeader>速度</CardHeader>
          <CardBody><Text tone="secondary">追加会话只处理新增尾部，避免重复读取完整历史。</Text></CardBody>
        </Card>
        <Card>
          <CardHeader>质量</CardHeader>
          <CardBody><Text tone="secondary">user/assistant turn 与 tool call/result 保持完整，减少上下文误判。</Text></CardBody>
        </Card>
        <Card>
          <CardHeader>可解释</CardHeader>
          <CardBody><Text tone="secondary">projection receipt 说明读了什么、复用了什么以及为何完成。</Text></CardBody>
        </Card>
      </Grid>

      <Card variant="borderless">
        <CardBody>
          <Stack gap={4}>
            <H3>一句话边界</H3>
            <Text tone="secondary" size="small">
              Pi 式增量机制被吸收为可重建投影；harness-mem 仍只有一套 canonical transcript / memory contract，摘要与缓存都不能替代事实。
            </Text>
          </Stack>
        </CardBody>
      </Card>
    </Stack>
  );
}
