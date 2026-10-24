# 主流 AI 编程 Agent 的 Shell/Bash 权限系统调研 — 2026-10

> 目的：为我们的"项目构建 agent"（shell 只用于脚手架类命令 + demo 生成）设计白名单，调研各家产品的权限档位、白名单/黑名单语法、高风险命令判定方式与体验取舍。
> 事实基准：各产品官方文档 / 官方仓库。Claude Code 用 code.claude.com 官方文档（v2.1.x，演化很快）；Codex 官方站 developers.openai.com 在本环境 403，改用其 GitHub 仓库文档镜像（mintlify.wiki，生成自 openai/codex commit 6a673e7）+ 一篇中文二手综述交叉验证（已标注）；其余均为官方站。
> 检索日期：2026-10-23。

---

## 0. TL;DR 总览

| 产品 | 权限档位 | 白名单/黑名单语法 | 高风险判定 | 默认松紧 |
| :--- | :--- | :--- | :--- | :--- |
| **Claude Code** | 6 档 mode：`default`(Manual)/`acceptEdits`/`plan`/`auto`/`dontAsk`/`bypassPermissions` | `settings.json` 的 `allow`/`ask`/`deny` 规则：`Bash(npm run *)` 文本通配，`deny>ask>allow` 固定顺序 | **静态 + LLM 双层**：内置只读命令集、protected/critical path 形态学检查（rm 系）；auto 模式由第二个模型当"分类器"逐动作审查（有公开的 block/allow 规则清单） | v2.1.283+ 交互会话默认 `auto`（LLM 审查代替人工） |
| **Codex CLI** | 两旋钮正交：sandbox（`read-only`/`workspace-write`/`danger-full-access`）× approval（`untrusted`/`on-request`/`on-failure`/`never`） | Starlark `prefix_rule()`：`allow`/`prompt`/`forbidden`（最严者赢）；Beta permission profiles（路径 `read`/`write`/`deny` + 域名 allowlist） | **纯静态 + OS 沙箱**（Landlock+seccomp / Seatbelt / Windows restricted token）；无 LLM 判定层 | 有 git 的目录 → `workspace-write`+`on-request`；无 git → 只读起步；`workspace-write` 下网络默认关 |
| **OpenHands** | 确认策略 `AlwaysConfirm`/`NeverConfirm`/`ConfirmRisky(threshold)` | 无文本规则；按工具/动作粒度，安全策略模板（Jinja2）注入系统提示词 | **静态 + LLM 混合**：`LLMSecurityAnalyzer`（LOW/MEDIUM/HIGH/UNKNOWN）+ 确定性 `PatternSecurityAnalyzer`（regex）+ `PolicyRailSecurityAnalyzer`（组合威胁）组成 Ensemble 取最高风险 | 默认建议 Docker 容器内跑 + ConfirmRisky(HIGH) |
| **Goose** | 4 模式：`Completely Autonomous`/**默认**/`Manual Approval`/`Smart Approval`/`Chat Only` | 工具粒度三档：`Always Allow`/`Ask Before`/`Never Allow`（仅 Manual/Smart 下可配） | **LLM 风险判定**（Smart 模式）：低风险自动放行、其余标记；读写工具分类"尽力而为，由 LLM provider 解释" | 默认即完全自治（最激进） |
| **Aider** | chat 模式：`code`/`ask`/`architect`/`help`；无 shell 权限档 | **无白名单**——LLM 根本没有 shell 工具；`/run`、`/test`、`/git` 是用户主动敲的 in-chat 命令 | **不存在该问题**（能力裁剪换安全）；git 自动 commit + dirty-file 保护 + `/undo` 兜底 | 最保守：模型只能"建议"命令，执行永远问（`--yes-always` 也不放行 shell） |
| **Gemini CLI** | approvalMode：`default`/`auto_edit`/`plan`/`yolo`（yolo 只能命令行开，不能写成默认） | **TOML policy engine**：`toolName`+`commandPrefix`/`commandRegex`/`argsPattern`+`decision(allow/deny/ask_user)`+`priority`，分层 Default/User/Admin | **静态规则引擎为主**；可选 LLM 层 `security.enableConseca`（上下文感知安全检查，默认关）；重定向操作符默认强制确认 | 写工具/shell 默认 `ask_user`；admin 层可禁 yolo |
| **Cursor** | Run Modes：`Auto-review`（推荐）/`Allowlist`/`Run Everything` | `permissions.json` 白名单 + **自然语言** `autoReview.allow_instructions`/`block_instructions`；`sandbox.json` 管网络/路径 | **白名单 → OS 沙箱 → 后端 LLM 分类器**三明治（分类器可读本机只读工具取证）；官方明确声明"不是安全边界" | 终端命令默认要批准；文件编辑默认免批（配置文件除外） |
| **VS Code Copilot**（简记） | 逐命令批准 / allowlist 自动 | `chat.agent.terminal.allowList` / `denyList`（前缀匹配） | 静态前缀 | 终端默认问 |

**共同骨架**（后面第 9 节展开）：`档位(mode) → 文本规则(allow/ask/deny) → OS 沙箱(sandbox)` 三层，外加可选的 `LLM 判定层`。七家中只有 Aider 选择了"直接不给 shell"。

---

## 1. Claude Code（Anthropic）

### 1.1 权限档位（permission modes）

