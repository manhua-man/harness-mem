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
  TodoListCard,
  UsageBar,
  useHostTheme,
} from "cursor/canvas";

const SNAPSHOT_AT = "2026-08-02";
const RELEASE_VERSION = "0.9.10";
const RUNNING_MCP_VERSION = "0.9.9.1";
const PLUGIN_VERSION = "0.9.10";
const PYTEST_PASSED = 637;
const PYTEST_SKIPPED = 2;
const BACKLOG_ACTIVE = 2;
const BACKLOG_PARKED = 198;
const BACKLOG_TOTAL = BACKLOG_ACTIVE + BACKLOG_PARKED;

const RELEASE_ROWS = [
  ["Repository version", RELEASE_VERSION, "main release truth"],
  ["Python tests", `${PYTEST_PASSED} passed / ${PYTEST_SKIPPED} skipped`, "发布质量门已通过"],
  ["Public MCP surface", "27 tools", "精确契约；未增加产品入口"],
  ["Host coverage", "7 hosts", "Codex / Claude Code / Cursor / Grok / Hermes / OpenCode / Antigravity"],
  ["Context lineage", "shipped", "append-aware projection · tool-safe windows · receipts"],
  ["Truth boundary", "shipped", "canonical state 唯一；derived cache 可重建"],
];

const LIVE_ROWS = [
  ["Phase", "needs-distill", "warning", "历史整理仍是当前运行重点"],
  ["Running MCP", RUNNING_MCP_VERSION, "drift", `落后 repo / plugin ${RELEASE_VERSION}`],
  ["Installed plugin", PLUGIN_VERSION, "current", "插件文件已更新"],
  ["Install state", "drift detected", "warning", "刷新 runtime 后重启宿主并重采样"],
  ["Observations", "207", "evidence", "证据数量，不等于长期记忆"],
  ["Memories", "1", "truth", "当前已治理长期事实"],
  ["Rules", "0", "truth", "当前没有长期规则"],
  ["Handoffs", "1", "truth", "当前任务交接"],
  ["Pending candidates", "5", "queue", "等待 Dream 治理或事后 review"],
  ["Distill backlog", `${BACKLOG_TOTAL}`, "critical", `${BACKLOG_ACTIVE} active / ${BACKLOG_PARKED} parked`],
  ["Throughput", "0.43 / day", "critical", "按当前速率约 466 天清空"],
  ["Retrieval feedback", "insufficient", "unknown", "2 surfaced；缺 used / ignored / misleading 反馈"],
];

function VersionDriftDiagram() {
  const theme = useHostTheme();
  const box = (
    x: number,
    title: string,
    value: string,
    fill: string,
    stroke: string,
  ) => (
    <g key={title}>
      <rect x={x} y={34} width={210} height={76} rx={9} fill={fill} stroke={stroke} strokeWidth={1.5} />
      <text x={x + 105} y={61} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>{title}</text>
      <text x={x + 105} y={88} textAnchor="middle" fill={theme.text.primary} fontSize={16} fontWeight={700}>{value}</text>
    </g>
  );

  return (
    <svg viewBox="0 0 760 170" width="100%" height="auto" role="img" aria-label="repo plugin MCP runtime 版本漂移">
      {box(25, "Repository", RELEASE_VERSION, theme.fill.secondary, theme.accent.primary)}
      {box(275, "Installed plugin", PLUGIN_VERSION, theme.fill.secondary, theme.accent.primary)}
      {box(525, "Running MCP", RUNNING_MCP_VERSION, theme.fill.tertiary, theme.stroke.primary)}
      <line x1={235} y1={72} x2={275} y2={72} stroke={theme.accent.primary} strokeWidth={1.5} />
      <line x1={485} y1={72} x2={525} y2={72} stroke={theme.stroke.primary} strokeWidth={1.5} strokeDasharray="5 4" />
      <text x={505} y={62} textAnchor="middle" fill={theme.text.tertiary} fontSize={9}>drift</text>
      <text x={380} y={144} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        代码成熟度不会自动升级已运行进程；刷新安装并重启 MCP 宿主后才可视为运行一致
      </text>
    </svg>
  );
}

