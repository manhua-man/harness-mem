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

const AS_OF = "2026-06-28";
const BEFORE_VERSION = "v5.6 / v5.0";
const AFTER_VERSION = "v0.8.3";

/** 十维同口径逐项对比 */
const TEN_DIM_COMPARE = [
  { id: "wake", label: "① Wake", before: 91, after: 88, delta: -3, bucket: "保守重估", verdict: "公开面更窄；guided flow 保留" },
  { id: "storage", label: "② 存储", before: 87, after: 84, delta: -3, bucket: "叙事收缩", verdict: "规模 benchmark 退出公开故事；store 拆分进行中" },
  { id: "retrieval", label: "③ 检索", before: 86, after: 85, delta: -1, bucket: "实质持平", verdict: "0.8.3 固化 recall steps + golden suite" },
  { id: "truth", label: "④ Truth", before: 94, after: 95, delta: 1, bucket: "加强", verdict: "review gate + state audit ledger" },
  { id: "mcp", label: "⑤ MCP", before: 91, after: 89, delta: -2, bucket: "广度换清晰", verdict: "多 profile → 单一 public surface" },
  { id: "temporal", label: "⑥ 时序", before: 83, after: 80, delta: -3, bucket: "非主轴", verdict: "observation 读模型；非图库路线" },
  { id: "wiki", label: "⑦ Wiki", before: 76, after: 68, delta: -8, bucket: "主动不做", verdict: "M10 wiki bridge 已删" },
  { id: "cost", label: "⑧ 成本", before: 69, after: 74, delta: 5, bucket: "加强", verdict: "recall 可解释；仍无全局 saving 宣称" },
  { id: "maint", label: "⑨ 维护", before: 78, after: 82, delta: 4, bucket: "加强", verdict: "Dream opt-in → 默认 Daily + gate/audit" },
  { id: "evidence", label: "⑩ 证据", before: 96, after: 88, delta: -8, bucket: "尺子换了", verdict: "31 accepted runs → 69 pytest 公开叙事" },
];

const FIVE_DIM_BEFORE = [
  { label: "核心产品能力", value: 90 },
  { label: "v4–v5 架构与证据", value: 94 },
  { label: "质量与治理", value: 93 },
  { label: "性能/成本证据", value: 86 },
  { label: "对外宣称边界", value: 52 },
];

const FIVE_DIM_AFTER = [
  { label: "核心产品闭环", value: 93 },
  { label: "公开面收敛 (V4)", value: 90 },
  { label: "质量与治理", value: 91 },
  { label: "检索与可解释性", value: 85 },
  { label: "对外宣称边界", value: 80 },
];

const CORE_LOOP_IDS = ["wake", "retrieval", "truth", "mcp", "temporal", "maint"];
const LAB_BREADTH_IDS = ["wiki", "evidence", "storage"];

const avg = (vals: number[]) => Math.round(vals.reduce((s, v) => s + v, 0) / vals.length);

const TEN_BEFORE_AVG = avg(TEN_DIM_COMPARE.map((d) => d.before));
const TEN_AFTER_AVG = avg(TEN_DIM_COMPARE.map((d) => d.after));
const CORE_BEFORE = avg(TEN_DIM_COMPARE.filter((d) => CORE_LOOP_IDS.includes(d.id)).map((d) => d.before));
const CORE_AFTER = avg(TEN_DIM_COMPARE.filter((d) => CORE_LOOP_IDS.includes(d.id)).map((d) => d.after));
const LAB_BEFORE = avg(TEN_DIM_COMPARE.filter((d) => LAB_BREADTH_IDS.includes(d.id)).map((d) => d.before));
const LAB_AFTER = avg(TEN_DIM_COMPARE.filter((d) => LAB_BREADTH_IDS.includes(d.id)).map((d) => d.after));

const FIVE_BEFORE_AVG = avg(FIVE_DIM_BEFORE.map((d) => d.value));
const FIVE_AFTER_AVG = avg(FIVE_DIM_AFTER.map((d) => d.value));
const CLAIM_BEFORE = 52;
const CLAIM_AFTER = 80;

const REMOVED = [
  { item: "M10 wiki bridge / knowledge-cache", why: "非 memory core loop；易混淆 truth 来源" },
  { item: "Skill governance MCP/CLI 面", why: "避免变成 skill lifecycle manager" },
  { item: "MCP 多 profile (full/minimal/labs…)", why: "用户心智负担；public contract 不清晰" },
  { item: "/hm:mark · /hm:prune 用户入口", why: "artifact 维护不应进 Daily 面" },
  { item: "旧版 distill KB/PRD 管理", why: "第二产品能力；改走 candidate + review" },
  { item: "31 accepted runs 公开叙事", why: "maintainer 证据留在内部；公开改 pytest + smoke" },
];

