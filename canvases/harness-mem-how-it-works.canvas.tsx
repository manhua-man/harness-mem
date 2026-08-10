import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  CollapsibleSection,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Swatch,
  Table,
  Text,
  useHostTheme,
} from "cursor/canvas";

type BoxSpec = { x: number; y: number; w: number; h: number; label: string; sub: string; accent?: boolean };

function FlowBox({ spec, theme }: { spec: BoxSpec; theme: ReturnType<typeof useHostTheme> }) {
  const fill = spec.accent ? theme.fill.secondary : theme.fill.tertiary;
  const stroke = spec.accent ? theme.accent.primary : theme.stroke.secondary;
  return (
    <g>
      <rect x={spec.x} y={spec.y} width={spec.w} height={spec.h} rx={8} fill={fill} stroke={stroke} strokeWidth={spec.accent ? 1.5 : 1} />
      <text x={spec.x + spec.w / 2} y={spec.y + 24} textAnchor="middle" fill={theme.text.primary} fontSize={12} fontWeight={600}>
        {spec.label}
      </text>
      <text x={spec.x + spec.w / 2} y={spec.y + 42} textAnchor="middle" fill={theme.text.tertiary} fontSize={10}>
        {spec.sub}
      </text>
    </g>
  );
}

function Arrow({ x1, y1, x2, y2, theme, dashed }: { x1: number; y1: number; x2: number; y2: number; theme: ReturnType<typeof useHostTheme>; dashed?: boolean }) {
  return (
    <line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={dashed ? theme.stroke.primary : theme.accent.primary}
      strokeWidth={1.5}
      strokeDasharray={dashed ? "5 4" : undefined}
      markerEnd="url(#arr)"
    />
  );
}

function SvgFrame({ title, caption, children, height = 280 }: { title: string; caption: string; children?: unknown; height?: number }) {
  const theme = useHostTheme();
  return (
    <Stack gap={8}>
      <H3>{title}</H3>
      <Text tone="tertiary" size="small">{caption}</Text>
      <svg viewBox={`0 0 760 ${height}`} width="100%" height="auto" role="img" aria-label={title}>
        <defs>
          <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill={theme.accent.primary} />
          </marker>
        </defs>
        {children}
      </svg>
    </Stack>
  );
}

function EntryMapDiagram() {
  const theme = useHostTheme();
  const boxes: BoxSpec[] = [
    { x: 20, y: 30, w: 120, h: 56, label: "你", sub: "自然语言 / Slash" },
    { x: 170, y: 30, w: 140, h: 56, label: "Cursor / Claude", sub: "AI 助手客户端" },
    { x: 340, y: 30, w: 120, h: 56, label: "Agent", sub: "替你调工具" },
    { x: 490, y: 30, w: 120, h: 56, label: "MCP", sub: "工具协议层", accent: true },
    { x: 640, y: 30, w: 100, h: 56, label: "harness-mem", sub: "本地运行时" },
    { x: 170, y: 130, w: 140, h: 56, label: "/hm:wake 等", sub: "Slash 快捷入口" },
    { x: 340, y: 130, w: 120, h: 56, label: "Skills", sub: "hm-distill" },
    { x: 490, y: 130, w: 250, h: 56, label: "CLI（排障用）", sub: "doctor · purge · maintenance" },
  ];
  return (
    <SvgFrame title="图 A：你每天怎么用到它" caption="日常入口是聊天和 Slash；MCP 在幕后；CLI 只在安装/排障时用">
      {boxes.map((b) => (
        <g key={b.label}><FlowBox spec={b} theme={theme} /></g>
      ))}
      <Arrow x1={140} y1={58} x2={170} y2={58} theme={theme} />
      <Arrow x1={310} y1={58} x2={340} y2={58} theme={theme} />
      <Arrow x1={460} y1={58} x2={490} y2={58} theme={theme} />
      <Arrow x1={610} y1={58} x2={640} y2={58} theme={theme} />
      <Arrow x1={240} y1={86} x2={380} y2={130} theme={theme} dashed />
      <Arrow x1={400} y1={130} x2={400} y2={100} theme={theme} dashed />
      <text x={380} y={210} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        你不需要记 MCP 工具名；说「用 harness-mem 唤醒项目」即可
      </text>
    </SvgFrame>
  );
}

