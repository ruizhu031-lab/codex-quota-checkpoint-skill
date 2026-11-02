# Codex 额度监测与断点续接 Skill

**手动开启额度监测，停止时保存真实进度，继续时依据原始要求和验证证据恢复完整项目。**

[English](README.md) · [技能入口](quota-checkpoint/SKILL.md) · [额度规则](quota-checkpoint/references/quota-policy.md) · [检查点格式](quota-checkpoint/references/checkpoint.md)

仓库名：`codex-quota-checkpoint-skill`；安装目录和调用名：`quota-checkpoint` / `$quota-checkpoint`。

适合 Codex 大型项目、长时间任务、可能跨额度窗口的工作，以及需要主动“停止保存 / 继续恢复”的场景。项目再大、工作再久、模型再昂贵，都不会自行开启监测。

这是 **Codex 工作流程技能 + 本地 Python 辅助脚本**，不是后台定时器、计费客户端或硬性限额拦截器。Python 脚本不获取真实账户额度；实时读数依赖宿主已经提供的只读工具，缺少工具时不能凭空推测。

## 功能概览

| 功能 | 具体行为 |
| --- | --- |
| 明确启动 | `allow_implicit_invocation: false`，关闭自动发现；首次显式调用后才处理操作命令 |
| 低频监测 | 额度高于 50% 时，每连续主动工作 15 分钟复查；低额度时再收紧 |
| 额度不足暂停 | 进入 5%–10% 判断下一完整环节是否够用，到 5% 保存并暂停 |
| 用户主动停止 | 不论是否开启监测、额度多少，优先保存，不先查额度或继续推进功能 |
| 版本化交接 | 保存原始要求、关键决策、证据、待办、下一步、产物指纹和可用的 Git 现场 |
| 核对后续接 | 先检查真实文件、用户新改动、运行任务和外部副作用，再继续原完整计划 |
| 保留原范围和质量 | 不因项目或环节大而减功能、降深度、降低模型/推理强度或跳过必要验证 |

## 安装

需要支持本地文件技能的 Codex 环境。辅助脚本需要 Python 3.10+；Git 可选。实时监测还需要宿主可用的额度读取工具；**没有实时额度工具仍可使用停止保存和项目恢复流程**。

### 通过 Codex 安装

在提供 `$skill-installer` 的 Codex 环境中输入：

```text
使用 $skill-installer 安装这个仓库中的 quota-checkpoint 技能：
https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/tree/main/quota-checkpoint
```

### 手动安装

克隆或下载本仓库，将完整的 **`quota-checkpoint` 文件夹**复制到宿主支持的技能目录，保留 `agents/openai.yaml` 和目录名。

当前官方文档列出个人目录 `~/.agents/skills` 和项目目录 `.agents/skills`。部分桌面版本或内置安装器使用 `$CODEX_HOME/skills` / `~/.codex/skills`；以实际宿主支持的位置为准，避免安装重复副本。

Windows PowerShell 示例：

```powershell
git clone https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill.git
$skillDestination = Join-Path $env:USERPROFILE '.agents\skills\quota-checkpoint'
if (Test-Path -LiteralPath $skillDestination) {
    throw '目标已存在，请先检查旧版本，不要直接覆盖。'
}
New-Item -ItemType Directory -Path (Split-Path -Parent $skillDestination) -Force | Out-Null
Copy-Item -LiteralPath '.\codex-quota-checkpoint-skill\quota-checkpoint' -Destination $skillDestination -Recurse
```

