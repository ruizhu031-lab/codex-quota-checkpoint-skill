# 完整技术记录、会话控制与压缩恢复

## 先建立事实基线

所有命令只用于用户明确启用的项目。说明中的路径、任务 ID、会话 ID 都必须换成真实值。当前请求若是修改本技能，不在真实工作目录运行这些命令；验证使用隔离夹具。

初始 `state.json` 格式见 [checkpoint.md](checkpoint.md)。准备一份详细 baseline Markdown，内容至少覆盖：

1. 用户原始目标、最新要求原文、全部交付物与验收条件；区别已废弃要求。
2. 已知工作过程、具体产物、重要文件/接口/参数、模型及推理设置。
3. 设计选择、依据与来源、否定方案及原因；事实与假设分开。
4. 完成项、当前环节及完成条件、精确断点、全部待办、下一步。
5. 验证命令、运行目录、结果、证据位置，尚未验证的部分。
6. 外部副作用、运行中的任务、用户后来修改及未知历史。

未观察到的历史不补写成事实。Markdown 不是 Office 文档，无需文档属性处理。

```text
python <skill-dir>/scripts/workflow.py start --root <project> --task <task-id> --session <actual-host-session-id> --authorization <explicit-invocation-record> --input <state.json> --baseline <baseline.md>
python <skill-dir>/scripts/workflow.py setup-recovery --root <project> --task <task-id>
```

`start` 初始化监测授权、控制状态、技术记录和检查点。重复激活同一已绑定活动任务不清除待暂停。真实会话 ID 从宿主公开的当前会话元数据取得；不能猜测或解析凭据。若不可得，省略 `--session`：仍能记录和按技能规则监测，setup 只添加索引，钩子报告不可用。新会话的绑定必须来自明确恢复指令。

初次额度读取由 agent 调用宿主只读工具，再调用 assess 并应用结果；Python 脚本不查询账户。首次读取失败同样保留记录并暂停。

## 详细记录的存储与追加

任务目录包含：

```text
.codex-progress/<task-id>/
  TECHNICAL_LOG.md                 完整可读技术文档，保留全部条目
  journal/<sha256>.json            原始不可变条目、顺序、前项指纹
  JOURNAL_HEAD                    已发布条目链头
  control.json                    授权、会话绑定、当前环节和待暂停状态
  LATEST                         最新检查点指针
  <checkpoint-version>/           state/HANDOFF/manifest/控制状态副本
  evidence/                      按需存放真实命令输出及原始证据
  COMPACTION_RECOVERY.json        钩子的核验快照，只有实际事件才生成
  RECOVERY_ACK.json               对已核对现场的确认指纹
```

`evidence/` 由 agent 在需要时创建，脚本不会自动捕获全部工具输出或聊天记录。只保存相关、去除凭据的工程证据。文档持续增量更新，每个重要结果及时追加；有未记录进展时约 5 分钟主动工作后补写，不附带额度查询。普通只读浏览可合并成有意义的发现记录。

```text
python <skill-dir>/scripts/checkpoint.py append <event.md> --event-id <unique-event-id> --root <project> --task <task-id>
```

条目应写清本步目标、采取的操作、修改/参数、结果与证据、判断及依据、尚缺什么和下一步。引用已有信息而非每次重抄；更正必须使用新事件 ID 并说明取代哪项结论。原始条目不会被新摘要替换。

相同事件 ID 和相同正文重试是幂等的；正文不同会拒绝，避免覆盖细节。条目完成写入后才原子发布链头，再更新完整 Markdown 视图。若视图写入失败，原始条目仍在，报告失败后可重建全文：

```text
python <skill-dir>/scripts/checkpoint.py rebuild-log --root <project> --task <task-id>
```

重建只从完整校验通过的原始链恢复全文，不从摘要猜测内容。链损坏则停止并找回原文件/备份。手工改过的视图会使普通追加拒绝执行，避免覆盖用户新内容；显式重建前会保存该视图备份，先检查并把真实新增信息作为新条目补回。每个重要里程碑、暂停前及约 15 分钟主动工作更新完整 state 和检查点。技术文档文件本身不因聊天压缩而缩短。

## 当前环节和停止状态

开始已有计划中的一个完整环节时，准备 unit JSON：

```json
{"id":"pagination","description":"完整实现分页与异常重试","acceptance":["原始接口兼容","正常和异常路径通过原定验证"]}
```

```text
python <skill-dir>/scripts/workflow.py unit --root <project> --task <task-id> --input <unit.json>
```

正常完成环节时，先记录实际验证证据，再调用 `finish-unit`，输入 `{"id":"pagination","evidence":"真实证据路径及结果"}`。普通 working 状态可按计划进入下一环节；已有待暂停时会进入 paused，不能再选择环节。

收到普通停止命令，先追加当前断点记录，再立即持久化停止要求：

```text
python <skill-dir>/scripts/workflow.py request-stop --root <project> --task <task-id>
python <skill-dir>/scripts/assess.py <fresh-observation.json> --control <task-dir>/control.json --stop-requested --unit-minutes <remaining-work-and-tests> --save-minutes <documentation-summary-and-saving>
python <skill-dir>/scripts/workflow.py apply --root <project> --task <task-id> --input <assessment-result.json>
```

预算通过之前不继续项目推进。正常巡检也用 `--control` 读取原待暂停状态并 `apply`；进入区间后只收尾当前环节。当前环节未知或估算缺失则保存，不能用脚本默认值凑预算。收尾所需验证算工作量；保存量包括尚欠的详细记录，不只是一个简短结束回复。