Mode 定义"哪些动作可以不问就跑"，是**基线**；规则叠加在基线上。当前共 6 档（来源：[permission-modes](https://code.claude.com/docs/en/permission-modes)）：

| Mode | 免提示可跑 | 定位 |
| :--- | :--- | :--- |
| `default`（UI 叫 **Manual**） | 只读 | 每个动作自己审 |
| `acceptEdits` | 读 + 文件编辑 + 常见文件系统命令（mkdir/touch/mv/cp 等，限工作区） | 边看边改 |
| `plan` | 只读 +（auto 可用时）分类器批准的命令；先出计划再动手 | 探索代码库 |
| `auto` | 全部——由第二个模型（**classifier 分类器**）在后台逐动作审查 | 长任务、减少打断疲劳；**v2.1.283+ 交互式终端/VS Code 会话的内置默认** |
| `dontAsk` | 工作区内读 + 预批准工具；本该弹窗的一律**拒绝** | 锁死的 CI/脚本 |
| `bypassPermissions` | 全部（`--dangerously-skip-permissions` 等价） | 仅隔离容器/VM；Linux/macOS 上 root/sudo 直接拒绝启动 |

细节：
- **deny 规则在所有 mode 生效（包括 bypassPermissions）；allow 规则在 bypass 下无意义**。ask 规则命中的命令即使在 auto 模式也照样弹窗。
- `acceptEdits`/`auto` 不能写进项目级 `.claude/settings.json` 生效（防仓库投毒）；`bypassPermissions` 同样不能从项目 settings 进来。
- 首次交互式进 bypass 有警告对话框，接受后写 `skipDangerousModePermissionPrompt`。
- 组织可用 managed settings 的 `disableBypassPermissionsMode`/`disableAutoMode`/`allowManagedPermissionRulesOnly` 强行封死。

### 1.2 规则语法（settings.json 的 allow / ask / deny）

来源：[permissions](https://code.claude.com/docs/en/permissions)。规则形如 `Tool` 或 `Tool(specifier)`：

- `Bash` = 匹配所有 Bash 命令（deny 时整工具从模型上下文移除）；`Bash(*)` 等价。
- `Bash(npm run build)` = 精确匹配整条命令文本。
- `Bash(npm run *)` = 通配：`*` 匹配**任意文本包括空格**；第一个 `*` 之前的文本逐字匹配。尾缀 `*`（前面带空格）还匹配裸命令本身（`Bash(ls *)` 也匹配 `ls`）；`Bash(ls:*)` 是等价写法。
- **通配符位置纪律**：官方明确警告"`*` 要放在子命令之后"——`Bash(git log *)` 只放行 `git log`；`Bash(git *)` 放行所有 git 子命令（含 `git -c core.fsmonitor=<script>` 这种能执行程序的形态），启动时会对此类规则发警告。
- 匹配的是**字面前缀**：`Bash(git push *)` 匹配不了 `git -C . push`（选项重排绕过）。
- `ask` 规则强制弹窗；deny/ask 还支持参数匹配 `Tool(param:value)`（如 `Bash(dangerouslyDisableSandbox:true)`），但**不允许**匹配主内容字段（`Bash(command:rm *)` 会被忽略并告警，因为复合命令可绕过）。

**评估顺序：deny → ask → allow，先匹配先赢，规则特异性不影响顺序**。宽 deny（`Bash(aws *)`）能压过窄 allow（`Bash(aws s3 ls)`），allow 不能在 deny 里挖洞。任何一层 settings 的 deny 都无法被其他层 allow 翻盘（managed > 项目 > 用户 的优先级另算）。

### 1.3 复合命令与 wrapper（白名单防绕过的核心工程）

- **复合命令拆分**：识别 `&&`、`||`、`;`、`|`、`|&`、`&`、换行为分隔符，**每个子命令独立匹配规则**。`Bash(safe-cmd *)` 不会放行 `safe-cmd && other-cmd`。deny/ask 只要任一子命令命中（包括子 shell `(...)`、命令替换 `$(...)`/反引号、`for` 循环体内）就生效。解析不了的（如 `npm test &&` 结尾悬空）不放行。
- **Wrapper 剥离**：匹配前剥掉固定 wrapper 集：`timeout`、`time`、`nice`、`nohup`、`stdbuf`、shell 内建 `command`/`builtin`、zsh `noglob`；前导**已知安全**环境变量赋值（`NODE_ENV=test npm test`）对 allow 可剥；**deny/ask 可以越过任意前导赋值**（`FOO=bar rm -rf tmp/` 仍被 `Bash(rm *)` deny 命中）。裸 `xargs` 也剥（`xargs grep` 按 grep 匹配），带 flag 的 `xargs -n1` 不剥。
- **前缀规则管不住的形态**：exec wrapper（`watch`、`setsid`、`ionice`、`flock`）和带动作的 `find`（`-exec`、`-delete`、`-rm`、`-fprint`、`-files0-from`）**永远不能被前缀规则自动放行**，只能写整条精确规则（如 `Bash(find build -type f -delete)`）或每次人工批。
- 批准复合命令时按子命令分别存规则（`git status && npm test` 只存 `npm test` 一条）。

### 1.4 内置安全集（静态判定）

- **内置只读命令集**（所有 mode 免提示，不可配置）：`ls`、`cat`、`echo`、`pwd`、`head`、`tail`、`grep`、`find`、`wc`、`which`、`diff`、`stat`、`du`、`cd`、**只读形态的 git**。带"可写/可执行 flag + 未加引号的 glob"（如 `find`/`sort`/`sed`/`git` 后跟裸 `*`）仍会弹窗（glob 可能展开成 `-delete` 这类 flag）。
- **Protected paths**（写入永不自动批，allow 规则也救不了）：`.git`、`.config/git`、`.vscode`、`.idea`、`.husky`、`.cargo`、`.devcontainer`、`.yarn`、`.mvn`、`.claude`，以及 `.gitconfig`、`.bashrc`/`.zshrc` 等 shell rc、`.npmrc`、`.envrc`、`.pre-commit-config.yaml`、`.mcp.json`、`.claude.json` 等文件。
- **Critical paths（rm/rmdir 形态学检查）**：目标是文件系统根、顶层目录、家目录（含 Windows 8.3 短名）、盘根、工作目录及其父目录，或 `rm -rf "$DIR"/*`（变量空展开=从根删）、`$1`/`$@` 形态、`rm -rf "$(pwd)"`（命令替换不可解析）、`bash -c 'rm -rf ~'`（内联脚本，双引号形态也查）、挂载盘（`/Volumes/*`、`/mnt/*`）……**命中即视为"关键路径删除"，没有任何 allow 规则或 hook 能自动批准**；按 mode 弹窗或拒绝。官方同时承认"检查会漏（如 find -delete、其他命令删关键路径），不能替代 OS 沙箱"。PowerShell 的 `Remove-Item`：系统路径与裸 `*`/`/*` 结尾目标**任何 mode 直接拒绝**；工作目录 + `-Recurse` 走常规审批。
- auto/bypass 下关键路径删除的终端弹窗带 **2 分钟倒计时**，超时自动拒绝且告知 agent 换路；连续 3 次超时后本会话不再弹、直接拒。

### 1.5 auto 模式的 LLM 分类器（高风险判定的"软"层）

来源：[permission-modes#what-the-classifier-blocks-by-default](https://code.claude.com/docs/en/permission-modes)。每个动作过**固定决策序**：① allow/ask/deny 规则立即裁决（protected-path 写入、关键路径 rm 例外地不可被 allow 覆盖）→ ② 只读动作与工作区内文件编辑自动批 → ③ 其余全部送分类器。

**默认拦截清单**（节选，全部为语义级规则）：下载并执行（`curl | bash`）、向外部端点发敏感数据、生产部署与迁移、云存储批量删除、授予 IAM/仓库权限、修改共享基础设施、**不可逆地毁掉会话前就存在的文件**、force push、提交/推送会把 secret 或敏感数据带出仓库的变更（含 CI workflow 改动）、`git reset --hard`/`git checkout -- .`/`git restore .`/`git clean -fd`/`git stash drop|clear`（推定丢弃未提交改动）、`git commit --amend`（HEAD 非本会话创建或已推送）、`terraform destroy` 系列、写 secret manager/改 DNS/TLS、合并无人批准的 PR/关 CI、生产 feature flag、集群 DaemonSet/admission webhook、向敏感目标的交互 shell/port-forward、公网隧道/反弹 shell、**打印活凭证到 transcript**、绕过内部 registry 装 public 包、带 `--insecure` 这类解除安全防护的 flag、**启动无审批无沙箱的自治 agent 循环（`--dangerously-skip-permissions`、`--yes-always` 等）**、注释/删除/强过安全相关测试、改 `git remote`、向公开仓库推私有内容……
**默认放行**：工作区内文件操作、**锁文件/清单声明的依赖安装**、读 `.env` 并把凭证发给其对应的 API、只读 HTTP、向当前仓库任何分支 push（非 deploy 类分支）。

工程细节值得抄：
- **分类器看不到工具结果**（只看用户消息、非只读工具调用、CLAUDE.md），防止文件/网页里的注入内容操纵分类器；另有服务端探针扫描工具结果。
- 进入 auto 模式时**自动丢弃粗放 allow 规则**：`Bash(*)`、`Bash(python*)`、包管理器 run 命令、`Agent`/`Monitor` 规则；窄规则（`Bash(npm test)`）保留。
- 用户在对话里说的边界（"别 push"）被分类器当**阻断信号**，但会随上下文压缩丢失——官方建议硬保证用 deny 规则。
- 连续 3 次或累计 20 次拦截 → auto 暂停、退回人工弹窗。

### 1.6 Bash sandbox（OS 级，与权限正交）

来源：[sandboxing](https://code.claude.com/docs/en/sandboxing)。macOS Seatbelt / Linux+WSL2 bubblewrap(+seccomp)，Windows 原生不支持。默认边界：**写=工作区+每用户 tmp+add-dir 目录**（protected paths 仍禁写）；**网络=本地代理域名白名单（初始为空，按 host 逐个批）**；读基本放开（可用 denyRead/credentials 收）。两种 sandbox mode：
- **auto-allow**：沙箱内命令**免提示直接跑**（`autoAllowBashIfSandboxed` 默认 true）——"沙箱边界替代整工具弹窗"。但 deny 规则、关键路径 rm、内容型 ask 规则（`Bash(git push *)`）仍然生效。
- **regular permissions**：沙箱内照常走审批。
- **unsandboxed retry 逃生舱**：命令在沙箱内失败（如网络被拒）→ agent 可带 `dangerouslyDisableSandbox` 重试；交互下按 mode 审批（allow 规则匹配也会直接放行重试）；`allowUnsandboxedCommands:false`（strict 模式）关掉。
- 明确承认局限：不终结 TLS（域名 fronting 可绕）、allowUnixSockets 可能提权、宽域名（github.com）= 潜在外传通道。

### 1.7 UX 取舍

弹窗四选项：`Yes` / `Yes, and don't ask again for <规则>`（存 `.claude/settings.local.json`，按仓库生效）/ `Yes, and switch to auto mode` / `No`；Tab 可加批注。产品方向明确：**用"沙箱 auto-allow + auto 分类器"把打断次数压到接近零，同时保留 deny/ask/关键路径这些硬闸**。代价是复杂度（规则语法 + 六个 mode + 沙箱 + 分类器四套概念要向用户解释）和分类器的误判（有 3/20 次熔断回退机制）。

来源：
- https://code.claude.com/docs/en/permission-modes.md
- https://code.claude.com/docs/en/permissions.md
- https://code.claude.com/docs/en/sandboxing.md

---

## 2. OpenAI Codex CLI

### 2.1 两旋钮矩阵（核心设计）

来源：[concepts/sandboxing](https://mintlify.wiki/openai/codex/concepts/sandboxing)、[concepts/approvals](https://mintlify.wiki/openai/codex/concepts/approvals)（openai/codex 仓库文档镜像）+ [腾讯云中文综述](https://cloud.tencent.com.cn/developer/article/2702951)（二手，交叉验证用）。

**沙箱（能碰多大）**与**审批（问不问你）是两个独立旋钮**，自由组合：

| sandbox_mode | 行为 |
| :--- | :--- |
| `read-only` | 全盘只读；网络需显式开 |
| `workspace-write`（**默认**） | 工作区（cwd + `--add-dir`）+ 临时目录可写；**`.git` 等保护路径保持只读**；**网络默认关**（`[sandbox_workspace_write] network_access = true` 手动开）；子进程同受约束 |
| `danger-full-access` | 整机；官方标注 not recommended，仅隔离容器 |

| approval_policy | 行为 |
| :--- | :--- |
| `untrusted`（新名 `unless-trusted`） | 已知安全的只读操作自动跑，其余一律先问 |
| `on-request`（**推荐默认**） | 沙箱圈内自己干，**要出圈（escape sandbox）才停** |
| `on-failure` | 沙箱内失败、需要出沙箱重试时才问 |
| `never` | 不弹审批（≠放权：可与 read-only 组合用于 CI 只读分析） |

OS 层实现：Linux **Landlock + seccomp**、macOS **Seatbelt**、Windows **restricted token + job object**。沙箱升级（escalation）：命令要出圈时按 approval policy 决定问不问。

**启动默认**：目录有 git → Auto 档（`workspace-write` + `on-request`，理由是"改砸了能回滚"）；无 git → 只读起步，等用户信任工作目录。会话内 `/permissions` 可当场切档。`--yolo`（=`--dangerously-bypass-approvals-and-sandbox`）= `danger-full-access`+`never`，官方红线：只在隔离容器/VM，本机和生产机免谈；即便在 devcontainer 里也非绝对安全（可偷容器内的登录凭据）。

### 2.2 execpolicy rules（命令前缀规则，静态）

Starlark 语法（Python 子集），存 `~/.codex/rules/*.rules`：

```python
prefix_rule(
    pattern = ["gh", "pr", "view"],
    decision = "prompt",        # allow / prompt / forbidden
    justification = "...",
)
```

- 决策词是 `allow`/`prompt`/`forbidden`，**优先级固定：最严者赢（forbidden > prompt > allow）**。
- **复合命令拆分**：`git add . && rm -rf /` 会在安全前提下拆成单条逐个判——即使 `git add` 被 allow，`rm -rf /` 单独被拦，不会夹带过关。
- rules 在沙箱**之前**评估（评估于执行前的策略层）。
- `codex execpolicy check` 可离线测试一条命令会怎么判。
- pattern 匹配的是解析后的 argv 前缀（含 host executable 解析），比裸文本前缀健壮。

### 2.3 permission profiles（Beta）

新机制（与旧 `sandbox_mode` 互斥）：把文件系统规则（路径 → `read`/`write`/`deny`，**deny > write > read**，越具体越优先）+ 网络规则（域名 allowlist，不写 allow 就全不放）打包成命名 profile。内置 `:workspace` 等三个，可自定义（如"工作区可写但 `**/*.env` 全部 deny + 只允许 api.openai.com"）。

### 2.4 高风险判定方式

**纯静态 + OS 沙箱，没有 LLM 判定层**。"高风险"被物化为两件事：① 出沙箱边界（由 OS 判定）；② 命中 forbidden/prompt 规则（由 argv 前缀判定）。风险判断的主体是**人**（审批弹窗）。新版有 `approvals_reviewer = "auto_review"`（审查 agent 代审）的演进方向。另有两处体现纵深的小设计：web search 默认走缓存索引（降低实时页面提示注入面，`--yolo` 时才转实时）；默认按"有没有 git"决定起始档位。

### 2.5 UX 取舍

打断频率由"出圈频率"决定，而圈由沙箱画——所以**把沙箱画准（网络默认关、.git 只读）比写一堆规则更能减少弹窗**。代价：网络默认关导致 `npm install` 这类"看起来无害"的操作也要升级审批，新手第一晚经常被卡住（二手资料里的常见吐槽）。

来源：
- https://mintlify.wiki/openai/codex/concepts/sandboxing （官方仓库文档镜像）
- https://mintlify.wiki/openai/codex/concepts/approvals （同上）
- https://mintlify.wiki/openai/codex/advanced/exec-policies （同上）
- https://mintlify.wiki/openai/codex/configuration/basic （同上）
- https://cloud.tencent.com.cn/developer/article/2702951 （中文二手综述，用于补全被截断的段落）

---

## 3. OpenHands（原 OpenDevin）

来源：[SDK Security & Action Confirmation](https://docs.openhands.dev/sdk/guides/security)。

### 3.1 双机制：confirmation policy + security analyzer

- **Confirmation policy**：`AlwaysConfirm()`（全部问）/ `NeverConfirm()`（全不问）/ `ConfirmRisky(threshold=SecurityRisk.HIGH, confirm_unknown=True)`——**只对高风险动作要确认；UNKNOWN 默认也问（fail-closed）**；阈值可降到 MEDIUM 收紧。
- **Security analyzer**：给每个动作评级 `LOW / MEDIUM / HIGH / UNKNOWN`。**analyzer 只分类、不拦截**；"怎么办"归 policy 层。二者解耦。

### 3.2 LLM 判定：LLMSecurityAnalyzer

主模型在生成动作时**自我标注** risk 等级（通过 Jinja2 渲染的 security policy 模板进系统提示词，可自定义——模板里定义 LOW=只读、MEDIUM=容器内变更/装包、HIGH=网络访问/系统修改/数据外传）。可用独立 LLM 复核避免与主 agent 冲突。本质上和 Claude auto 模式分类器同类：**LLM 语义判断**，且把评级标准做成可配置文本。

### 3.3 确定性纵深：defense-in-depth 三件套

| Analyzer | 抓什么 | 怎么做 |
| :--- | :--- | :--- |
| `PatternSecurityAnalyzer` | 已知特征（`rm -rf`、`eval`、`curl\|sh`） | 正则，**双语料库**：shell 模式只扫可执行字段；注入模式（"ignore all previous instructions"类）扫全部字段 |
| `PolicyRailSecurityAnalyzer` | 组合威胁（fetch 管道到 exec、裸盘写、灾难删除） | 确定性规则按**段**评估，两个 token 必须出现在同一字段 |
| `EnsembleSecurityAnalyzer` | 组合上面（可再加 LLM） | **取最高具体风险**（max-severity，不做平均）；UNKNOWN 默认被具体值覆盖，`propagate_unknown=True` 则任何一个 UNKNOWN 都触发确认 |

工程细节：30k 字符/语料提取预算（防 ReDoS，代价是超长载荷不可见）；**主攻击面优先排序**（`tool_call.arguments` 先于 `tool_name`）；已知局限表公开（analyzer 无硬 deny 能力、`execute_tool()` 旁路、无同形字检测、`thinking_blocks` 不扫）。传统上 OpenHands 整体跑在 Docker runtime 里，这套判定是容器之外的又一层。

### 3.4 UX 取舍

面向 SDK 嵌入者而非终端用户：没有"档位旋钮"的产品化 UI，而是**可编程的 policy + analyzer 接口**。默认建议 = ConfirmRisky(HIGH) + 容器。教训点：文档反复强调"analyzer 不是拦截器、`execute_tool()` 会绕过、不是沙箱替代品"——**分层时每层的职责要写死**。

来源：
- https://docs.openhands.dev/sdk/guides/security.md

---

## 4. Goose（Block，现 AAIF）

来源：[goose Permission Modes](https://goose-docs.ai/docs/guides/managing-tools/goose-permissions)、[Managing Tool Permissions](https://goose-docs.ai/docs/guides/managing-tools/tool-permissions)。

### 4.1 权限档位（4 模式）

| Mode | 行为 | 适合 |
| :--- | :--- | :--- |
| **Completely Autonomous**（**默认！**） | 改文件、用扩展、**删文件都不问** | 全自动化 |
| **Manual Approval** | 任何工具/扩展使用前确认（支持工具粒度覆盖） | 每步都审 |
| **Smart Approval** | **基于风险**：低风险自动批、其余标记确认（支持工具粒度覆盖） | 平衡 |
| **Chat Only** | 纯对话，无扩展无文件改动 | 分析/写作 |

### 4.2 工具粒度覆盖

每个工具三档：**`Always Allow` / `Ask Before` / `Never Allow`**（只读工具 Always Allow、写操作 Ask Before、敏感操作 Never Allow 的示例配置）。仅 Manual/Smart 模式下可配。Smart 模式的读写分类是"尽力而为"，**由你的 LLM provider 解释**——即判定主体是 LLM。

### 4.3 高风险判定与取舍

高风险判定完全交给 **LLM 的风险直觉**（Smart 模式），没有静态规则层、没有 OS 沙箱文档（安全模型主要靠"运行环境自己隔离"+ MCP 扩展 allowlist）。**默认 Autonomous 是七家里对用户最激进的默认**（官方自己加 warning）。值得一提的反向设计：作为多 agent 框架，Goose 接入 Claude Code 等 CLI provider 时会把对方的权限请求**转发到自己的确认 UI**，统一审批体验。

来源：
- https://goose-docs.ai/docs/guides/managing-tools/goose-permissions
- https://goose-docs.ai/docs/guides/managing-tools/tool-permissions

---

## 5. Aider

来源：[in-chat commands](https://aider.chat/docs/usage/commands.html)、[chat modes](https://aider.chat/docs/usage/modes.html)、[git integration](https://aider.chat/docs/git.html)、[issue #3903](https://github.com/Aider-AI/aider/issues/3903)。

### 5.1 设计：LLM 没有 shell 工具

Aider 的工具面只有**受限文件编辑**（SEARCH/REPLACE diff 格式，只改 `/add` 进会话的文件）。shell 相关全是**用户主动敲**的 in-chat 命令：
- `/run <cmd>`（别名 `!`）：本地执行 shell，**可选**把输出加进上下文；
- `/test <cmd>`：跑测试，非零退出才把输出加进 chat；
- `/git <cmd>`：跑 git，输出不进 chat；
- `/lint`、`/commit`、`/undo` 等同样是用户触发。

模型确实会"提议"命令（比如让它 `touch a.txt`），但那只是文本。issue #3903 的实证：**开了 `--yes-always` 模型提议的 shell 也不执行**；不开时弹 `Run shell command? (Y)es/(N)o/(D)on't ask again`——"D"只是不再问"要不要把输出加进 chat"这类低风险确认，命令本身仍要 Y。也就是说 aider 的确认体系里，**shell 是和"加文件进会话"同级甚至更高级的人工动作**，`--yes-always` 管不到它。

### 5.2 为什么敢这么收

- 它的使命是"pair editing"，不是跑任务：编辑由 diff 格式收敛（模型做不了任意写），lint/test 由用户配置的 `--lint-cmd`/`--test-cmd` 在**编辑后由 aider 自己**触发（不是模型）。
- **git 当沙箱**：每次编辑自动 commit（弱模型写 commit message）；编辑"脏文件"前先把用户未提交的改动保护性 commit（`--no-dirty-commits` 可关）；`/undo` 一键回滚；`(aider)` 标注作者归属。出错的爆炸半径 = 一个 commit。
- chat 模式（`code`/`ask`/`architect`/`help`）控制的是**编辑权**而不是 shell 权：ask 模式只读，architect 双模型（架构师提方案+编辑器落盘）。

### 5.3 取舍

打断最少（因为几乎无命令可跑），安全上限最高（模型无执行权 + git 兜底），代价是**能力面窄**：不能装依赖、不能跑脚手架、demo 生成做不了——对我们的"项目构建 agent"不适用，但其"**能力裁剪优先于权限裁剪**"和"**用可回滚的 VCS 限爆炸半径**"两条思想值得保留。

来源：
- https://aider.chat/docs/usage/commands.html
- https://aider.chat/docs/usage/modes.html
- https://aider.chat/docs/git.html
- https://github.com/Aider-AI/aider/issues/3903 （API 正文）

---

## 6. Gemini CLI

来源：[settings](https://geminicli.com/docs/cli/settings.md)、[policy engine](https://geminicli.com/docs/reference/policy-engine.md)、[tools reference](https://geminicli.com/docs/reference/tools.md)。注：Gemini CLI 2026-06 起[过渡为 Antigravity CLI](https://geminicli.com/)，文档仍在且机制值得借鉴。

### 6.1 approvalMode 档位

`default`（写工具要确认）/ `auto_edit`（编辑类自动批）/ `plan`（只读）/ **`yolo`（全自动）**。关键治理细节：
- **yolo 只能通过命令行开**（`--yolo` / `--approval-mode=yolo`），settings.json 里不能设成默认——防止配置文件投毒；
- `security.disableYoloMode` 可整体禁掉 yolo（企业管控）；`security.disableAlwaysAllow` 禁掉"总是允许"按钮；`security.enablePermanentToolApproval` 控制"以后所有会话都允许"选项（默认关）；
- 持久批准是**模式感知**的：在 plan 模式批准的工具会覆盖所有模式（全局信任），在 default 批准的只覆盖 default/autoEdit/yolo（`plan < default < autoEdit < yolo` 层级）。

### 6.2 policy engine（七家里最完整的静态规则引擎）

TOML 规则，`~/.gemini/policies/*.toml`：

```toml
[[rule]]
toolName = "run_shell_command"
commandPrefix = "rm -rf"
decision = "deny"          # allow / deny / ask_user
priority = 100
# 可选: commandRegex / argsPattern（对参数 JSON 的正则）
# 可选: modes = ["default","autoEdit","yolo"]（按 approvalMode 激活）
# 可选: interactive = true/false（只对交互/非交互生效）
# 可选: denyMessage = "Deletion is permanent"（回给模型的原因）
# 可选: allowRedirection = true（本条规则是否豁免重定向确认）
```

- **条件**：`toolName`（支持 `*`、`mcp_server_*`、`mcp_*_toolName` 通配；推荐用 `mcpName` 字段）/ `commandPrefix`（前缀）/ `commandRegex`（对参数 JSON 的正则）/ `argsPattern`（正则）。
- **决策**：`allow` / `deny` / `ask_user`（**非交互模式下 ask_user 视为 deny**——fail-closed）。全局 deny（无 argsPattern）会把工具**从模型上下文整体移除**。
- **优先级分层**：Default(1) / Extension(2) / Workspace(3，当前有 bug 失效) / User(4) / **Admin(5)**，`final_priority = tier_base + toml_priority/1000`，**最高优先级者赢**——Admin 永远压过 User。Admin 策略目录有严格属主检查（防提权），且标准目录存在策略时忽略 `--admin-policy` 补充路径（防 flag 覆盖）。
- **重定向防御**：检测到 `>` `>>` `<` 等重定向操作符时**默认强制确认，即使规则已 allow**；`allowRedirection` 按规则粒度豁免，链式命令中每段都要各自豁免。
- **默认策略**：只读工具（read_file/glob/grep…）allow；**写工具与 `run_shell_command` 默认 `ask_user`**；yolo 模式挂一条高优先 allow-all；agent 委派默认 ask_user。

### 6.3 高风险判定

以**静态规则引擎**为主（前缀 + 正则 + 参数模式），另有可选 LLM 层：`security.enableConseca`——"上下文感知安全检查器，用 LLM 根据你的 prompt 动态生成并执行安全策略"（默认关，实验性）。沙箱配置：`tools.sandboxAllowedPaths`、`tools.sandboxNetworkAccess`（默认 false）、`security.toolSandboxing`（工具级沙箱，实验）。

### 6.4 取舍

规则表达力最强的静态方案（优先级分层 + 模式感知 + 重定向特殊处理），企业管控入口清晰；代价是 TOML 规则对普通用户偏重，Workspace 层还有已知 bug。

来源：
- https://geminicli.com/docs/reference/policy-engine.md
- https://geminicli.com/docs/cli/settings.md
- https://geminicli.com/docs/reference/tools.md

---

## 7. Cursor（agent 模式）

来源：[Run Modes](https://cursor.com/docs/agent/security/run-modes)、[Agent Security](https://cursor.com/docs/agent/security)。

### 7.1 Run Modes（3 档）

| Mode | 免批可跑 | 沙箱 | 分类器 |
| :--- | :--- | :--- | :--- |
| **Auto-review**（推荐默认） | 白名单内立即跑；其余 shell 尽量进沙箱跑；不能沙箱的送分类器 | 有（shell） | 有 |
| **Allowlist** | 白名单内免批（可开沙箱） | 可选 | 无（确定性） |
| **Run Everything** | 全部自动 | 无 | 无 |

### 7.2 Auto-review 生命周期（三明治结构）

1. **白名单**内的 shell/Fetch/MCP 直接跑（沙箱外）；
2. 其余 shell 命令**能进沙箱就进沙箱跑**（沙箱容得下文件/网络限制的命令）；
3. 沙箱跑不了的、沙箱内失败要重跑的、非 shell 的调用 → **后端 LLM 分类器**（Cursor 托管小模型：Gemini Flash Lite，Haiku 兜底；企业模型管控适用）审查。**分类器可以在本机执行只读 ReadFile/Grep/Glob/ListDir 取证**（比如读一下命令要跑的脚本再判断）；
4. 分类器拦截 → agent 换路径或给用户弹批准。

配套配置：
- `permissions.json`（`~/.cursor/` 用户级 + `<project>/.cursor/` 项目级合并，团队配置优先）：除了白名单，还有 **`autoReview.allow_instructions` / `block_instructions`——自然语言句子**（例："Every AWS CLI command should go through approval first."），直接喂给分类器当策略。官方甚至建议"让 agent 自己帮你改这个文件"。
- `sandbox.json`：网络域名、额外读写路径；默认沙箱：工作区可读写、保护路径（`.git/config`、`.git/hooks`、`.vscode`、`.cursorignore`）、网络受限。

### 7.3 默认基线与安全声明

读文件/搜代码免批（`.cursorignore` 可挡）；**工作区文件编辑默认免批（配置文件除外）**；终端命令默认要批；MCP 连接要批 + 每个工具调用单独批（可用 MCP allowlist 预批）；网络工具仅限 GitHub/直链/搜索提供商。官方明确两句话："**Auto-review is not a security boundary**"（分类器会犯错）、"这些是 best-effort guardrails"。Workspace trust 默认关。

### 7.4 取舍

Auto-review 的设计意图 = "known-safe 的确定性放行 + 沙箱吸收长尾 + LLM 只判剩下的小尾巴"，**把分类器调用量压到最小**（对比 Claude auto 全量送分类器）。自然语言策略（block_instructions）是对"规则语法太难写"的产品化回答，但语义边界模糊。

来源：
- https://cursor.com/docs/agent/security/run-modes
- https://cursor.com/docs/agent/security

---

## 8. 简记：VS Code GitHub Copilot

VS Code 的 Copilot agent 对终端命令提供 allowlist/denylist 设置：`chat.agent.terminal.allowList` / `chat.agent.terminal.denyList`（前缀匹配；旧名 `github.copilot.chat.agent.terminal.*`，见 [microsoft/vscode#253314](https://github.com/microsoft/vscode/issues/253314)）；MCP 工具逐个批准 + allowlist 格式。思路与 Gemini/Codex 的静态前缀白名单同代，无 LLM 判定层、无独立沙箱配置面。（4sysops 有[中文圈常引的综述](https://4sysops.com/archives/new-in-vs-code-github-copilot-command-allowdeny-lists-resubmit-requests-mcp-server-catalog/)，本环境被 Cloudflare 拦截，未直接核验。）

---

## 9. 横向对比与可提炼的设计模式

### 9.1 通用三层 + 可选第四层

所有成熟产品都长成这个形状：

```
档位 mode（免提示基线）
  └─ 规则层 rules（allow / ask|prompt / deny，前缀+通配+正则）
       └─ OS 沙箱 sandbox（文件系统边界 + 网络出口）
            └─ [可选] LLM 判定层（分类器 / 风险标注）
```

### 9.2 高风险判定方式光谱

```
无 shell        纯静态+OS        静态规则引擎        静态为主+LLM兜底       LLM 全量判定
Aider ────────► Codex ────────► Gemini CLI ──────► Claude / Cursor ──────► OpenHands(LLM+ensemble) / Goose(Smart)
                (argv 前缀)      (TOML+正则+分层)    (关键路径静态+分类器)    (语义风险评级)
```

**共识红线**（至少 3 家以上用静态规则处理）：
- `rm -rf` 危险形态（变量展开/裸通配/关键路径）——Claude 专门做了形态学 + 拒绝被 allow 覆盖；OpenHands pattern 规则；Gemini 文档示例第一条就是 `commandPrefix = "rm -rf"` → deny；
- 下载即执行（`curl | sh`）——Claude 分类器默认拦、OpenHands pattern 抓、各家文档常用例；
- git 不可逆操作（`push --force`、`reset --hard`、`clean -fd`）——Claude 分类器默认拦、Gemini/用户常见规则；
- 网络默认关 / 域名白名单——Codex（workspace-write 网络默认关）、Claude（沙箱代理白名单初始为空）、Cursor（网络仅限三类端点）、Gemini（sandboxNetworkAccess 默认 false）；
- 保护路径（`.git`、shell rc、`.env`、`.ssh`）——Claude protected paths、Codex `.git` 只读、Cursor 保护路径、Gemini `.env` 示例规则；
- 凭证/敏感数据外发——只有 LLM 层能做语义判断（Claude 分类器的 outbound 规则、OpenHands HIGH 定义）。

### 9.3 值得直接抄的工程决策

1. **deny 永远压过 allow，且全档生效**（Claude/Codex/Gemini 一致）；`ask` 介于其间且不可被 allow 覆盖。
2. **复合命令必须拆分逐段判定**（Claude 按操作符拆、Codex 按 argv 拆）——否则白名单形同虚设。
3. **wrapper/前缀赋值要处理**（Claude 剥 timeout/nice/command 等；deny 要能越过 `FOO=bar` 前缀；xargs/exec wrapper/find -delete 干脆不允许前缀放行）。
4. **前缀匹配的字面性陷阱**：`git -C . push` 绕过 `Bash(git push *)`；通配符要放在子命令之后（Claude 的启动警告）。
5. **fail-closed**：解析不了的命令不放行（Claude）；`ask_user` 在非交互下 = deny（Gemini）；UNKNOWN 默认问（OpenHands）。
6. **配置投毒防御**：yolo/bypass 不能从项目级配置进（Claude、Gemini）；项目 allow 规则要过 workspace trust（Claude）；admin 层属主检查（Gemini）。
7. **重定向/管道是独立风险维度**（Gemini 把 `>` 单独拎出来强制确认；Claude 把 `|` 当命令分隔符拆段）。
8. **持久批准的粒度与层级**（Claude 按仓库+命令前缀存 local settings；Gemini 按 approvalMode 层级传播）。
9. **LLM 层的防注入设计**（Claude：分类器看不到工具结果；服务端探针扫结果）与**熔断**（3/20 次拦截退回人工）。
10. **声明边界**：Cursor 明说"不是安全边界"；Claude 明说形态学检查"会漏"；OpenHands 明说 analyzer 无硬 deny。**文档化每层的不保证**，能省掉后续无数扯皮。

---

## 10. 综合建议：面向"项目构建 agent"的最小白名单

场景设定：shell 只用于**脚手架类命令 + demo 生成**（create-vite/degit/git clone/npm install/构建/本地静态服务器等），工作区 = 项目目录，网络需求 = 包 registry + 本地端口。

### 10.1 档位：两旋钮 + 四档（学 Codex 的正交，学 Claude 的命名）

```
boundary（能碰多大）:  readonly ── project-write ── full(仅容器)
interrupt（问不问你）:  plan ── scaffold(白名单自动) ── ask-all ── yolo(仅 flag)
```

| 档位 | boundary | interrupt | 用途 |
| :--- | :--- | :--- | :--- |
| **P0 plan**（默认起步） | readonly | 只读命令免批，其余不批 | 看仓库、出方案 |
| **P1 scaffold**（日常档） | project-write | 白名单自动 + 白名单外 ask | 脚手架 + demo |
| **P2 ask-all** | project-write | 全部问 | 敏感项目 |
| **P3 yolo** | full | 不问 | 仅容器/VM，**只能命令行 flag 开**，配置文件写了不生效 |

规则：
- deny 规则**全档生效**（含 yolo）；yolo 且 boundary=full 时启动横幅确认（学 Claude 的 `skipDangerousModePermissionPrompt`）。
- 白名单外默认 **ask**（不是 deny——脚手架生态命令太杂，deny 会把合法新工具打死；也不是 auto——本项目没有全量分类器的预算）。
- 解析失败 = ask（fail-closed）。

### 10.2 白名单写法（草案）

```jsonc
// agent-shell-policy.json
{
  "version": 1,
  "decision_order": ["deny", "ask", "allow"],   // 先匹配先赢，deny 不可被覆盖
  "boundary": {
    "writable": ["${WORKSPACE}", "${TMP}"],
    "protected_paths": [".git/**", ".env*", "**/.env*", ".ssh/**", ".aws/**",
                        ".npmrc", ".bashrc", ".zshrc", ".pre-commit-config.yaml"],
    "network": { "allowed_domains": ["registry.npmjs.org", "registry.npmmirror.com"],
                 "allow_localhost": true }        // 学 Codex：默认关，显式开
  },
  "allow": [
    // A. 只读探查（学 Claude 内置只读集）
    "ls *", "cat *", "pwd", "echo *", "head *", "tail *", "grep *", "rg *",
    "find *",            // 仅当无 -delete/-exec/-fprint/-files0-from（见 deny 规则+静态检查）
    "wc *", "which *", "diff *", "stat *", "du *", "cd *",
    "git status", "git log *", "git diff *", "git show *", "git branch", "git remote -v",
    "node --version", "npm --version", "pnpm --version", "python --version",

    // B. 脚手架/生成（本 agent 的核心面）
    "npm create *", "pnpm create *", "npm create vite@latest *",
    "npx degit *", "npx create-* *",          // create-* 系列脚手架
    "npm install", "npm install *", "pnpm install", "pnpm install *",  // registry 白名单内
    "mkdir *", "cp *", "mv *",                // boundary 限定工作区
    "git init", "git add *", "git commit -m *", "git commit *",  // 无 --amend（见 deny）
    "git clone *",                            // 需网络 → 域名白名单扩展 github.com

    // C. 构建 / demo 运行
    "npm run build", "npm run *", "pnpm run *", "npx vite build", "npx vite *",
    "python -m http.server *",                 // demo 静态服务，localhost
    "node *"
  ],
  "ask": [
    "git push *",                              // 非白名单出口一律先问
    "npm publish *", "git clone *",            // 外联动作
    "npm install -g *", "pnpm add -g *"        // 全局安装
  ],
  "deny": [
    // 删除类（形态学，见 10.3 静态规则）
    "rm -rf *", "rm -fr *", "rmdir *", "Remove-Item *",
    // 下载即执行 / 管道进解释器
    "curl * | *", "wget * | *", "* | sh", "* | bash", "* | python", "* | node",
    // 提权 / 远程
    "sudo *", "su *", "doas *", "ssh *", "scp *", "rsync *",
    // git 不可逆
    "git push --force*", "git push -f*", "git reset --hard*", "git clean -fd*",
    "git checkout -- *", "git stash drop*", "git stash clear", "git commit --amend*",
    // 解释器套壳（复合命令绕过的老巢）
    "bash -c *", "sh -c *", "eval *", "xargs *",
    // 保护路径写入
    //（由 protected_paths 静态检查兜住，deny 里写不全是常态）
    "chmod 777 *", "chown *"
  ]
}
```

写法纪律（各家教训汇总）：
1. **通配符放在子命令之后**；`npm *` 这种宽规则会覆盖 `npm exec`（任意脚本执行），宁可枚举 `npm install/create/run/exec vite*`。
2. **复合命令拆段**：`&&`、`||`、`;`、`|`、`|&`、`&`、换行全部拆开，每段独立过 deny→ask→allow；任何一段解析失败整条 = ask。
3. **wrapper 剥离白名单**：`timeout`、`time`、`nice`、`nohup`、`command`、`builtin`；前导 env 赋值：allow 只认安全变量清单，deny 无条件越过。
4. **deny 不需要精确**——宽 deny（`rm -rf *`）合法且推荐，因为 deny 的误伤只是"弹个窗"；allow 必须精确，因为 allow 的误伤是事故。
5. **持久的"Yes, don't ask again"按 (仓库 × 命令前缀) 存**，且只存用户亲手批的那条前缀。

### 10.3 高风险判定：静态正则能覆盖多少，哪里必须留 LLM/人工

**静态可覆盖（本场景 ~90% 的高频风险，正则草案）**：

| 类别 | 正则/规则草案 | 依据 |
| :--- | :--- | :--- |
| 灾难删除 | `\brm\b[^|]*\s(-[rR][fF]\|--recursive)` 且目标含 `^/`、`~`、`$VAR`、`$(`、裸 `*`、`..`、`\\` → 直接 deny；`Remove-Item` + `-Recurse` + 裸 `*`/`/*` 结尾 → deny | Claude critical-path 形态学（连 8.3 短名、`\\?\C:\`、变量空展开都列了） |
| 下载即执行 | `(curl|wget|fetch)[^|;]*\|\s*(sh|bash|zsh|python|perl|node|ruby)` | Claude 分类器第 1 条 + OpenHands pattern |
| 提权 | `^(sudo|doas|su)\b` | OpenHands 自定义 analyzer 示例 |
| 凭证面 | 路径匹配 `~/.ssh/**`、`~/.aws/**`、`.env*`、`*.pem`、`id_rsa*` → 写操作 deny / 读+网络 = ask | Codex profiles（`**/*.env` deny）+ Claude 分类器（sensitive local store） |
| git 不可逆 | `git\s+(push\s+(-f\|--force)|reset\s+--hard|clean\s+-[fF][dD]|checkout\s+--\s|stash\s+(drop\|clear))`、`commit\s+--amend` | Claude 分类器默认拦截清单 |
| 网络出口 | 命令含 URL/host 且不在域名白名单（registry、github）→ ask | Codex/Claude/Gemini 的网络默认关 |
| 重定向 | 出现 `>` / `>>` 且目标在工作区外或保护路径 → ask（即使命令在 allow 里） | Gemini 的重定向强制确认 |
| 命令替换 | 含 `$(` 或反引号且结果被 rm/mv/chmod 消费，或整体作为目标 → ask（不可解析） | Claude：`rm -rf "$(pwd)"` 形态 |
| 自我提权 | 命令试图写本 agent 的 policy/settings 文件 → deny | Claude 对 `.claude/**` 的保护 + auto 模式丢弃宽 allow |

**静态覆盖不了、必须留人工（或 LLM）的 5 处**：
1. **语义级外发判断**："这条 `git push` 的 diff 里有没有不该公开的东西 / 这次 commit 会不会把 `.env` 带进历史"——需要理解内容，正则只能兜路径形态。Claude 用分类器做（outbound 规则），我们可以先退化为"push 一律 ask + 弹 diff 摘要"。
2. **供应链**：`npm install` 会跑任意 postinstall 脚本。静态可做的是"锁文件声明的依赖自动、其余 ask"（学 Claude 分类器的 allowed 清单），但**恶意包本体**判定不了——留人工。
3. **命令替换不可解析目标**：`rm -rf "$(./gen.sh)"`。静态规则只能 fail-closed 到 ask。
4. **对话内边界**：用户说"别 push"，属于会话语义，规则层存不住（Claude 也只把它做成易失的分类器信号 + 建议 deny 规则兜底）。
5. **注入语料**：文件/网页内容里的"ignore previous instructions"类文本（OpenHands 专门为它建了第二语料库）。本项目 shell 面窄，风险低，可先不做，但要写进"不保证"清单。

**LLM 判定层的位置**：不是必须品。若加，学 Cursor 的用法——**只审白名单外的 ask 命令**（调用量小、可给"允许/拒绝/转人工"三态），而不是 Claude auto 的全量审查。分类器输入不要带工具结果原文（防操纵）。

### 10.4 最小实现清单

1. 决策序：`deny → ask → allow → mode 默认 → 解析失败=ask`；deny 全档生效。
2. 命令解析：先按 shell 操作符拆段（这是**第一道工序**，先于任何匹配）；wrapper 剥离；每段取 (程序, 子命令, 参数) 三元组做前缀匹配，不玩裸文本 includes。
3. 静态检查器独立于白名单：critical-path rm、下载管道、凭证路径、网络域名、重定向目标——**这些即使命令在 allow 里也要跑**（Claude 的教训："allow 规则救不了 rm 关键路径"）。
4. 审计：每次 deny/ask 落一条结构化日志（规则 id + 命令段 + 原因码），上线后用它驱动白名单调优。
5. 网络：默认全关；域名白名单从 `registry.npmjs.org`（或镜像）+ `github.com` 起步；localhost 放行用于 demo server。
6. 文档化"不保证"：形态学检查会漏（find -delete、脚本内部逻辑）；allow 精确性依赖前缀语义；yolo 无任何保护。

### 10.5 一句话总结

> 用 **Codex 的两旋钮**定档、**Claude 的规则语法与拆段工程**定白名单、**Gemini 的 fail-closed 与配置投毒防御**定治理、**Cursor 的"只审白名单外"**控制 LLM 成本；静态规则覆盖 90% 形态学风险，语义外发/供应链/不可解析目标三处老老实实留人工。

---

## 附：全部来源

**Claude Code**（官方，2026-10 抓取）
- https://code.claude.com/docs/en/permission-modes.md （模式、关键路径、auto 分类器默认 block/allow 清单）
- https://code.claude.com/docs/en/permissions.md （规则语法、通配符语义、复合命令、wrapper、内置只读命令、protected paths、workspace trust）
- https://code.claude.com/docs/en/sandboxing.md （沙箱边界、auto-allow、网络代理、unsandboxed retry）

**Codex CLI**（官方仓库文档镜像 mintlify.wiki，生成自 openai/codex commit 6a673e7；developers.openai.com 本环境 403）
- https://mintlify.wiki/openai/codex/concepts/sandboxing
- https://mintlify.wiki/openai/codex/concepts/approvals
- https://mintlify.wiki/openai/codex/advanced/exec-policies
- https://mintlify.wiki/openai/codex/configuration/basic
- https://raw.githubusercontent.com/openai/codex/main/docs/config.md
- 二手交叉验证：https://cloud.tencent.com.cn/developer/article/2702951

**OpenHands**
- https://docs.openhands.dev/sdk/guides/security.md

**Goose**
- https://goose-docs.ai/docs/guides/managing-tools/goose-permissions
- https://goose-docs.ai/docs/guides/managing-tools/tool-permissions

**Aider**
- https://aider.chat/docs/usage/commands.html
- https://aider.chat/docs/usage/modes.html
- https://aider.chat/docs/git.html
- https://github.com/Aider-AI/aider/issues/3903

**Gemini CLI**
- https://geminicli.com/docs/reference/policy-engine.md
- https://geminicli.com/docs/cli/settings.md
- https://geminicli.com/docs/reference/tools.md

**Cursor**
- https://cursor.com/docs/agent/security/run-modes
- https://cursor.com/docs/agent/security

**VS Code Copilot**
- https://github.com/microsoft/vscode/issues/253314 （设置名变更记录）
- https://4sysops.com/archives/new-in-vs-code-github-copilot-command-allowdeny-lists-resubmit-requests-mcp-server-catalog/ （未直接核验，Cloudflare 拦截）