macOS / Linux 的复制示例见 [English README](README.md#manual-installation)。若未显示技能，开始新会话或重启 Codex。安装完成不代表开启监测，仍须明确调用。具体规则见 [OpenAI 官方技能文档](https://learn.chatgpt.com/docs/build-skills)。

## 命令用法

### 开启本项目额度监测

```text
使用 $quota-checkpoint，开始自动监测当前项目额度。
保持原模型、推理强度、完整交付范围和验收标准。
```

启用时取得一次基线，保存本项目授权状态，之后按周期检查。不会注册系统服务或定时自动化，不会把授权传播到其他项目。

### 只停止保存，不开启监测

```text
使用 $quota-checkpoint 停止工作并保存进度，不查询额度，不开启监测。
```

技能已加载的同一项目会话中，可以直接说“停止工作”“暂停项目，保存进度”。新聊天未加载技能时，仅说“停止工作”不能保证宿主会加载本技能，因此首次应带 `$quota-checkpoint`。

停止命令优先于额度判断；在宿主能够处理指令的第一个边界停止推进。不会先做一轮查询、继续修一个问题或开启新测试。未做验证明确保留为未验证，恢复后补齐。

### 继续工作

```text
使用 $quota-checkpoint，从 <检查点目录> 恢复项目。
核对真实文件和原始资料，继续全部待办和必要验证，保持原要求与质量。
```

“继续”不新增监测授权；只恢复此前明确开启且未关闭的监测。旧进度没有授权状态时默认关闭。重新核对用户改动和外部副作用，避免覆盖新工作或重复部署、发送、提交等操作。

### 关闭监测但继续项目

```text
关闭本项目额度监测，项目工作继续。
```

### 只讨论技能，不运行

```text
检查或修改 quota-checkpoint 技能。本次不要执行监测、停止或恢复流程。
```

讨论、举例、引用命令以及否定指令，均不当作项目操作命令。

## 检查频率与暂停阈值

取当前模型**已确认适用窗口中最低的剩余百分比**，不硬编码账户永远只有某两个窗口：

| 最低剩余额度 | 连续主动工作后的复查周期 |
| --- | --- |
| 高于 50% | 15 分钟 |
| 高于 25%、不超过 50% | 10 分钟 |
| 高于 10%、不超过 25% | 5 分钟 |
| 高于 5%、不超过 10% | 3 分钟 |
| 不超过 5% | 保存并暂停 |

暂停、等待用户、纯下载或外部构建等待不计入主动工作。检查到期后在最近可执行边界进行，不保证中断一次长推理或工具调用。高消耗模式只扩大估算余量，不擅自加密为每分钟查询。用户主动要求、实际限额错误或明确更改模型/速度/并发设置时，可以额外复查一次。

- **高于 10%：** 继续原完整工作；预算估计只提示提前保存，不能变成缩水或升高暂停阈值的理由。
- **高于 5%、不超过 10%：** 判断下一完整环节、保存及必要恢复开销是否足够，同时保留 5% 底线；不够则保存暂停，不能通过少做内容把“不够”变成“够”。
- **不超过 5%：** 保存并暂停，不开新环节。
- **服务端限额或额度未知：** 先保存并说明缺失项，不伪造余额、不无限重试。到重置时间不等于已经恢复。

账户读数可能包含其他会话消耗，预测不是对当前项目的精确归因。预算、倍数和时间间隔是可解释的默认策略，不能保证一次长请求必定够用。阈值可以由使用者明确调整。

## 保存内容与恢复质量

交接保存全部原始目标与验收标准、已完成和待办、关键决策和依据、否定方案、原始资料、验证命令及结果、准确下一步、模型配置、运行任务和外部副作用。

项目进度目录通常为：

```text
.codex-progress/<task-id>/
├── control.json       # 由代理按规则维护：监测授权、计时及最近命令
├── LATEST
└── <version>/
    ├── state.json
    ├── HANDOFF.md
    └── manifest.json  # 文件SHA-256和可用的Git现场
```

辅助脚本先发布完整版本，再替换 `LATEST`；写入或发布失败时尽量保留旧检查点。核验能报告文件变化或缺失，不覆盖用户改动。`control.json` 由代理依据参考格式单独维护，脚本不是状态守护进程。

**检查点不是项目文件备份或进程内存快照。** 实际文件也必须落盘；换机器、换目录时应同时带走项目文件与进度目录。不会自动提交 Git、推送或上传用户项目。原模型不可用或确实需要改变范围时由用户选择，不静默降级。恢复质量依赖原始资料和可验证现场，不能承诺与未中断运行完全等价。

## 脚本、隐私与验证

`scripts/assess.py`：从已有新鲜读数计算 `continue` / `pause` / `unknown` 与下次周期，不联网获取额度。正常决策均以退出码 0 返回，必须读取 JSON 中的 `action`；输入错误返回非零退出码。`--unit-minutes` 是成本估算，不是强制截止时间。

`scripts/checkpoint.py`：保存版本化交接、计算关键产物指纹、记录只读 Git 现场，并在恢复时核验。输入格式及命令见 [额度参考](quota-checkpoint/references/quota-policy.md) 和 [检查点参考](quota-checkpoint/references/checkpoint.md)。

不读取 `auth.json`、Cookie、API Key 或私有计费接口，不购买额度、不使用重置券、不切换账户。进度和完整额度观测默认留在本地；提交项目之前请检查交接记录是否包含私密内容。技能不会擅自修改用户项目的 `.gitignore`。

在仓库根目录运行：

```text
python -B -X utf8 -m unittest discover -s quota-checkpoint/tests -v
```

51 项测试方法覆盖额度、多窗口、过期数据、取整、模型变化、频率边界、文件核验、保存失败及范围保留标志。使用模拟数据和隔离文件，不读取真实账户额度；没有 Git 时会跳过一项 Git 专用测试。GitHub Actions 配置 Linux / Windows 测试。

这些测试不等于真实的自然语言触发验证、额度耗尽实测、精确定时保证或恢复质量等价实验。该项目与 OpenAI 无隶属关系，不是官方插件。

## 参与与许可

改动或提交问题前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。不要在公开 Issue 中贴出真实账户 ID、原始额度响应、令牌或私人项目交接记录。

采用 [MIT License](LICENSE)，版权归 2026 ruizhu031-lab。允许使用、修改、分发和商用，须保留版权和许可声明。

相关资料：[官方技能机制](https://learn.chatgpt.com/docs/build-skills)、[官方 App Server 额度协议](https://learn.chatgpt.com/docs/app-server)、[官方额度与消耗说明](https://learn.chatgpt.com/docs/pricing)。

关键词：Codex skill / agent skills / quota monitoring / usage limits / rate limits / checkpoint / pause resume / context preservation / 额度监测 / 断点保存 / 暂停继续 / 项目续接。