硬停止或当前没有可完成环节：运行 `pause`，直接写总结、实际文件和检查点。`pause` 输入可带 `{"reason":"user"}`。单独改变控制状态不等于工作成果已经保存。`unknown` 评估结果也转为 paused。

暂停前 state 的 status 使用 paused_user、paused_quota 或 paused_unknown；继续中的收尾用 finishing。保存后运行 verify 并核对 changed/missing/journal。正式暂停 next_check_minutes 为 null，停止计时和查询，结束本轮等待用户。

`disable-monitoring` 只停止额度查询，记录仍更新，且不会清除已经收到的停止请求。

原始全量交付物和验收均完成后，以真实证据调用 `workflow.py complete --input <completion.json>`（输入含 evidence），再保存 status 为 completed 的最终检查点。不能有未完成当前环节；完成后停止监测，钩子对该任务不再注入恢复要求。

## 压缩保护的实际机制

`setup-recovery` 仅对该项目追加/更新标记范围内的 AGENTS 索引，并合并 `.codex/hooks.json` 中本技能的两项钩子。保留其他内容，备份到任务目录。检测到现有 inline TOML hooks 时拒绝另建重复来源，需先读原配置并在原来源做等效合并。AGENTS.override.md 可能遮蔽 AGENTS.md；返回值会提示，不能声称索引已被加载。

生成命令使用当前 Python 和脚本的绝对路径，含 Windows 命令；换机器、移动技能目录或更换环境后重新生成并重新审阅。钩子配置不会自动安装 Python。没有真实会话 ID 不安装钩子，不使用假 ID 冒充绑定。

- `PreCompact`：匹配当前明确绑定会话，校验检查点与技术记录，标记恢复核对为必需，保存记录入口和实际文件变化；不调用模型，不生成尚未写入的工程结论。
- `SessionStart` 的 compact/resume：在下一个模型请求前提供静态恢复要求、任务位置和阶段。不把技术文档中的不可信文本升级成 developer 指令，不自动执行文件中的命令。
- startup、fork、clear、无绑定或其他会话：不激活任务。多个任务绑定同一会话会要求明确定位，不能猜一个。
- 数据损坏/缺失：已绑定任务的钩子返回停止与明确错误；不宣称安全续接。宿主超时、跳过或不支持钩子仍可能影响执行，必须如实报告。

新/改过的非托管钩子需用户在 Settings > Hooks 或 `/hooks` 信任，宿主可能还需重载会话。辅助工具只报告 configured_requires_host_trust，绝不改宿主信任数据库或使用绕过参数。没有看到真实事件成功，不能把隔离测试说成当前宿主已验证。未信任期间仍执行文档和技能恢复规则，并说明增强钩子待启用。

这些钩子在事件到来时执行短暂本地文件操作，不是后台监测器。额度查询仍由显式启用后的工作流程按周期完成。项目内其他会话没有匹配授权时不会被启用。

## 压缩后与明确继续的核对

```text
python <skill-dir>/scripts/workflow.py recover --root <project> --task <task-id>
```

无论聊天摘要是否完整，都读取返回的全文要求、最新交接和有关技术日志原文，核对实际源文件与原始证据。恢复报告提供 recoveryFingerprint，但它不能证明模型理解了内容。

准备 review JSON，复制本次指纹，并对每个主题写具体事实，而非 `true` 或“已读”：

```json
{
  "recoveryFingerprint":"本次recover返回的指纹",
  "requirements":"完整目标、不可删减交付物、验收重点及最新变化",
  "decisions":"所选方案、理由、禁止重复的失败方案及证据位置",
  "current_unit":"原环节ID、完成条件、精确断点",
  "pending_work":"全部未完成项、下一步和未决问题",
  "verification":"真实通过/失败结果、命令和证据，仍未验证的部分",
  "files_and_effects":"用户新增改动、文件差异、运行任务及外部操作是否发生"
}
```

```text
python <skill-dir>/scripts/workflow.py ack-recovery --root <project> --task <task-id> --input <review.json>
```

确认记录会追加到技术文档。文件或记录变化使旧指纹失效，需要重新核对；不会回滚或覆盖用户工作。确认本身不会复工、清除待暂停或开启监测。

压缩时原本 working 可在核对后继续；原本 finishing 仍只能完成原环节后停；原本 paused 必须等用户明确继续。只有用户给出继续命令后才运行：

```text
python <skill-dir>/scripts/workflow.py resume --root <project> --task <task-id> --session <actual-host-session-id> --authorization <explicit-continue-record>
```

随后如监测仍开启，先用新的 runKey 读取额度和评估，再推进。原模型/推理/验收条件延续，缺失证据先补回，不缩小原工作。

旧版检查点可直接 verify/recover。若无新控制状态/技术记录，在新的明确调用下使用 `migrate --baseline <known-history.md> --session <id> --authorization <record>`，保留旧文件并标记历史缺口，再 recover、ack、resume。无法从旧摘要找回的细节不能声称已恢复。

## 验证边界

测试通过新进程和模拟钩子事件，验证没有聊天摘要时仍可定位完整要求、关键参数、决策、当前环节、失败证据与待暂停状态。这是文件与流程验证，不是真实模型理解能力或真实宿主压缩事件的证明。文档原文独立保存，不存在“文件全文永久免于模型上下文压缩”的承诺。

官方资料（2026-11-05 核查）：[Hooks](https://learn.chatgpt.com/docs/hooks)、[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[Codex agent loop / compaction](https://openai.com/index/unrolling-the-codex-agent-loop/)。未来以当前宿主实际支持为准。