function WakeFlowDiagram() {
  const theme = useHostTheme();
  const boxes: BoxSpec[] = [
    { x: 30, y: 40, w: 130, h: 56, label: "新 Session 开始", sub: "你打开新对话" },
    { x: 200, y: 40, w: 130, h: 56, label: "Agent 调 wake", sub: "MCP 工具" },
    { x: 370, y: 40, w: 150, h: 56, label: "读取已确认记忆", sub: "Rules / Handoffs / Profile" },
    { x: 560, y: 40, w: 170, h: 56, label: "组装唤醒包", sub: "压缩成可读的上下文", accent: true },
    { x: 200, y: 150, w: 200, h: 56, label: "SQLite + 索引", sub: "本地数据库检索" },
    { x: 450, y: 150, w: 200, h: 56, label: "不读 pending 候选", sub: "避免未审核草稿污染" },
  ];
  return (
    <SvgFrame title="图 B：Wake（唤醒）流程" caption="Wake = 给 AI 一份「这个项目目前已知什么」的精简摘要">
      {boxes.map((b) => (
        <g key={b.label}><FlowBox spec={b} theme={theme} /></g>
      ))}
      <Arrow x1={160} y1={68} x2={200} y2={68} theme={theme} />
      <Arrow x1={330} y1={68} x2={370} y2={68} theme={theme} />
      <Arrow x1={520} y1={68} x2={560} y2={68} theme={theme} />
      <Arrow x1={445} y1={96} x2={300} y2={150} theme={theme} dashed />
      <Arrow x1={445} y1={96} x2={550} y2={150} theme={theme} dashed />
      <text x={380} y={240} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        典型触发：/hm:wake 或「帮我唤醒 harness-mem 项目上下文」
      </text>
    </SvgFrame>
  );
}

function DistillFlowDiagram() {
  const theme = useHostTheme();
  const boxes: BoxSpec[] = [
    { x: 20, y: 30, w: 120, h: 52, label: "/hm:distill", sub: "你发起提炼" },
    { x: 160, y: 30, w: 140, h: 52, label: "prepare_session_distill", sub: "收集会话证据包" },
    { x: 320, y: 30, w: 120, h: 52, label: "hm-distill", sub: "AI 阅读理解" },
    { x: 460, y: 30, w: 120, h: 52, label: "suggest_*", sub: "写入候选层" },
    { x: 600, y: 30, w: 130, h: 52, label: "auto_review", sub: "自动处理低风险" },
    { x: 160, y: 120, w: 140, h: 52, label: "Codex/Claude 归档", sub: "自动识别来源" },
    { x: 320, y: 120, w: 120, h: 52, label: "pending 候选", sub: "待审核草稿" },
    { x: 460, y: 120, w: 120, h: 52, label: "confirm / reject", sub: "确认或拒绝" },
    { x: 600, y: 120, w: 130, h: 52, label: "最终摘要给你", sub: "只看结论纠错", accent: true },
  ];
  return (
    <SvgFrame title="图 C：Distill（提炼）完整流程" caption="从旧聊天记录里挖出值得长期记住的东西；必须经过候选门控">
      {boxes.slice(0, 5).map((b) => (
        <g key={`t-${b.label}`}><FlowBox spec={b} theme={theme} /></g>
      ))}
      {boxes.slice(5).map((b) => (
        <g key={`b-${b.label}`}><FlowBox spec={b} theme={theme} /></g>
      ))}
      <Arrow x1={140} y1={56} x2={160} y2={56} theme={theme} />
      <Arrow x1={300} y1={56} x2={320} y2={56} theme={theme} />
      <Arrow x1={440} y1={56} x2={460} y2={56} theme={theme} />
      <Arrow x1={580} y1={56} x2={600} y2={56} theme={theme} />
      <Arrow x1={230} y1={82} x2={230} y2={120} theme={theme} dashed />
      <Arrow x1={380} y1={82} x2={380} y2={120} theme={theme} dashed />
      <Arrow x1={520} y1={82} x2={520} y2={120} theme={theme} dashed />
      <Arrow x1={665} y1={82} x2={665} y2={120} theme={theme} dashed />
      <text x={380} y={210} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        v2.0 后没有正则启发式提炼；必须由 LLM 理解后再 suggest
      </text>
    </SvgFrame>
  );
}