const STRENGTHENED = [
  { item: "wake → search → distill → review", note: "默认叙事唯一主链" },
  { item: "Dream 默认维护", note: "gate / audit ledger / undo" },
  { item: "0.8.3 recall + retrieval baseline", note: "search / trace 带 evidence · fixed steps · score_details；golden suite 可回归" },
  { item: "State audit ledger", note: "governance 事件 append-only 可审计" },
  { item: "/hm:distill 默认 preview", note: "durable write 仅经 /hm:review" },
  { item: "对外宣称边界", note: "52 → 80（五维口径）" },
];

const REVIEW_QUESTIONS = [
  "十维均分下降 2 分，是否接受为「聚焦代价」而非「能力退化」？",
  "⑦ Wiki / ⑩ 证据 是否应该继续留在十维雷达里，还是拆成「实验室扩展维」？",
  "③ 检索 −1 分是否低估 recall contract？建议复核为持平或 +1。",
  "② 存储 −3 分：底层 scale 能力仍在时，公开分应反映「代码」还是「可承诺面」？",
  "五维里「架构证据 94→90」是否应标注为维度迁移，避免误读为退步？",
];

function deltaTone(delta: number): "success" | "warning" | "info" | "neutral" {
  if (delta > 0) return "success";
  if (delta === 0) return "neutral";
  if (delta >= -3) return "info";
  return "warning";
}

function bucketTone(bucket: string): "success" | "warning" | "info" | "neutral" {
  if (bucket === "加强") return "success";
  if (bucket === "主动不做" || bucket === "尺子换了") return "warning";
  if (bucket === "广度换清晰" || bucket === "叙事收缩") return "info";
  return "neutral";
}