function TwoTruthsDiagram() {
  const theme = useHostTheme();
  return (
    <svg viewBox="0 0 760 250" width="100%" height="auto" role="img" aria-label="发布成熟度和实时运营健康度是两类不同事实">
      <rect x={30} y={24} width={325} height={170} rx={10} fill={theme.fill.secondary} stroke={theme.accent.primary} strokeWidth={1.5} />
      <text x={192} y={54} textAnchor="middle" fill={theme.text.primary} fontSize={14} fontWeight={700}>Release maturity</text>
      <text x={192} y={80} textAnchor="middle" fill={theme.text.tertiary} fontSize={11}>回答：这版代码是否可发布？</text>
      <text x={192} y={110} textAnchor="middle" fill={theme.text.primary} fontSize={11}>版本 · 测试 · 契约 · 宿主覆盖</text>
      <text x={192} y={135} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>来自 repo 与发布质量门</text>
      <text x={192} y={165} textAnchor="middle" fill={theme.accent.primary} fontSize={11} fontWeight={600}>0.9.10 release truth</text>

      <rect x={405} y={24} width={325} height={170} rx={10} fill={theme.fill.tertiary} stroke={theme.stroke.primary} strokeWidth={1.5} />
      <text x={567} y={54} textAnchor="middle" fill={theme.text.primary} fontSize={14} fontWeight={700}>Live operations</text>
      <text x={567} y={80} textAnchor="middle" fill={theme.text.tertiary} fontSize={11}>回答：这台设备现在跑得怎样？</text>
      <text x={567} y={110} textAnchor="middle" fill={theme.text.primary} fontSize={11}>进程版本 · backlog · 吞吐 · 反馈</text>
      <text x={567} y={135} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>来自运行时状态，只代表一个时间点</text>
      <text x={567} y={165} textAnchor="middle" fill={theme.text.primary} fontSize={11} fontWeight={600}>needs-distill · install drift</text>

      <text x={380} y={225} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        两块可以同时为真：代码已通过发布门，但当前设备仍有版本漂移和 200 条整理 backlog
      </text>
    </svg>
  );
}

