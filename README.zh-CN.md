# Codex 额度监测、完整技术记录与项目续接技能

**主动调用后自动监测额度，持续保存工作细节，暂停或上下文压缩后按原范围与标准继续。**

[English](README.md) · [技能规则](quota-checkpoint/SKILL.md) · [额度计算](quota-checkpoint/references/quota-policy.md) · [完整恢复流程](quota-checkpoint/references/recovery.md)

[![Tests](https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/actions/workflows/tests.yml/badge.svg)](https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/actions/workflows/tests.yml) [![MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`quota-checkpoint` 用于大型、长时间 Codex 项目。只有你主动调用后，它才监测额度，同时持续记录原始要求、工程细节、重要决定、验证证据与准确断点。它不会因为项目大、工作久、模型贵或发现旧检查点而自动启动。

完整交付范围、技术深度、模型与推理设置、必要验证和验收标准始终保留。项目或某个环节太大时，额度不够就记录并等待，不能通过缩水、降低标准或用草稿替代成品完成。

这是技能指令与本地 Python 辅助工具的组合。额度检查由 agent 在工作边界调用宿主只读工具完成，脚本不登录账户、不读取凭据、不自行联网查额度，也不是后台定时服务。可选恢复钩子只处理明确绑定的项目会话。

## 安装

需要支持本地技能和显式调用的 Codex 环境，以及 Python 3.10+。Git 可选；实时监测需要宿主提供受支持的只读额度工具。缺少额度工具时仍可直接保存现场，但不能保证预算足够完成收尾。

可以对带有安装器的 Codex 说：

```text
使用 $skill-installer 安装这个仓库中的 quota-checkpoint：
https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/tree/main/quota-checkpoint
```

也可以克隆/下载仓库，只复制包含 `SKILL.md` 与 `agents/openai.yaml` 的 `quota-checkpoint` 文件夹。官方文档列出个人 `~/.agents/skills` 和项目 `.agents/skills`；部分桌面版本/安装器使用 `$CODEX_HOME/skills` 或 `~/.codex/skills`，以实际发现目录为准，避免装两份。已有版本先备份、比较后更新，不盲目覆盖。

[英文说明](README.md#manual-installation)提供 Windows、macOS/Linux 复制命令。安装后可新开会话或重启让技能重新发现。**安装不启动监测，也不会给项目注册钩子。**

## 如何调用

启动当前项目：

```text
$quota-checkpoint
```

这会自动开启监测、取得一次真实额度基线、创建或续写详细技术文档，并准备本项目的恢复索引/钩子。保存任务、授权、实际会话绑定及当前完整环节的验收要求。

普通停止：

```text
停止工作，保存进度。
```

立即进入停止流程：先记录当前断点和待暂停状态，再估算当前已经开始的环节还需多少工作、必要验证、技术记录更新、最终总结和保存成本。每个适用窗口保留 5% 底线，足够就只完成这个环节后暂停；不足、未知或没有正在做的环节则直接保存暂停。不能开始下一环节，额度中途恢复也不取消停止要求。

需要立刻保存而不继续当前环节时：

```text
不要继续当前环节，立即保存暂停，不查询额度。
```

恢复：

```text
使用 $quota-checkpoint，从 <检查点目录> 继续工作。
先核对完整原始要求、相关技术记录原文及验证证据，再推进。
```

技能先核对现场、用户新修改、原决定、准确断点、全部待办、测试证据、运行任务和外部操作，填写具体恢复记录。此前监测开启且未关闭时，在推进前重新读额度。预计重置时间、打开聊天或上下文压缩都不等于用户说“继续”。

其他命令：

```text
关闭额度监测，但继续工作并维护技术记录。
检查或修改 quota-checkpoint，本次不要执行它。
```

关闭监测不取消已经收到的停止要求。示例、引用、否定和技能修改不会执行监测。新聊天要显式带 `$quota-checkpoint` 并指出任务；单独说“停止工作”不保证宿主加载显式技能。

## 监测频率

使用所有**已确认适用窗口**中的最低剩余百分比：

| 剩余额度 | 主动工作后的复查周期 |
| --- | --- |
| 高于 50% | 20 分钟 |
| 高于 20%、不超过 50% | 15 分钟 |
| 高于 10%、不超过 20% | 5 分钟 |
| 高于 5%、不超过 10% | 只允许当前环节收尾，期间每 3 分钟 |
| 不超过 5% | 保存并暂停 |

边界明确：50% 用 15 分钟，20% 用 5 分钟，10% 进入收尾评估，5% 直接保存。主动时间不包含等用户、暂停和纯外部构建/下载等待；到期在最近可执行边界检查，不能保证打断一个长推理或不可中断工具调用。

高于 10% 且没有停止要求时，继续完整工作；大环节可以提前保存，不能因此提前提高暂停门槛或缩水。进入区间或收到普通停止命令后，评估**当前环节**，不是新开下一个。每个窗口都须足够支付剩余工作和保存成本并保留 5%；相等视为不足，估算或环节身份不明也保存。

正式暂停后没有每 3 分钟轮询，没有自动复工。等待用户明确继续。高消耗模式只增加估算余量，不降低模型，也不加快查询。明确要求立即查询、实际限额错误或刻意变更模型/速度/并发可额外读取一次。

额度是账户共享观测，可能含其他聊天消耗；预测为保守估计，不能准确换算“还能工作几分钟”，也不是 OpenAI 的完成保证。不消费额外点数、不买额度、不兑换重置券、不换账户。

## 完整技术文档保存什么

从启用开始持续记录：

- 原始目标、最新要求、全部交付物与验收重点。
- 工作步骤、重要修改、文件/接口/参数、准确断点和所有待办。
- 设计决定、依据和原始资料、否定方案及原因。
- 命令、结果、失败与解决过程、通过/失败/未验证证据。
- 当前环节完成条件、模型/推理设置、下一步、运行任务和外部副作用。

重要结果及时追加，有未记录进展时最迟约 5 分钟主动工作后的可执行边界补写。完整检查点按里程碑、暂停前及约 15 分钟主动工作更新；保存不附带查额度。

任务目录 `.codex-progress/<task>/` 中的 `TECHNICAL_LOG.md` 是完整技术文档；原文同时保存在有指纹链的 `journal/` 条目中。新摘要不替代旧细节，更正采用追加记录。同一事件重复提交相同正文不会重复写入，改写已有事件会被拒绝。

Markdown 视图损坏时，可从校验通过的原始链重建全部正文；原始链损坏会明确报告，不凭摘要补造。长输出保存为本地证据并引用，恢复时按需读原文。agent 负责持续记录有意义的工程信息，脚本不会自动捕获所有工具输出或整段聊天。

检查点包含 state、HANDOFF、manifest 和已有控制状态副本，保存要求、决定、待办、文件指纹、Git 现场及对应技术日志链头。**它不是项目源码或进程内存的备份。**实际工作文件也须保留，迁移时带走整个进度目录和真实项目文件。

## 上下文压缩后如何找回细节

三层保护：

1. 详细原文落盘保留，不能因为压缩对话而删减或用摘要覆盖。
2. 项目 `AGENTS.md` 增加有标记边界的恢复索引，保留已有内容；索引不授权其他会话监测或自动恢复。
3. 支持的宿主上配置项目级 `PreCompact` 与 `SessionStart(compact/resume)` 钩子，匹配明确绑定的真实会话。

压缩前钩子核验已有记录并标记需要恢复核对；压缩后在下一次模型请求前重新提供文档位置和读取要求。钩子只做短暂本地操作，不查询额度、不调用新模型、不自行复工，也不能替 agent 写出尚未落盘的工程结论。日志内容不会被直接提升为 developer 指令。

新建或改过的钩子必须在 **Settings > Hooks** 或 **`/hooks`** 中审阅并信任，可能还需重载会话。配置工具只报告待信任，不改信任数据库、不绕过审批。缺少会话 ID 或宿主不支持时使用文档与索引，并说明增强钩子未生效。`AGENTS.override.md` 遮蔽索引或已有 inline Hooks 时，必须明确处理，不能假装已接入。

压缩后即使聊天摘要看起来够用，也先核对完整要求、关键决定、当前环节、断点、待办、验证证据、实际文件及外部操作。缺失或矛盾先找原始依据，找不回则明确说明，不能猜测推进。原本收尾仍只完成原环节再暂停；原本暂停仍等你说继续。

**能保护已经保存的详细原文，并建立强制恢复流程；不能承诺文档全文永久驻留模型上下文、挽回从未保存的信息、保证每个宿主都执行钩子，或证明压缩前后模型理解和输出完全一致。**完整范围与质量要求不会因此降低。[恢复机制与命令](quota-checkpoint/references/recovery.md)说明了实际边界。

恢复校验会拒绝日志回退或分叉；缺少日志链头时，不覆盖已经存在的技术文档。恢复确认绑定实际读过的证据，确认期间文件发生变化就要求重新核对。首次检查点保存失败后，可以用原输入安全重试，成功之前不能推进项目。同一聊天中已完成的任务不会阻挡后续明确启用的新任务。故障处理步骤见[完整恢复流程](quota-checkpoint/references/recovery.md)。

## 辅助命令与旧版本兼容

```text
python <skill-dir>/scripts/assess.py <observation.json> --control <task-dir>/control.json --unit-minutes 8 --save-minutes 2
python <skill-dir>/scripts/checkpoint.py append <event.md> --event-id <unique-id> --root <project> --task <task-id>
python <skill-dir>/scripts/checkpoint.py save <state.json> --root <project> --task <task-id>
python <skill-dir>/scripts/checkpoint.py verify --root <project> --task <task-id>
python <skill-dir>/scripts/workflow.py recover --root <project> --task <task-id>
```

`--unit-minutes` 是剩余完整工作及必要验证的估算，不是限时；`--save-minutes` 包括技术记录、总结和保存。缺估算不擅自猜默认值。assess 输出版本 2，结果为 continue、finish_then_pause、pause、unknown；正常判断退出码均为 0，**必须读取 JSON action**。

工作流持久保存环节与待暂停状态，禁止停止期间选择其他环节；明确恢复前要求针对当前指纹填写具体核对记录。文件变动让旧确认失效。指纹证明文件状态，不能证明 agent 已理解全部事实。

旧检查点保持可读；明确迁移会保留旧版本、写入已知历史并标明缺口，不能把旧摘要缺失的细节说成已经找回。配置生成保留原规则和其他钩子，运行配置含本机 Python/脚本路径，移动安装位置后应重新生成、审阅。

## 额度开销、隐私与限制

- 文档增量记录和恢复重读会消耗一定额度；本地渲染、校验和钩子不额外调用模型。没有固定开销比例保证，通过局部追加和按需读取控制成本。
- 记录、证据及原始额度数据默认在本地，不自动提交或上传。提交项目时审查进度目录；技能不会擅自改项目 `.gitignore`。
- 不读取密钥、Cookie、凭据或整份环境变量，不保存隐藏思维链，不安装私有额度接口。
- 长调用、额度突发耗尽、进程/磁盘故障、权限、钩子超时均可能影响及时保存。失败和未验证能力必须如实报告。
- 只协调本项目可控制的任务，不自动停止其他项目或聊天。
- 这是独立开源技能，不是 OpenAI 官方额度保障服务。

## 测试与贡献

```text
python -B -X utf8 -m unittest discover -s quota-checkpoint/tests -v
```

测试使用模拟额度和隔离目录，覆盖阈值、所有窗口预算、停止状态持久化、大环节不缩水、文档成本、原文保留、日志回退/分叉、既有文档保护、初始化失败重试、恢复确认期间的用户改动与中断、指纹、旧版迁移、钩子会话隔离、已完成任务隔离与配置合并，以及无聊天摘要的新进程恢复。CI 覆盖 Linux/Windows × Python 3.10/3.13。Git 或符号链接能力不可用时跳过相应测试。

模拟事件和文件测试不是实际宿主压缩、自然语言执行或模型质量完全相同的证明。实际钩子信任和事件触发需在目标宿主验证，不混报结果。参见[贡献说明](CONTRIBUTING.md)。

## 开源许可与资料

采用 [MIT](LICENSE)，Copyright 2026 ruizhu031-lab，允许依许可复用、修改、分发和商用；本项目与 OpenAI 无隶属关系。

[官方技能文档](https://learn.chatgpt.com/docs/build-skills)、[额度协议](https://learn.chatgpt.com/docs/app-server)、[额度说明](https://learn.chatgpt.com/docs/pricing)、[Hooks](https://learn.chatgpt.com/docs/hooks)、[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[上下文压缩机制](https://openai.com/index/unrolling-the-codex-agent-loop/)。

检索关键词：Codex skill、agent skills、quota monitoring、rate limits、checkpoint、pause resume、technical work log、context compaction、context recovery、context preservation；Codex 技能、额度监测、断点续接、技术记录、上下文压缩恢复。