export default function HarnessMemConvergenceBeforeAfterCanvas() {
  const deltaSeries = TEN_DIM_COMPARE.map((d) => d.after - d.before);

  return (
    <Stack gap={20} style={{ padding: 20, maxWidth: 1000, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>收敛前后对比分析</H1>
          <Pill tone="neutral">外部分享稿</Pill>
        </Row>
        <Text tone="secondary">
          harness-mem · {BEFORE_VERSION}（实验室/maintainer 口径）vs {AFTER_VERSION}（公开产品基线）· 核对 {AS_OF}
        </Text>
      </Stack>

      <Callout tone="info">
        结论先行：十维均分 {TEN_BEFORE_AVG} → {TEN_AFTER_AVG}（−{TEN_BEFORE_AVG - TEN_AFTER_AVG}），但 Memory 六维 {CORE_BEFORE} → {CORE_AFTER}（−{CORE_BEFORE - CORE_AFTER}，基本持平）。
        下降主要来自「主动删面」与「证据评分尺子更换」；核心 daily 路径在 Truth、维护、对外宣称上加强。
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat label="十维均分" value={`${TEN_BEFORE_AVG}→${TEN_AFTER_AVG}`} tone="warning" />
        <Stat label="Memory 六维" value={`${CORE_BEFORE}→${CORE_AFTER}`} tone="info" />
        <Stat label="实验室扩展三维" value={`${LAB_BEFORE}→${LAB_AFTER}`} tone="warning" />
        <Stat label="对外宣称 (五维)" value={`${CLAIM_BEFORE}→${CLAIM_AFTER}`} tone="success" />
      </Grid>

      <Stack gap={6}>
        <H2>十维逐项：v5.6 vs 0.8.3</H2>
        <Text tone="tertiary" size="small">主观分 0–100 · 同维度名称对齐 · 橙=收敛前 蓝=收敛后</Text>
      </Stack>
      <Card>
        <CardBody>
          <BarChart
            horizontal
            height={360}
            categories={TEN_DIM_COMPARE.map((d) => d.label)}
            series={[
              { name: `收敛前 ${BEFORE_VERSION}`, data: TEN_DIM_COMPARE.map((d) => d.before), tone: "warning" },
              { name: `收敛后 ${AFTER_VERSION}`, data: TEN_DIM_COMPARE.map((d) => d.after), tone: "info" },
            ]}
            yMin={60}
            yMax={100}
            referenceLines={[{ value: 80, label: "80 分参考线", tone: "success" }]}
          />
          <Text tone="tertiary" size="small">纵轴：主观分 · 横轴：十维 · 来源：completion/reference 历史 canvas 与 0-8x canvas</Text>
        </CardBody>
      </Card>

      <Grid columns={2} gap={12}>
        <Card>
          <CardHeader>十维变化量（after − before）</CardHeader>
          <CardBody>
            <BarChart
              height={220}
              categories={TEN_DIM_COMPARE.map((d) => d.label)}
              series={[{ name: "分值变化", data: deltaSeries, tone: "info" }]}
              yMin={-10}
              yMax={6}
              valueSuffix=" 分"
              showValues
            />
            <Text tone="tertiary" size="small">负值=收敛后更低 · 正值=加强</Text>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>两种读法：子集均分</CardHeader>
          <CardBody>
            <Stack gap={14}>
              <UsageBar
                total={100}
                topLeftLabel="Memory 六维（daily 主轴）"
                topRightLabel={`${CORE_BEFORE} → ${CORE_AFTER}`}
                segments={[
                  { id: "core-b", value: CORE_BEFORE, color: "yellow" },
                  { id: "core-a", value: CORE_AFTER, color: "blue" },
                ]}
              />
              <UsageBar
                total={100}
                topLeftLabel="实验室扩展三维"
                topRightLabel={`${LAB_BEFORE} → ${LAB_AFTER}`}
                segments={[
                  { id: "lab-b", value: LAB_BEFORE, color: "yellow" },
                  { id: "lab-a", value: LAB_AFTER, color: "gray" },
                ]}
              />
              <UsageBar
                total={100}
                topLeftLabel="五维完成度均分"
                topRightLabel={`${FIVE_BEFORE_AVG} → ${FIVE_AFTER_AVG}`}
                segments={[
                  { id: "5-b", value: FIVE_BEFORE_AVG, color: "yellow" },
                  { id: "5-a", value: FIVE_AFTER_AVG, color: "green" },
                ]}
              />
            </Stack>
            <Text tone="tertiary" size="small">拆子集后可见：降分集中在实验室扩展维，非 core loop 崩塌</Text>
          </CardBody>
        </Card>
      </Grid>

      <Card>
        <CardHeader>十维明细 · 变化原因（请外部评审勾选是否同意）</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["维", "前", "后", "Δ", "归类", "解读"]}
            rows={TEN_DIM_COMPARE.map((d) => [
              d.label,
              String(d.before),
              String(d.after),
              (
                <Pill tone={deltaTone(d.delta)} size="sm">
                  {d.delta > 0 ? `+${d.delta}` : String(d.delta)}
                </Pill>
              ),
              <Pill tone={bucketTone(d.bucket)} size="sm">{d.bucket}</Pill>,
              d.verdict,
            ])}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>五维完成度：维度不完全同构，需映射阅读</CardHeader>
        <CardBody style={{ padding: 0 }}>
          <Table
            headers={["收敛前 (v5.0)", "分", "收敛后 (0.8.x)", "分", "映射说明"]}
            rows={[
              ["核心产品能力", "90", "核心产品闭环", "93", "主链更完整，+3"],
              ["v4–v5 架构与证据", "94", "公开面收敛 (V4)", "90", "从内部证据链 → 公开 contract，非单纯退步"],
              ["质量与治理", "93", "质量与治理", "91", "略降；但新增 state audit"],
              ["性能/成本证据", "86", "检索与可解释性", "85", "recall 可解释性替代部分 cost 叙事"],
              ["对外宣称边界", "52", "对外宣称边界", "80", "公开产品最大正向变化，+28"],
            ]}
          />
        </CardBody>
      </Card>

      <Grid columns={2} gap={12}>
        <Card>
          <CardHeader trailing="移出/收缩">收敛删了什么</CardHeader>
          <CardBody style={{ padding: 0 }}>
            <Table
              headers={["项", "原因"]}
              rows={REMOVED.map((r) => [r.item, r.why])}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader trailing="保留/加强">收敛加强了什么</CardHeader>
          <CardBody style={{ padding: 0 }}>
            <Table
              headers={["项", "说明"]}
              rows={STRENGTHENED.map((r) => [r.item, r.note])}
            />
          </CardBody>
        </Card>
      </Grid>

      <Card>
        <CardHeader>给评审者的 5 个问题</CardHeader>
        <CardBody>
          <Table
            headers={["#", "评审问题"]}
            rows={REVIEW_QUESTIONS.map((q, i) => [String(i + 1), q])}
          />
        </CardBody>
      </Card>

      <Divider />

      <Stack gap={8}>
        <H3>口径声明（分享时务必带上）</H3>
        <Text tone="secondary">
          本对比不是「同一个产品在两个版本的功能回归测试」，而是「实验室全能叙事」与「公开可承诺叙事」的对照。
          分数下降不等于代码能力消失；分数上升也不等于所有删除都正确。请评审者分别判断：core loop 承诺、实验室扩展、评分尺子三件事。
        </Text>
        <Text tone="tertiary" size="small">
          数据来源：canvases/harness-mem-completion.canvas.tsx · harness-mem-reference-comparison.canvas.tsx · *-0-8x.canvas.tsx · docs/roadmap.md
        </Text>
      </Stack>
    </Stack>
  );
}