function SearchFlowDiagram() {
  const theme = useHostTheme();
  const boxes: BoxSpec[] = [
    { x: 40, y: 50, w: 150, h: 56, label: "search_memory", sub: "先给摘要命中" },
    { x: 240, y: 50, w: 150, h: 56, label: "timeline", sub: "按时间线展开" },
    { x: 440, y: 50, w: 150, h: 56, label: "observations", sub: "原始对话证据" },
    { x: 640, y: 50, w: 100, h: 56, label: "你/AI 判断", sub: "是否够用", accent: true },
  ];
  return (
    <SvgFrame title="图 D：Search 渐进式披露" caption="先给短答案，不够再下钻；避免一次塞满上下文" height={200}>
      {boxes.map((b) => (
        <g key={b.label}><FlowBox spec={b} theme={theme} /></g>
      ))}
      <Arrow x1={190} y1={78} x2={240} y2={78} theme={theme} />
      <Arrow x1={390} y1={78} x2={440} y2={78} theme={theme} />
      <Arrow x1={590} y1={78} x2={640} y2={78} theme={theme} />
      <text x={380} y={160} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        检索模式：FTS 关键词 / hybrid 语义+关键词（需安装 hybrid 依赖）
      </text>
    </SvgFrame>
  );
}

function StorageLayersDiagram() {
  const theme = useHostTheme();
  const layers = [
    { y: 20, label: "Observation（原始证据）", sub: "聊天记录原文片段 · 可溯源", fill: theme.fill.quaternary },
    { y: 80, label: "Candidate / pending（候选草稿）", sub: "AI 建议记住的东西 · 尚未生效", fill: theme.fill.tertiary },
    { y: 140, label: "Confirmed truth（已确认记忆）", sub: "MemoryEntry / Rule / Handoff · wake/search 消费", fill: theme.fill.secondary },
    { y: 200, label: "Index 派生层（索引缓存）", sub: "FTS5 · 向量 · sidecar · 可重建", fill: theme.fill.tertiary },
  ];
  return (
    <SvgFrame title="图 E：数据分层（从原始到可用）" caption="越往下越「可检索」；truth 变更必须走审核链" height={260}>
      {layers.map((l) => (
        <g key={l.label}>
          <rect x={40} y={l.y} width={680} height={48} rx={6} fill={l.fill} stroke={theme.stroke.secondary} strokeWidth={1} />
          <text x={60} y={l.y + 22} fill={theme.text.primary} fontSize={12} fontWeight={600}>{l.label}</text>
          <text x={60} y={l.y + 38} fill={theme.text.tertiary} fontSize={10}>{l.sub}</text>
        </g>
      ))}
      <text x={380} y={252} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        Canonical SQLite = 主存储形态；JSON 文件更多用于导出/兼容
      </text>
    </SvgFrame>
  );
}

function ModuleMapDiagram() {
  const theme = useHostTheme();
  const mods = [
    { x: 20, y: 20, w: 160, h: 64, label: "mcp/", sub: "对外工具定义\nwake search suggest" },
    { x: 200, y: 20, w: 160, h: 64, label: "commands/", sub: "CLI 子命令实现\ndoctor maintenance" },
    { x: 380, y: 20, w: 160, h: 64, label: "storage/", sub: "读写 SQLite\n候选与 truth" },
    { x: 560, y: 20, w: 180, h: 64, label: "search/", sub: "FTS + hybrid\n检索编排" },
    { x: 20, y: 110, w: 160, h: 64, label: "adapters/", sub: "解析 Claude/Codex\n会话归档" },
    { x: 200, y: 110, w: 160, h: 64, label: "core/schemas/", sub: "数据结构定义\nMemoryEntry Rule" },
    { x: 380, y: 110, w: 160, h: 64, label: "index_fabric/", sub: "派生索引 sidecar" },
    { x: 560, y: 110, w: 180, h: 64, label: "tools/hm-distill/", sub: "提炼 Skill\n（仓库 tools/）" },
    { x: 200, y: 200, w: 360, h: 52, label: "plugins/harness-mem/", sub: "Slash 命令 · 安装脚本 · IDE 集成", accent: true },
  ];
  return (
    <SvgFrame title="图 F：代码模块地图（harness-mem/）" caption="Python 包在 harness_mem/；Skills 在 tools/；插件在 plugins/" height={280}>
      {mods.map((m) => (
        <g key={m.label}><FlowBox spec={m} theme={theme} /></g>
      ))}
      <text x={380} y={272} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        rust_core.py = native PyO3 harness_mem_core_rs；不可用时 Python fallback
      </text>
    </SvgFrame>
  );
}