export default function HarnessMemReadiness0910Canvas() {
  return (
    <Stack gap={24} style={{ padding: 20, maxWidth: 1040, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>harness-mem 0.9.10 Readiness</H1>
          <Pill tone="success">release 0.9.10</Pill>
          <Pill tone="warning">live needs-distill</Pill>
          <Pill tone="warning">install drift</Pill>
        </Row>
        <Text tone="secondary">
          发布成熟度与实时运营健康度分开陈述。Live metrics 是 {SNAPSHOT_AT} 快照，不是永久结论。
        </Text>
      </Stack>

      <Callout tone="warning">
        不提供一个掩盖运营问题的综合分：0.9.10 代码通过质量门，与 running MCP 仍为 0.9.9.1、parked backlog 为 198 可以同时成立。
      </Callout>

      <Card><CardBody><TwoTruthsDiagram /></CardBody></Card>

      <Stack gap={6}>
        <Row gap={8} align="center" wrap>
          <H2>Release maturity</H2>
          <Pill tone="success">repo truth</Pill>
        </Row>
        <Text tone="tertiary" size="small">稳定、可复查的发布事实；不随当前 MCP 进程或 backlog 波动。</Text>
      </Stack>

      <Grid columns={4} gap={12}>
        <Stat label="Repository" value={RELEASE_VERSION} tone="success" />
        <Stat label="Python tests" value={`${PYTEST_PASSED} + ${PYTEST_SKIPPED}`} tone="success" />
        <Stat label="Public MCP tools" value="27" tone="info" />
        <Stat label="Qualified hosts" value="7" tone="info" />
      </Grid>

      <Card>
        <CardHeader>Release evidence</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table headers={["契约", "0.9.10 事实", "证据含义"]} rows={RELEASE_ROWS} framed={false} striped />
        </CardBody>
      </Card>

      <Callout tone="success">
        Release verdict：0.9.10 的仓库版本、637 passed / 2 skipped、27-tool 公共面与七宿主契约成立。这里不对设备当前吞吐作乐观推断。
      </Callout>

      <Divider />

      <Stack gap={6}>
        <Row gap={8} align="center" wrap>
          <H2>Live operations</H2>
          <Pill tone="warning">snapshot {SNAPSHOT_AT}</Pill>
        </Row>
        <Text tone="tertiary" size="small">运行时快照必须在刷新安装、重启宿主之后重新采集；下列数字不能沿用为新版发布事实。</Text>
      </Stack>

      <Grid columns={4} gap={12}>
        <Stat label="Running MCP" value={RUNNING_MCP_VERSION} tone="warning" />
        <Stat label="Distill backlog" value={String(BACKLOG_TOTAL)} tone="warning" />
        <Stat label="Throughput / day" value="0.43" tone="warning" />
        <Stat label="Retrieval feedback" value="insufficient" tone="warning" />
      </Grid>

      <Card>
        <CardHeader>Runtime version alignment</CardHeader>
        <CardBody><VersionDriftDiagram /></CardBody>
      </Card>

      <Card>
        <CardHeader>Backlog composition</CardHeader>
        <CardBody>
          <UsageBar
            total={BACKLOG_TOTAL}
            topLeftLabel="Distill backlog"
            topRightLabel={`${BACKLOG_ACTIVE} active · ${BACKLOG_PARKED} parked`}
            segments={[
              { id: "active", value: BACKLOG_ACTIVE, color: "blue" },
              { id: "parked", value: BACKLOG_PARKED, color: "orange" },
            ]}
          />
          <Divider />
          <Text tone="secondary" size="small">
            active 只占 1%；parked 占 99%。队列不再爆炸不等于历史已经消化，当前吞吐仍是主要运营瓶颈。
          </Text>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>Live snapshot detail</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table headers={["指标", "快照值", "分类", "解释"]} rows={LIVE_ROWS} framed={false} striped />
        </CardBody>
      </Card>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader>Current canonical content</CardHeader>
          <CardBody>
            <Grid columns={3} gap={10}>
              <Stat label="Observations" value="207" tone="info" />
              <Stat label="Memory" value="1" tone="success" />
              <Stat label="Handoff" value="1" tone="success" />
              <Stat label="Rules" value="0" tone="info" />
              <Stat label="Pending" value="5" tone="warning" />
              <Stat label="Phase" value="needs-distill" tone="warning" />
            </Grid>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>Interpretation guardrails</CardHeader>
          <CardBody>
            <Stack gap={8}>
              <Text tone="secondary">• 207 Observations 是 evidence，不等于 207 条长期事实。</Text>
              <Text tone="secondary">• 5 pending 不等于需要用户逐条人工审批。</Text>
              <Text tone="secondary">• insufficient feedback 表示无法证明真实检索收益。</Text>
              <Text tone="secondary">• runtime 刷新后必须重采样，不能只改图上的版本号。</Text>
            </Stack>
          </CardBody>
        </Card>
      </Grid>

      <Stack gap={6}>
        <H3>Next operational verification</H3>
        <TodoListCard
          todos={[
            { id: "runtime-refresh", content: "刷新全局 0.9.10 runtime，重启 MCP 宿主并验证 plugin / process 版本一致", status: "pending" },
            { id: "resample", content: "重新运行 status / doctor，重采样 phase、backlog、吞吐与 install drift", status: "pending" },
            { id: "drain", content: "验证 parked backlog 持续下降、失败不饥饿后续任务，记录 7 日吞吐", status: "pending" },
            { id: "feedback", content: "积累 used / ignored / misleading 反馈后再判断检索线上质量", status: "pending" },
          ]}
          defaultExpanded
        />
      </Stack>

      <Callout tone="info">
        快照刷新规则：任何 runtime 安装、MCP 重启、backlog drain 或 feedback 采集后，都应重新生成 Live operations；Release maturity 只在发布契约变化时更新。
      </Callout>

      <Card variant="borderless">
        <CardBody>
          <Text tone="secondary" size="small">
            Sources: repository 0.9.10 quality gates · get_project_status live snapshot ({SNAPSHOT_AT}) · 637 passed / 2 skipped · 27 public tools · seven-host contract.
          </Text>
        </CardBody>
      </Card>
    </Stack>
  );
}
