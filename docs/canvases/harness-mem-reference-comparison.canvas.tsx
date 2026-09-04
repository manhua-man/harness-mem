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
  UsageBar,
} from "cursor/canvas";

const VERSION = "5.6.0";
const AS_OF = "2026-06-18";

/** 十维：harness-mem v5.6 vs 各维参考项目峰值 */
const TEN_DIMENSIONS = [
  {
    id: "wake",
    label: "① Wake",
    hm: 91,
    peak: 92,
    peakProject: "claude-mem",
    note: "v5.3 Daily DX：next_actions / why_this_result",
  },
  {
    id: "storage",
    label: "② 存储",
    hm: 87,
    peak: 93,
    peakProject: "hindsight",
    note: "v5.1 canonical 默认；规模证据 v4.7 已齐",
  },
  {
    id: "retrieval",
    label: "③ 检索",
    hm: 86,
    peak: 94,
    peakProject: "hindsight",
    note: "LongMemEval hybrid-real R@5=0.953",
  },
  {
    id: "truth",
    label: "④ Truth",
    hm: 94,
    peak: 94,
    peakProject: "hm / meta-kb",
    note: "live runtime 最强档；meta-kb 为编译期",
  },
  {
    id: "mcp",
    label: "⑤ MCP",
    hm: 91,
    peak: 93,
    peakProject: "hindsight",
    note: "v5.6 multi-client field-test packet",
  },
  {
    id: "temporal",
    label: "⑥ 时序",
    hm: 83,
    peak: 91,
    peakProject: "hindsight",
    note: "temporal_query read model；非图数据库",
  },
  {
    id: "wiki",
    label: "⑦ Wiki",
    hm: 76,
    peak: 97,
    peakProject: "meta-kb",
    note: "刻意 bridge-only，不做 wiki-as-truth",
  },
  {
    id: "cost",
    label: "⑧ 成本",
    hm: 69,
    peak: 87,
    peakProject: "OpenSpace",
    note: "surface_cost 有；全局 saving 仍 blocked",
  },
  {
    id: "maint",
    label: "⑨ 维护",
    hm: 78,
    peak: 93,
    peakProject: "ai-harness",
    note: "v5.4 guided maintenance_summary；opt-in",
  },
  {
    id: "evidence",
    label: "⑩ 证据",
    hm: 96,
    peak: 96,
    peakProject: "hm / evo",
    note: "31 accepted runs + context_outcome_loop",
  },
];

const HM_AVG = Math.round(
  TEN_DIMENSIONS.reduce((s, d) => s + d.hm, 0) / TEN_DIMENSIONS.length,
);

const MEMORY_RUNTIME_AVG = Math.round(
  TEN_DIMENSIONS.filter((d) =>
    ["wake", "retrieval", "truth", "mcp", "temporal", "maint"].includes(d.id),
  ).reduce((s, d) => s + d.hm, 0) / 6,
);

const LEAD_COUNT = TEN_DIMENSIONS.filter((d) => d.hm >= d.peak).length;
const WITHIN_5_COUNT = TEN_DIMENSIONS.filter((d) => d.peak - d.hm <= 5 && d.hm < d.peak).length;
const GAP_OVER_10 = TEN_DIMENSIONS.filter((d) => d.peak - d.hm > 10).length;

/** Memory runtime 主要对手（均分示意） */
const RUNTIME_PEERS = [
  { project: "harness-mem", role: "truth gate runtime", avg: HM_AVG, tone: "info" as const },
  { project: "hindsight", role: "memory OS", avg: 83, tone: "neutral" as const },
  { project: "mempalace", role: "memory 引擎", avg: 82, tone: "neutral" as const },
  { project: "claude-mem", role: "hook 披露", avg: 61, tone: "neutral" as const },
];

const V56_DELTAS = [
  { slice: "v5.3 Daily Flow DX", impact: "① Wake +1", detail: "status / wake / search 带 next_actions" },
  { slice: "v5.4 Guided Maintenance", impact: "⑨ 维护 +4", detail: "maintenance_summary 统一面" },
  { slice: "v5.5 Outcome Loop", impact: "⑧ 成本 +1", detail: "record_context_outcome；默认 off" },
  { slice: "v5.6 Multi-client", impact: "⑤ MCP +3", detail: "field-test packet；非外部用户证据" },
];

function deltaTone(gap: number): "success" | "warning" | "danger" | "info" {
  if (gap <= 0) return "success";
  if (gap <= 5) return "info";
  if (gap <= 10) return "warning";
  return "danger";
}