function BackgroundWorkerDiagram() {
  const theme = useHostTheme();
  const boxes: BoxSpec[] = [
    { x: 30, y: 40, w: 140, h: 56, label: "本地 worker", sub: "opt-in · worker.mode" },
    { x: 200, y: 40, w: 140, h: 56, label: "dream_auto_tick", sub: "自动维护 tick" },
    { x: 370, y: 40, w: 140, h: 56, label: "reflection_once", sub: "反思队列任务" },
    { x: 540, y: 40, w: 190, h: 56, label: "只写 ledger/候选", sub: "不改 confirmed truth", accent: true },
    { x: 200, y: 140, w: 200, h: 56, label: "DreamRun 账本", sub: "/hm:dream 可查看" },
    { x: 430, y: 140, w: 200, h: 56, label: "IDE hook", sub: "会话边界触发" },
  ];
  return (
    <SvgFrame title="图 G：后台自动维护（Auto Dream）" caption="后台帮你「整理记忆」，但不能偷偷改掉已确认事实" height={230}>
      {boxes.map((b) => (
        <g key={b.label}><FlowBox spec={b} theme={theme} /></g>
      ))}
      <Arrow x1={170} y1={68} x2={200} y2={68} theme={theme} />
      <Arrow x1={340} y1={68} x2={370} y2={68} theme={theme} />
      <Arrow x1={510} y1={68} x2={540} y2={68} theme={theme} />
      <Arrow x1={270} y1={96} x2={270} y2={140} theme={theme} dashed />
      <Arrow x1={440} y1={96} x2={530} y2={140} theme={theme} dashed />
      <text x={380} y={220} textAnchor="middle" fill={theme.text.quaternary} fontSize={10}>
        worker.mode=on 可开启；dream.auto.enabled 控制 Auto Dream；host hook 默认 off
      </text>
    </SvgFrame>
  );
}

const GLOSSARY_CORE = [
  ["Wake", "新对话开始时给 AI 的「项目备忘录」", "/hm:wake · MCP wake"],
  ["Search", "按问题查找历史决策/事实", "/hm:search · search_memory"],
  ["Distill", "从旧会话里提炼可长期记住的知识", "/hm:distill"],
  ["MCP", "AI 客户端调本地工具的标准协议", "Cursor 设置里注册 harness-mem"],
  ["Slash", "聊天输入 /hm:xxx 触发的快捷命令", "/hm:wake /hm:distill"],
  ["Skill", "给 AI 的操作说明书（如 hm-distill）", "tools/hm-distill/"],
  ["CLI", "终端命令；日常不用，装/修/维护时用", "harness-mem doctor"],
];

const GLOSSARY_MEMORY = [
  ["Observation", "原始聊天片段，证据来源", "timeline · get_observations"],
  ["Candidate / pending", "AI 建议记住但还没生效的草稿", "list_candidates"],
  ["Confirmed truth", "审核通过、可被 wake/search 使用的记忆", "MemoryEntry · Rule"],
  ["MemoryEntry", "一条结构化事实（如「API 用 JWT」）", "suggest_memory_entry"],
  ["Rule", "长期遵守的约定（如「禁止用某库」）", "suggest_rule · confirm_rule"],
  ["Handoff", "任务交接：进度、下一步、阻塞点", "create_task_handoff"],
  ["Supersede", "用更新的事实取代旧事实（保留链条）", "confirm_supersede"],
  ["Project Profile", "项目静态画像：技术栈、关键文件", "update_project_profile"],
];

const GLOSSARY_TECH = [
  ["FTS5", "SQLite 全文关键词搜索", "搜类名、函数名很准"],
  ["Hybrid", "关键词 + 语义向量混合检索", "从 GitHub Release 安装 [hybrid]"],
  ["Embedding", "把文字变成向量用于语义相似", "默认 all-MiniLM-L6-v2"],
  ["SQLite", "本地数据库，存记忆主数据", "~/.harness-mem/ 下"],
  ["Index Fabric", "可重建的派生索引 sidecar", "加速检索，不是 truth"],
  ["Canonical store", "v4 主存储契约（DB-first）", "migration dry-run/apply"],
  ["Rust Core", "性能热路径（解析/排序/建索引）", "无 wheel 时 Python 兜底"],
  ["RetrievalSignal", "记录「这条记忆被用过」的影子日志", "给 metabolism 用，Agent 不用主动读"],
];

