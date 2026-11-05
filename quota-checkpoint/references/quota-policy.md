> 本参考只在用户已授权监测或主动查询时使用。停止保存不需要读取额度；修改本技能不构成执行授权。

# 额度来源与计算

## 来源顺序与边界

1. 宿主环境实际提供的只读 `get_usage_limits`；可用性依赖当前宿主，不是所有 Codex 环境都提供。
2. 已有、已授权的 Codex 集成提供的 `account/rateLimits/read`。这是 App Server 的 JSON-RPC 方法，不是可直接调用的同名 shell 命令；没有现成连接时，不为检查额度额外搭建服务。
3. 用户刚刚提供的界面读数及可用状态，或当前环境已连接的只读界面。标注来源与时间，不能当作自动读取。

没有来源则额度未知。CLI 的 `/status` 是交互界面指令，不编造 `codex /status --json`。本技能不读取 `auth.json`、Cookie、访问令牌或私有计费接口，不用 API 美元余额或上下文占用率替代 ChatGPT Codex 额度。

账户额度由同账户多个会话共享。消耗增量是账户观测值，可能包含其他项目；预测只能保守使用，不能精确归因当前任务或保证后续单元一定能完成。

## 字段处理

- 首选非空的 `rateLimitsByLimitId`，旧 `rateLimits` 仅作兼容回退。
- 根据实际模型和返回的额度归属选择桶。多个桶归属不明时先解析或询问，不挑剩余最多的桶。`normalModelSlug` 可以辅助匹配，不能仅凭名称猜测共享/独立关系。
- 每个适用桶分别检查所有有读数的 `primary`、`secondary`，使用返回的 `windowDurationMins`；不硬编码 Plus 永远只有 5 小时和周两个限制。
- `usedPercent` 为已用，合法有限数字读数的剩余值取 `clamp(100 - usedPercent, 0, 100)`。空值、缺失或非法数字为未知；缺少第二窗口并不证明存在一个未消耗的第二窗口。
- `resetsAt` 是 Unix 秒。转换为北京时间展示，保留日期；时间已到也必须重新读取。缺失时写“重置时间未知”。
- `ordinaryUsageAllowed` 的 `false`、`rateLimitReachedType` 非空、`spendControlReached` 为 `true` 都优先进入暂停。旧/未知权限字段不能证明已恢复。
- `credits.balance`、`credits.unlimited`、`rateLimitResetCredits` 不参与普通额度预算。本技能不会消费它们。

## 计算脚本

先将当前工具结果的实际 JSON 负载写入如下观测包装。`observedAt` 必须是本次读取的真实 Unix 秒，不是旧文件的复制时间。`runKey` 在每次暂停后恢复、账户或任务类型改变时更新；`modelKey` 包含可见的模型、推理与速度设置。未知模型写 `unknown`，使用高消耗估算余量，仍允许同账户、同一轮工作内保守采样；不能据此声称已识别模型。可见设置改变时更新 `modelKey` 或 `runKey`，不要沿用之前速率。

```json
{
  "observedAt": 1793601600,
  "runKey": "task-example-run-1",
  "modelKey": "visible-model|visible-reasoning",
  "usage": {
    "ordinaryUsageAllowed": true,
    "rateLimitsByLimitId": {
      "codex": {
        "limitId": "codex",
        "primary": {"usedPercent": 40, "windowDurationMins": 300, "resetsAt": 1793619600},
        "secondary": {"usedPercent": 20, "windowDurationMins": 10080, "resetsAt": 1794000000},
        "spendControlReached": false,
        "rateLimitReachedType": null
      }
    }
  }
}
```

示例时间只供说明结构；实际运行用当前时间和工具返回值。工具外层若有 MCP `content` 文本或 JSON-RPC `result`，先提取实际额度 JSON；脚本也支持这些常见包装。

```text
python <skill-dir>/scripts/assess.py <observation.json> --control <task-dir>/control.json --unit-minutes 5 --save-minutes 2
python <skill-dir>/scripts/assess.py <observation.json> --control <task-dir>/control.json --previous <last-decision.json> --unit-minutes 3 --save-minutes 1 --heavy
python <skill-dir>/scripts/assess.py <observation.json> --control <task-dir>/control.json --stop-requested --unit-minutes 5 --save-minutes 2
```

多桶时重复 `--limit-id <已确认适用桶>`。`--pause-floor 5 --decision-at 10` 为本技能当前默认值；只有用户另行要求时才改变这两个数。旧的 `--reserve-short`、`--reserve-long` 已移除，避免把保留值与决策区间混淆。

完整输出 JSON 留在任务进度目录，用作下一次的 `--previous`；向模型只回传必要摘要。输出仅保留预算所需字段，账户 ID 只派生为短摘要用于比较同账户，原 ID 不输出。输入原始响应不应进入版本控制，保存后删除不再需要的原始响应文件。