export default function HarnessMemReferenceComparisonCanvas() {
  const gapSeries = TEN_DIMENSIONS.map((d) => Math.max(0, d.peak - d.hm));

  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 980, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>参考项目十维对比</H1>
          <Pill tone="info">v{VERSION}</Pill>
          <Pill tone="neutral">Maintainer</Pill>
        </Row>
        <Text tone="secondary">
          harness-mem 仓库 · 数据源 docs/reference-comparison-matrix.md · 核对日期 {AS_OF}
        </Text>
      </Stack>

      <Callout tone="warning">
        能力雷达，不是总分榜。蓝柱 = harness-mem v5.6；橙柱 = 该维参考项目峰值（天花板，非 hm 得分）。不能把
        codedb-mcp / mempalace 的外部 benchmark 写成 harness-mem 分数。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="十维均分" value={`${HM_AVG}`} tone="info" />
        <Stat label="Memory 六维" value={`${MEMORY_RUNTIME_AVG}`} tone="success" />
        <Stat label="并列/领先维" value={`${LEAD_COUNT}/10`} tone="success" />
        <Stat label="差距 &gt;10 分" value={`${GAP_OVER_10}`} tone="warning" />
      </Grid>

      <Stack gap={6}>
        <H2>harness-mem vs 参考峰值（十维）</H2>
        <Text tone="tertiary" size="small">
          主观分 0–100 · 参考源码 ../upstreams/harness-mem/ · v5.3–v5.6 已计入 DX / maintenance / outcome-loop
        </Text>
      </Stack>
      <Card>
        <CardBody>
          <BarChart
            horizontal
            height={360}
            categories={TEN_DIMENSIONS.map((d) => d.label)}
            series={[
              { name: `harness-mem v${VERSION}`, data: TEN_DIMENSIONS.map((d) => d.hm), tone: "info" },
              { name: "参考项目峰值", data: TEN_DIMENSIONS.map((d) => d.peak), tone: "warning" },
            ]}
            yMin={0}
            yMax={100}
            referenceLines={[{ value: 80, label: "80% 门槛", tone: "success" }]}
          />
          <Text tone="tertiary" size="small">
            橙柱项目：{TEN_DIMENSIONS.map((d) => `${d.label}→${d.peakProject}`).join(" · ")}
          </Text>
        </CardBody>
      </Card>

      <Grid columns={2} gap={12}>
        <Card>
          <CardHeader>与峰值差距（仅落后维）</CardHeader>
          <CardBody>
            <BarChart
              height={220}
              categories={TEN_DIMENSIONS.filter((d) => d.hm < d.peak).map((d) => d.label)}
              series={[{ name: "落后分值", data: gapSeries.filter((g) => g > 0), tone: "warning" }]}
              yMin={0}
              yMax={25}
              valueSuffix=" 分"
              showValues
            />
            <Text tone="tertiary" size="small">落后 = 参考峰值 − harness-mem · 0 分维已省略</Text>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>Memory runtime 对手均分</CardHeader>
          <CardBody>
            <Stack gap={14}>
              {RUNTIME_PEERS.map((p) => (
                <UsageBar
                  key={p.project}
                  total={100}
                  topLeftLabel={p.project}
                  topRightLabel={`${p.avg}`}
                  segments={[{ id: p.project, value: p.avg, color: p.project === "harness-mem" ? "blue" : "gray" }]}
                />
              ))}
            </Stack>
            <Text tone="tertiary" size="small">十维全表均分示意 · 品类不同不可直接排名</Text>
          </CardBody>
        </Card>
      </Grid>

      <Card>
        <CardHeader>分维明细与 v5.6 依据</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["维", "hm", "峰值", "峰值项目", "差", "v5.6 备注"]}
            rows={TEN_DIMENSIONS.map((d) => {
              const gap = d.peak - d.hm;
              return [
                d.label,
                String(d.hm),
                String(d.peak),
                d.peakProject,
                (
                  <Pill tone={deltaTone(gap)} size="sm">
                    {gap <= 0 ? "≥峰值" : `−${gap}`}
                  </Pill>
                ),
                d.note,
              ];
            })}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>v5.3–v5.6 对本矩阵的影响</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["切片", "评分影响", "说明"]}
            rows={V56_DELTAS.map((r) => [r.slice, r.impact, r.detail])}
          />
        </CardBody>
      </Card>

      <Divider />

      <Stack gap={8}>
        <H3>怎么读「参考项目峰值」</H3>
        <Text tone="secondary">
          峰值 = 某一维上所有参考项目最高分（天花板）。例如 ① Wake 峰值 92 来自 claude-mem，不是 harness-mem
          的 91 分。④ Truth / ⑩ 证据 harness-mem 与峰值并列或领先。
        </Text>
        <Text tone="tertiary" size="small">
          完整 14 项目总表 · Mermaid 定位图 · 硬边界 → docs/reference-comparison-matrix.md
        </Text>
      </Stack>
    </Stack>
  );
}