const GLOSSARY_OPS = [
  ["auto_review", "自动确认低风险候选、拒绝噪声", "distill 同一轮调用"],
  ["Auto Dream", "后台自动整理记忆的维护循环", "/hm:dream 看账本"],
  ["DreamRun", "每次自动维护的运行记录", "dream_ledger MCP"],
  ["Reflection queue", "反思任务队列（job 生命周期）", "reflection_once"],
  ["Doctor", "自检：配置、索引、向量是否健康", "harness-mem doctor"],
  ["Purge", "按策略清理旧数据（可预览）", "维护命令"],
  ["/hm:mark", "标记蒸馏资产状态", "维护 Slash"],
  ["/hm:prune", "修剪冗余候选/记忆", "维护 Slash"],
];

function GlossaryTable({ rows }: { rows: string[][] }) {
  return (
    <Table
      headers={["名词", "白话", "在哪遇到"]}
      rows={rows.map((r) => [r[0], r[1], r[2]])}
      columnAlign={["left", "left", "left"]}
    />
  );
}

export default function HarnessMemHowItWorksCanvas() {
  return (
    <Stack gap={24} style={{ padding: 20, maxWidth: 980, margin: "0 auto" }}>
      <Stack gap={6}>
        <Row gap={10} align="center" wrap>
          <H1>harness-mem 怎么运行</H1>
          <Pill tone="info">入门图解</Pill>
        </Row>
        <Text tone="secondary">
          面向不熟悉名词的读者 · 主产品 harness-mem v5.0.0 · 数据源 AGENTS.md / best-practices.md / roadmap-status.md（2026-06-16）
        </Text>
      </Stack>

      <Callout tone="info">
        一句话：harness-mem 把 AI 聊天记录变成「可审核的长期记忆」，在新对话里自动唤醒给 AI 用。所有写入先走候选，不能静默改已确认事实。
      </Callout>

      <Card>
        <CardHeader trailing="7 张">核心流程图</CardHeader>
        <CardBody>
          <Stack gap={28}>
            <EntryMapDiagram />
            <Divider />
            <WakeFlowDiagram />
            <Divider />
            <DistillFlowDiagram />
            <Divider />
            <SearchFlowDiagram />
            <Divider />
            <StorageLayersDiagram />
            <Divider />
            <ModuleMapDiagram />
            <Divider />
            <BackgroundWorkerDiagram />
          </Stack>
        </CardBody>
      </Card>

      <H2>名词白话表</H2>
      <Text tone="tertiary" size="small">点击展开各分类；遇到文档里的英文术语可先在这里查</Text>

      <CollapsibleSection title="入口与日常操作" count={GLOSSARY_CORE.length} leading={<Swatch color="blue" />} defaultOpen>
        <GlossaryTable rows={GLOSSARY_CORE} />
      </CollapsibleSection>

      <CollapsibleSection title="记忆与数据概念" count={GLOSSARY_MEMORY.length} leading={<Swatch color="green" />}>
        <GlossaryTable rows={GLOSSARY_MEMORY} />
      </CollapsibleSection>

      <CollapsibleSection title="检索与存储技术词" count={GLOSSARY_TECH.length} leading={<Swatch color="purple" />}>
        <GlossaryTable rows={GLOSSARY_TECH} />
      </CollapsibleSection>

      <CollapsibleSection title="维护与自动化" count={GLOSSARY_OPS.length} leading={<Swatch color="orange" />}>
        <GlossaryTable rows={GLOSSARY_OPS} />
      </CollapsibleSection>

      <Card>
        <CardHeader>三条日常路径速记</CardHeader>
        <CardBody>
          <Grid columns={3} gap={12}>
            <Stack gap={6}>
              <Text weight="semibold">开始干活</Text>
              <Text size="small" tone="secondary">/hm:wake → AI 拿到项目规则、交接、画像</Text>
            </Stack>
            <Stack gap={6}>
              <Text weight="semibold">查历史决策</Text>
              <Text size="small" tone="secondary">/hm:search → 先摘要，不够再 timeline / 原文</Text>
            </Stack>
            <Stack gap={6}>
              <Text weight="semibold">阶段结束整理</Text>
              <Text size="small" tone="secondary">/hm:distill → 提炼 → 自动审核 → 你看摘要纠错</Text>
            </Stack>
          </Grid>
        </CardBody>
      </Card>

      <Text tone="tertiary" size="small">
        配套 Canvas：harness-mem-completion.canvas.tsx（完成度评估）· 在 IDE 中与本文件并排打开效果更佳
      </Text>
    </Stack>
  );
}