脚本输出 schemaVersion 2，返回 `continue`、`finish_then_pause`、`pause` 或 `unknown`；正常决策均退出 0，必须读取 JSON 的 `action`。输入错误非零退出。`finish_then_pause` 只允许已绑定的当前环节收尾，不能选择下一环节；`unknown` 在工作流中转换为保存暂停。预算估计不是完成保证。

`--unit-minutes` 是当前环节剩余工作及必要验证的实际估算，不是期限。`--save-minutes` 覆盖尚欠的技术记录、总结、保存与核对，没有默认值；停止区间缺任一估算就暂停。`--control` 读取持久化 phase、pause_pending 和当前环节 ID；无控制文件时可用 `--current-unit-id`、`--pause-pending`。`--stop-requested` 在任何额度下评估停止；`--hard-stop` 和 `--phase paused/completed` 不使用读数，输出暂停且没有下次查询时间。普通高额度巡检可以不带环节估算。

计算方法：

- 读数必须不超过 120 秒；比较样本间隔为 1–30 分钟，且账户摘要、`runKey`、模型设置标记、窗口长度和重置时刻一致。
- 同窗口已用量增加时，`rate = 增量百分点 / 间隔分钟`。整数读数未变时可沿用最近 10 分钟内的正速率；下降、重置或设置改变时丢弃旧速率。没有可信速率就用初始估算，不把零增量当免费。
- 初始单元预算：普通短/长窗口分别 2/0.5 个百分点（以 5 分钟为基准），高消耗分别 3/1 个百分点（以 3 分钟为基准），随单元时长缩放。这是进入决策区间后的启发式预算，尚无长期消耗实测保证。
- 有可信速率时，普通用 2 倍、高消耗用 3 倍速率估算；最小单元预算普通短/长为 0.5/0.25、高消耗为 1/0.5 个百分点。保存预算为同一保守每分钟速率乘实际保存分钟数，至少 0.25 个百分点；无实测速率时采用上述初始每分钟估算。`--resuming` 加入当次恢复成本，普通至少 0.5、高消耗至少 1 个百分点，有速率时至少覆盖约 1 分钟。实际更大的恢复成本另计入剩余工作估算，不降低标准。
- **高于 10% 且没有待暂停要求：** 成本预测只指导提前保存，不因环节大主动暂停或缩水。估算时长没有 30 分钟上限。
- **任一窗口高于 5%、不超过 10%，或已有停止请求：** 锁定当前环节，只有每一个适用窗口均满足 `remaining > 5 + unit_cost + save_cost + resume_cost`，且当前环节和估算完整，才返回 `finish_then_pause`。预算包含其他高于 10% 的窗口，不只检查低值窗口。相等视为不足。不足则 `pause`；无已开始环节不能新开一个。**不超过 5%：** 保存暂停。
- `pausePending` 一旦出现就写入控制状态；每次评估都读取控制状态，额度恢复不能取消它。完成该环节后转换 paused；只有明确继续才清除。服务端禁止和未知状态优先保存。
- 仅在启用后：最低剩余高于50%每20分钟，高于20%至50%每15分钟，高于10%至20%每5分钟，高于5%至10%仅在收尾期间每3分钟。正式暂停后没有下一次查询；高消耗模式不改变周期。

## 资料与实际验证范围

额度字段初次核查日期：2026-11-02；本轮行为更新：2026-11-05。以下为可维护来源，未来工具与字段变化时优先实际工具声明。

- [OpenAI：App Server 的额度读取与字段](https://learn.chatgpt.com/docs/app-server)：确认 JSON-RPC 读取、多个额度桶、已用百分比和 Unix 秒时间。
- [OpenAI：Codex 额度与任务消耗](https://learn.chatgpt.com/docs/pricing)：消耗受模型、上下文、推理和任务复杂程度影响，不能固定换算分钟数。
- [OpenAI：技能发现与调用](https://learn.chatgpt.com/docs/build-skills)：技能通过描述自动选择，也可显式调用；本身不是后台调度器。
- [openai/codex：账户额度响应定义](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/GetAccountRateLimitsResponse.ts)：明确普通使用权限未知时不能仅由百分比/重置时间推断恢复。
- [openai/codex：额度桶类型](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/RateLimitSnapshot.ts)：交叉核对模型别名、支出控制等字段。
- [CodexBar：Codex 数据源说明](https://github.com/steipete/CodexBar/blob/main/docs/codex.md)：客观参考其区分远端额度和本地消耗记录的设计；未安装、未复用其认证或抓取流程，也未验证其运行效果。

5%–10% 是本技能的默认决策区间，使用者可明确调整；速率倍数、冷启动预算和复查间隔仍是设计选择。该区间比旧版本更充分使用额度，也减少了突发限额时的余量，因此持续保存尤其必要；它不是保证能在耗尽前保存的硬限制。后续根据真实观测调整估算，保持原验收标准与用户指定区间。
