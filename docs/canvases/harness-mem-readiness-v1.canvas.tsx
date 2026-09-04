import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Text,
} from "cursor/canvas";

const MODEL_VERSION = "v1";
const AS_OF = "2026-09-04";
const RUNTIME_VERSION = "0.9.27";
const PUBLIC_RELEASE_VERSION = "0.9.27";

const MODULES = [
  { code: "0", title: "会话接入与生命周期", unit: "1 session + 1 immutable revision", owns: "宿主接入、chunk、job、receipt、重试与来源生命周期" },
  { code: "1", title: "提取", unit: "0–12 promotion points", owns: "完整 manifest、窄 claim 与可重开 source location" },
  { code: "2", title: "逐点验证", unit: "1 promotion point", owns: "reference integrity、当前语义支持与 fail-closed Answer Gate" },
  { code: "3", title: "归纳吸收", unit: "1 verified point", owns: "拆分、去重、替代、明确 no-write 与 SQLite mutation" },
  { code: "4", title: "检索与使用", unit: "1 task / query", owns: "干净 wake/search、排序、去重与 bounded feedback" },
];

const EXECUTION_PATHS = [
  { title: "人工显式 distill", body: "当前宿主读取一个会话并执行模块 1–3；不改道到后台执行。" },
  { title: "Stop Hook", body: "只在模块 0 保存 revision、创建或推进 session job，并发出 Dream activity signal。" },
  { title: "授权 Dream", body: "enabled=true 时由项目选择的 CLI 服务会话处理与项目治理两个队列；默认使用当前宿主，也可明确指定。" },
];

const STORAGE_ROLES = [
  { title: "Transcript ledger", body: "raw revisions / chunks；证据权威，不是长期事实" },
  { title: "Job workspace", body: "candidate / evidence / proposed decision；成功终态后按策略清理" },
  { title: "Canonical SQLite", body: "knowledge_entries；当前长期知识唯一权威" },
  { title: "Derived projections", body: "FTS / vector / Markdown；可重建，不可反向成为真值" },
];

export default function HarnessMemReadinessV1() {
  return (
    <Stack gap={18} style={{ padding: 20, maxWidth: 1120, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>harness-mem 当前源码架构与发布边界</H1>
          <Pill tone="info">source {RUNTIME_VERSION}</Pill>
          <Pill tone="success">public {PUBLIC_RELEASE_VERSION}</Pill>
          <Pill tone="info">{MODEL_VERSION}</Pill>
        </Row>
        <Text tone="secondary">
          0.9.27 源码面板 · 核对日期 {AS_OF} · 历史 canvas 不作为当前版本真值
        </Text>
      </Stack>

      <Grid columns={4} gap={12}>
        <Stat label="功能模块" value="5" tone="info" />
        <Stat label="原生宿主" value="7" tone="info" />
        <Stat label="公开 MCP 工具" value="27" tone="success" />
        <Stat label="实际结果检查" value="12" tone="success" />
      </Grid>

      <Callout tone="info">
        当前结论：SQLite knowledge_entries 是当前长期知识唯一权威；原始会话是证据；
        候选、验证与拟议决定是 job 范围临时材料。completed / queued 字段本身不是用户结果证据。
      </Callout>

      <Callout tone="info">
        使用路径：Quickstart 只需为当前 Agent 全局运行一次并安装唯一 hm 入口；
        每个项目第一次使用 hm 时才连接项目并准备 Hook。Quickstart 不管理 MCP 连接。
      </Callout>

      <Stack gap={8}>
        <H2>五模块功能架构</H2>
        <Text tone="secondary">每个模块有独立处理单位、owner 和质量信号；Daily 动作不是另一套架构。</Text>
        <Grid columns={5} gap={10}>
          {MODULES.map((module) => (
            <Card key={module.code}>
              <CardHeader>
                <Row gap={8} align="center"><Pill tone="info">{module.code}</Pill><H3>{module.title}</H3></Row>
              </CardHeader>
              <CardBody>
                <Stack gap={6}>
                  <Text weight="semibold">{module.unit}</Text>
                  <Text tone="secondary" size="small">{module.owns}</Text>
                </Stack>
              </CardBody>
            </Card>
          ))}
        </Grid>
      </Stack>

      <Stack gap={8}>
        <H2>执行边界</H2>
        <Grid columns={3} gap={12}>
          {EXECUTION_PATHS.map((path) => (
            <Card key={path.title}>
              <CardHeader><H3>{path.title}</H3></CardHeader>
              <CardBody><Text tone="secondary">{path.body}</Text></CardBody>
            </Card>
          ))}
        </Grid>
        <Callout tone="warning">
          Dream 只在真实来源完整、可重开、项目已开启后台（`distill.autonomous.enabled=true`）且所选 CLI 可用时执行。
          多条知识关系无法安全裁决时关闭比较而不改写；Review 是事后纠错与 undo 支路。
        </Callout>
      </Stack>

      <Stack gap={8}>
        <H2>存储角色</H2>
        <Grid columns={4} gap={12}>
          {STORAGE_ROLES.map((role) => (
            <Card key={role.title}>
              <CardHeader><H3>{role.title}</H3></CardHeader>
              <CardBody><Text tone="secondary" size="small">{role.body}</Text></CardBody>
            </Card>
          ))}
        </Grid>
      </Stack>

      <Callout tone="info">
        版本事实：源码、runtime 与 plugin manifest 均为 0.9.27；公开版本以 GitHub Releases 为准。
        冻结六会话 oracle、隔离的真实 Hook 全链路与 12 项当前实际结果检查是仓库记录的用户结果证据。
      </Callout>

      <Text tone="tertiary" size="small">
        Source: pyproject.toml · harness_mem/__init__.py · AGENTS.md · CHANGELOG Unreleased · docs/maturity-model.md · .codex/outcomes.json
      </Text>
    </Stack>
  );
}
