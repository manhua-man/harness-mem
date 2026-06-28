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

const VERSION = "0.8.3";
const AS_OF = "2026-06-28";

/** 十维：harness-mem 0.8.x 公开基线 vs 各维参考项目峰值（天花板） */
const TEN_DIMENSIONS = [
  {
    id: "wake",
    label: "① Wake",
    hm: 88,
    peak: 92,
    peakProject: "claude-mem",
    note: "guided flow v5.13；公开面更窄，渐进披露保留",
  },
  {
    id: "storage",
    label: "② 存储",
    hm: 84,
    peak: 93,
    peakProject: "hindsight",
    note: "local SQLite + TruthStore/CandidateStore 拆分进行中",
  },
  {
    id: "retrieval",
    label: "③ 检索",
    hm: 85,
    peak: 94,
    peakProject: "hindsight",
    note: "0.8.3 recall steps + golden suite；hybrid/vector 可选，不阻断 core loop",
  },
  {
    id: "truth",
    label: "④ Truth",
    hm: 95,
    peak: 94,
    peakProject: "hm",
    note: "review gate + state audit；公开基线最强维",
  },
  {
    id: "mcp",
    label: "⑤ MCP",
    hm: 89,
    peak: 93,
    peakProject: "hindsight",
    note: "单一 public surface；无 profile 心智负担",
  },
  {
    id: "temporal",
    label: "⑥ 时序",
    hm: 80,
    peak: 91,
    peakProject: "hindsight",
    note: "observations / session evidence；非图数据库",
  },
  {
    id: "wiki",
    label: "⑦ Wiki",
    hm: 68,
    peak: 97,
    peakProject: "meta-kb",
    note: "M10 wiki bridge 已删；刻意不做 wiki-as-truth",
  },
  {
    id: "cost",
    label: "⑧ 成本",
    hm: 74,
    peak: 87,
    peakProject: "OpenSpace",
    note: "recall 可解释；diagnostic cost 未作公开宣称",
  },
  {
    id: "maint",
    label: "⑨ 维护",
    hm: 82,
    peak: 93,
    peakProject: "ai-harness",
    note: "dream 默认 + gate/audit/undo；standalone metabolism 面已删",
  },
  {
    id: "evidence",
    label: "⑩ 证据/测试",
    hm: 88,
    peak: 96,
    peakProject: "hm (v5 era)",
    note: "69 pytest + invariant suite；无 maintainer 31-run 公开叙事",
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
const GAP_OVER_10 = TEN_DIMENSIONS.filter((d) => d.peak - d.hm > 10).length;

const RUNTIME_PEERS = [
  { project: "harness-mem 0.8.x", role: "truth-gated local runtime", avg: MEMORY_RUNTIME_AVG, tone: "info" as const },
  { project: "hindsight (ref)", role: "memory OS 天花板", avg: 83, tone: "neutral" as const },
  { project: "claude-mem (ref)", role: "hook 披露", avg: 61, tone: "neutral" as const },
];

const V08X_DELTAS = [
  { slice: "0.8.1 公开基线", impact: "叙事重置", detail: "local-first auditable backend；prune 非产品文档" },
  { slice: "0.8.2 recall", impact: "③ 检索 +2", detail: "search_memory/trace_relations additive recall payload" },
  { slice: "0.8.3 retrieval baseline", impact: "③ 可信度 +1", detail: "LLM-free golden suite；stale/leak/abstain/vector-off fallback" },
  { slice: "V4.2 单 MCP 面", impact: "⑤ MCP +1", detail: "删除 profile/labs；registry 只注册 public tools" },
  { slice: "V4 dream 默认", impact: "⑨ 维护 +2", detail: "Daily 含 dream；standalone metabolism 产品面删除" },
  { slice: "M10 / skill gov 移除", impact: "⑦ Wiki −2", detail: "wiki bridge 与 skill lifecycle 移出 memory 产品面" },
];

const POSITIONING_SHIFTS = [
  { from: "v5.x 多 profile MCP", to: "0.8.x 单一 public memory surface", tone: "success" as const },
  { from: "31 accepted runs 叙事", to: "69 pytest + public-smoke CI", tone: "info" as const },
  { from: "wiki bridge / skill governance", to: "candidate→review 唯一 truth 路径", tone: "success" as const },
  { from: "CLI 第二产品入口", to: "operator console + maintenance", tone: "info" as const },
];

function deltaTone(gap: number): "success" | "warning" | "info" {
  if (gap <= 0) return "success";
  if (gap <= 5) return "info";
  return "warning";
}

export default function HarnessMemReferenceComparison08xCanvas() {
  const gapSeries = TEN_DIMENSIONS.map((d) => Math.max(0, d.peak - d.hm));

  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 980, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>参考项目十维对比</H1>
          <Pill tone="info">v{VERSION}</Pill>
          <Pill tone="neutral">Maintainer · 0.8.x</Pill>
        </Row>
        <Text tone="secondary">
          harness-mem 仓库 · 主观分基于公开基线定位 · 核对日期 {AS_OF}
        </Text>
      </Stack>

      <Callout tone="warning">
        能力雷达，不是总分榜。蓝柱 = harness-mem 0.8.x；橙柱 = 该维参考峰值（天花板）。0.8.x 主动收窄了 wiki、skill
        governance、多 profile MCP 等面，④ Truth 与公开可审计叙事是刻意押注的维度。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="十维均分" value={`${HM_AVG}`} tone="info" />
        <Stat label="Memory 六维" value={`${MEMORY_RUNTIME_AVG}`} tone="success" />
        <Stat label="并列/领先维" value={`${LEAD_COUNT}/10`} tone="success" />
        <Stat label="差距 &gt;10 分" value={`${GAP_OVER_10}`} tone="warning" />
      </Grid>

      <Stack gap={6}>
        <H2>harness-mem 0.8.x vs 参考峰值</H2>
        <Text tone="tertiary" size="small">
          主观分 0–100 · 峰值来自行业/上游参考项目 · 已收敛边界与 0.8.3 retrieval baseline 已计入
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
            橙柱来源：{TEN_DIMENSIONS.map((d) => `${d.label}→${d.peakProject}`).join(" · ")}
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
              yMax={30}
              valueSuffix=" 分"
              showValues
            />
            <Text tone="tertiary" size="small">落后 = 参考峰值 − harness-mem · 0 分维已省略</Text>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>Memory runtime 对手均分（示意）</CardHeader>
          <CardBody>
            <Stack gap={14}>
              {RUNTIME_PEERS.map((p, i) => (
                <UsageBar
                  total={100}
                  topLeftLabel={p.project}
                  topRightLabel={`${p.avg}`}
                  segments={[{
                    id: `peer-${i}`,
                    value: p.avg,
                    color: p.project.startsWith("harness-mem") ? "blue" : "gray",
                  }]}
                />
              ))}
            </Stack>
            <Text tone="tertiary" size="small">六维 memory runtime 子集 · 品类不同不可直接排名</Text>
          </CardBody>
        </Card>
      </Grid>

      <Card>
        <CardHeader>分维明细与 0.8.x 依据</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["维", "hm", "峰值", "峰值项目", "差", "0.8.x 备注"]}
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
        <CardHeader>0.8.x 对本矩阵的影响</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["切片", "评分影响", "说明"]}
            rows={V08X_DELTAS.map((r) => [r.slice, r.impact, r.detail])}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>相对 v5.6 canvas 的定位迁移</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["旧叙事", "0.8.x 叙事", ""]}
            rows={POSITIONING_SHIFTS.map((r) => [
              r.from,
              r.to,
              <Pill tone={r.tone} size="sm">迁移</Pill>,
            ])}
          />
        </CardBody>
      </Card>

      <Divider />

      <Stack gap={8}>
        <H3>怎么读这张图</H3>
        <Text tone="secondary">
          0.8.x 不是 v5.6 的增量补丁，而是公开产品基线重置：更少默认面、更强 review gate、更可解释的 recall。
          ⑦ Wiki 与 ⑩ 证据维分数变化部分来自「主动不做」与「证据叙事从 maintainer runs 转向公开 pytest」。
        </Text>
        <Text tone="tertiary" size="small">
          历史 v5.6 十维快照 → canvases/harness-mem-reference-comparison.canvas.tsx（保留）
        </Text>
        <Text tone="tertiary" size="small">
          完成度五维（0.8.x）→ canvases/harness-mem-completion-0-8x.canvas.tsx
        </Text>
      </Stack>
    </Stack>
  );
}
