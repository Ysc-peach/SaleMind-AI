# SalesMind AI

面向企业销售与售前的需求分析、知识检索和技术方案辅助系统。

项目不是“把客户需求发给模型生成一段方案”，而是将客户事实、企业能力依据、技术建议和人工审批分开管理：模型负责提出建议，确定性代码负责校验与组织，售前负责最终技术审核。

核心功能历史冻结基线：`1141281c07b2f5f92d51151fc9b2f0803814ef60`。verifier 配置已更新为当前本地选择；历史 benchmark 不代表新模型已通过真实评估。本文不承诺尚未实现的生产能力。

## 业务流程

```text
Sales：Customer / Opportunity → 需求输入 → 版本化 Requirement Analysis
                                                   ↓
企业知识：文档 → BGE 索引 → Grounding Facts → 有权限人员审批
                                                   ↓
技术方案：检索与事实准入 → Core → Implementation → Assurance
                                                   ↓
             严格合同 → 确定性 guards → 独立语义 verifier
                                                   ↓
                    Solution V2 → 版本持久化 + 来源快照
                                                   ↓
Presales：技术审核 → 批准 / 补充客户信息 / 技术修订
```

Sales 维护商机与客户需求；Presales 负责技术判断和审核。`APPROVED` 表示某个方案版本通过内部技术审核，不表示客户签约或自动达成销售结果。

## 已实现的核心能力

- JWT 登录及 `admin / sales / presales` 业务权限，商机按所有者或指派关系隔离。
- 十个固定需求维度及 `known / unknown / unclear / conflict` 状态；分析历史不可覆盖。
- 企业文档解析、分块、BGE-M3 向量索引、pgvector 检索与来源引用。
- Grounding Facts 的提议、人工审批、索引失效与来源有效性校验。
- 三段 bounded generation 与 generation-only Minimal Semantic IR，避免让模型生成数据库 ID、最终结构枚举或持久化对象。
- 原子 claim registry、语义化组件名称、独立的依赖/请求流/数据流、阶段/验收/里程碑关联。
- 确定性 guards 和 veto-only 语义审查；不完整或未通过准入的方案不能部分保存。
- 不可变 Solution 版本、持久 provenance、stale 判断、版本级技术审核及 LangGraph 人工中断/恢复。
- 异步生成队列（202 + worker + 崩溃回收）、并发上限、定时备份与队列健康检查。
- 会话可撤销（登出/改密即失效）、客户资料可修正、售前待审核计数、管理员审计只读视图。
- Vue 销售/售前工作台和 V2 技术方案阅读界面；历史 V1 保持独立兼容展示。

## 技术栈与架构

| 层 | 当前实现 |
| --- | --- |
| 后端 | Python 3.12、Django 5.2、DRF、Simple JWT；模块化单体 |
| 数据 | PostgreSQL + pgvector；业务表、知识索引与来源快照 |
| 生成 | DeepSeek，三段 JSON/Semantic IR 输出 |
| 检索 | OpenAI-compatible BGE-M3，1,024 维 |
| 审查 | 独立配置的 DeepSeek `deepseek-flash`，显式关闭 thinking；历史 Qwen benchmark 保留原记录 |
| 工作流 | LangGraph + PostgreSQL checkpointer；规则仍由 Django 服务执行 |
| 前端 | Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus |
| 测试 | pytest / pytest-django；Vitest / Vue Test Utils |

实际依赖版本以 [后端依赖](requirements/base.txt) 和 [前端依赖](frontend/package.json) 为准。系统没有另设向量数据库或消息队列。

### 四个不能混淆的边界

1. **RAG** 找到相关文档，不代表文档中的能力已获准进入方案。
2. **Grounding** 检查事实是否经过审批、是否仍属当前索引、来源是否匹配；客户需求不能证明企业能力。
3. **Proposal Admissibility** 检查建议的相关性、冲突、无依据承诺及 placement-aware atomicity；verifier 只能否决，不能批准企业事实。
4. **Human Review** 决定方案能否作为正式技术方案使用。生成成功只产生 `DRAFT`，自动质量评分不替代人工审核。

详见 [架构](docs/architecture.md)、[AI 链路](docs/ai-pipeline.md) 与 [业务规则](docs/business-rules.md)。

## 本地运行

以下命令以 Windows PowerShell、项目根目录为上下文。使用 Python 3.12 和 Node.js 24+。PostgreSQL 及 pgvector 必须已由管理员准备；不要用 SQLite 替代，也不要自动修复或启动已有数据库实例。

### 后端

首次创建虚拟环境后，始终使用项目解释器：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.txt
Copy-Item .env.example .env
```

仅首次复制示例，不要覆盖已有 `.env`。在被 Git 忽略的 `.env` 中填写独立开发 secret、数据库连接和必要 provider 配置；示例不含可用凭据。

在明确允许初始化的本地数据库上执行：

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

创建管理账号时须填写业务 `role`。`is_staff / is_superuser` 本身不授予业务 Admin 权限；Grounding Facts 审批要求 active + staff + `role=admin`。

### 前端

另开终端：

```powershell
Set-Location frontend
npm ci
npm run dev
```

访问 Vite 显示的本地地址（默认 `http://127.0.0.1:5173`）。开发代理将 `/api` 转发至 `http://127.0.0.1:8000`；Django Admin 位于 `http://127.0.0.1:8000/admin/`。

### 离线产品演示

`seed_demo` 使用 deterministic providers，不消耗真实模型 API 额度；仍经过正式 parser、准入、持久化和 review 服务。它不是真实模型质量证明。需先配置 `LANGGRAPH_CHECKPOINT_DATABASE_URL`，并仅在独立演示数据库运行：命令会显式建立 checkpoint 表和演示数据。

```powershell
$env:SALESMIND_DEMO_PASSWORD = Read-Host '输入仅供演示的强密码'
.\.venv\Scripts\python.exe manage.py seed_demo
```

使用 `salesmind_demo_sales_a` 或 `salesmind_demo_presales_a` 登录，密码为刚输入的演示密码。五个场景覆盖知识平台、零售协同、企业服务、身份信息不足及电商技术修订。

演示结束可运行 `manage.py clear_demo`；它只清理经身份与引用校验的 demo graph，发生冲突会停止，不会模糊删除用户数据。最后执行 `Remove-Item Env:SALESMIND_DEMO_PASSWORD`。离线 Demo 向量与真实 BGE 索引不能混用；通过 UI 发起新的真实生成需要可用的真实 provider、匹配索引和已审批事实。

完整配置及测试数据库前置条件见 [本地配置说明](docs/local-configuration.md)。

## 验证

后端测试设置不读取 `.env`。在已准备好 pgvector 测试模板的独立环境中提供 `DATABASE_URL` 和 `TEST_DATABASE_TEMPLATE` 后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
git diff --check
```

前端在 `frontend/` 中运行 `npm test`、`npm run type-check`、`npm run build`。普通自动化使用 fake/deterministic providers，不应调用真实 API。

在具备 bash 的环境中可用 `DATABASE_URL=... bash scripts/verify.sh` 一次跑完上述检查；CI 定义见 `.github/workflows/ci.yml`。若在 Gitee Go 上使用，把 `scripts/verify.sh` 的 `backend` 与 `frontend` 两个入口分别配到流水线步骤即可。

冻结基线提交前记录的后端验证为 **1,904 passed**。这是一次离线回归结果，不是线上可用性指标；本次文档整理不会重新宣称全套测试已运行。此后各轮验证结果以 [技术债实时账本](docs/technical-debt.md) 与 CI 记录为准。

## 内网部署（Docker Compose）

适用场景：公司内网单机部署，用户通过浏览器访问。

```powershell
# 1. 准备部署变量文件（不要提交），见下方必需变量
#    .env.production.local 会覆盖 .env 中的同名配置
# 2. 启动
docker compose --env-file .env.production.local up -d --build
```

启动顺序由 compose 保证：`db` 健康后才启动 `web`，`web` 的 `/healthz` 通过后才启动 `nginx`。`web` 的入口脚本会先执行 `migrate` 与 `collectstatic`，再启动 gunicorn。默认入口是 `http://<主机>:8080`。

网络受限时可用镜像源，无需改代码：

```powershell
# .env.production.local
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_REGISTRY=https://registry.npmmirror.com
PGVECTOR_IMAGE=docker.m.daocloud.io/pgvector/pgvector:0.8.6-pg16-bookworm
```

`PGVECTOR_IMAGE` 用于 Docker Hub 不可达的网络；本地可先 `docker pull` 镜像站地址再打标签。

`production.py` 是 fail-closed 的，缺失以下任一变量会直接启动失败，这是有意设计：

| 变量 | 说明 |
|---|---|
| `DJANGO_SECRET_KEY` / `JWT_SIGNING_KEY` | 签名密钥，必须足够长且不入库 |
| `DJANGO_ALLOWED_HOSTS` | 例：`salesmind.internal,10.0.0.12` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | 必须带 scheme，例：`http://salesmind.internal:8080` |
| `DRF_NUM_PROXIES` | 本进程之前的可信反代层数；compose 里是 nginx 一层，填 `1` |
| 8 个 `THROTTLE_*_RATE` | 缺失即启动失败，防止默认值被当成有意配置 |
| `EMBEDDING_*` / `LLM_*` | embedding 与生成 provider 的凭据、模型与地址 |
| `VERIFIER_PROVIDER` / `VERIFIER_MODEL` / `VERIFIER_BASE_URL` | **生产必填**：独立审查不得回退到生成模型；三者缺失，或 verifier 的 provider + model 与生成完全相同，启动时直接报 `ImproperlyConfigured` |
| `VERIFIER_API_KEY` | 只在真正生成时才需要；允许为空启动，便于先加载知识资料，生成仍会在 provider 边界失败关闭 |

登出调用 `POST /api/auth/logout/` 撤销 refresh token；已撤销的 token 不能再换发 access token。当前 access token 最多还有 15 分钟有效期（`ACCESS_TOKEN_LIFETIME`），这是 SimpleJWT 的标准行为。

用户自助改密：页面右上角「修改密码」调用 `POST /api/auth/password/`（需当前密码）。改密成功后该账号**所有** refresh token 立即失效，本人也需要重新登录。账号由管理员在 Django Admin 创建与停用，停用后即时生效。

内网若没有 TLS，必须显式声明，Django 才会关闭 HTTPS 跳转：

```powershell
DJANGO_INSECURE_HTTP=true
```

不设置时 `SECURE_SSL_REDIRECT` 保持开启，内网 HTTP 访问会被重定向到 `https://`。上 TLS 后请删除该变量。

备份与恢复（Linux / macOS / Git Bash）：

```bash
COMPOSE_ENV_FILE=.env.production.local sh scripts/backup.sh
# 生成 backups/db-*.dump 与 backups/media-*.tar.gz
```

```bash
docker compose --env-file .env.production.local exec -T db \
    pg_restore -U salesmind -d salesmind --clean --if-exists \
    < backups/db-<时间>.dump
```

Windows PowerShell 的 `>` / `<` 会把二进制流转成文本，**不要用**；改用 `cmd /c` 做字节级重定向：

```powershell
cmd /c "docker compose --env-file .env.production.local exec -T db pg_dump -U salesmind -d salesmind -Fc > backups\db.dump"
```

恢复演练（2026-11-14，演示库）：备份后停 `web`/`worker`，故意改坏一条商机并清空任务表，再 `pg_restore`，六项校验值（用户 / 商机 / 方案 / 任务行数与两组内容 MD5）全部回到原值，随后服务健康、登录与商机列表均为 200。

演练还暴露并修复了两个部署缺陷：`backup.sh` 的 media 打包命令被镜像 ENTRYPOINT 吞掉（已改为 `--entrypoint sh`）；nginx 在启动时缓存后端容器 IP，重启 `web` 后返回 502（已改为 Docker DNS `resolver` + 变量式 `proxy_pass`）。

### 部署后自检

`/healthz` 只说明数据库通路正常，不代表登录和业务接口可用。部署或升级后跑一次冒烟检查：

```powershell
$env:SMOKE_USERNAME = 'admin'
$env:SMOKE_PASSWORD = '<该账号的密码>'
powershell -NoProfile -File scripts\smoke.ps1
```

```bash
SMOKE_USERNAME=admin SMOKE_PASSWORD='...' sh scripts/smoke.sh
```

它只做只读检查：`/healthz`、未带令牌必须 401、登录、`/api/auth/me/`、商机列表、知识库列表（管理员 200、非管理员 403 都算通过），最后用登录拿到的 refresh token 主动登出并确认它已失效。**不写数据、不打印密码或 token**，任一检查不符即退出码 1。

在容器网络内探测（例如从 web 容器打 `http://nginx`）时，请求的 `Host` 是容器名，会被 `ALLOWED_HOSTS` 拒绝并返回 400。这时加 `SMOKE_HOST`（Linux 用 `-e SMOKE_HOST=<对外域名>`，PowerShell 用参数 `-SmokeHost <对外域名>`）。

### 定时备份与队列监控

compose 的 `backup` 服务默认启动，在 compose 网络内直连数据库，**不需要宿主机 cron、也不挂载 Docker socket**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `BACKUP_INTERVAL_SECONDS` | `86400` | 备份间隔（秒） |
| `RETENTION_DAYS` | `14` | 保留天数，过期文件自动删除 |

产物写到宿主机 `./backups/`（`db-*.dump` + `media-*.tar.gz`）。`scripts/backup.sh` 仍可随时手动执行一次。恢复演练与 Windows 二进制重定向注意事项见上文。**备份仍在该磁盘上，生产环境请把 `backups/` 再同步到另一台机器或对象存储**，否则磁盘故障会同时丢库和备份。

队列健康检查输出一行 JSON，超阈值时返回非零退出码：

```bash
docker compose --env-file .env.production.local exec -T web \
    python manage.py check_generation_health
# {"health": {"queued": 0, "running": 0, "stale_running": 0,
#             "oldest_queued_wait_seconds": 0.0, "failed_last_hour": 0},
#  "thresholds": {...}, "breaches": []}
```

四个阈值分别对应：排队任务数、最老排队任务等待秒数、近一小时失败数，以及**心跳已停但在跑的任务数**（`--max-stale-running`，默认 0）。最后一项是为了覆盖「唯一的 worker 进程自己死了」：这时没人会去回收任务，队列也不会变长，只能由外部检查发现。命令只读，不碰 provider、不改任务状态。

如果调度器只会记一条失败日志、没人看，就让检查自己把告警推出去：

```cron
*/5 * * * * cd /srv/salesmind && docker compose --env-file .env.production.local exec -T web python manage.py check_generation_health --notify --max-queued 10 --max-wait-seconds 600 --max-failed-last-hour 5
```

两个通道各自独立配置，都留空则只靠退出码：

```bash
ALERT_WEBHOOK_URL=https://chat.example.internal/hooks/xxx   # 收 JSON 的机器人地址
ALERT_EMAIL_TO=ops@example.internal,sre@example.internal    # 复用上面的 EMAIL_* 传输
```

`--notify` 推送的内容只有计数、阈值名和触发项，**不含商机名或方案正文**；输出 JSON 会多一个 `alert` 字段，写明 `attempted` / `delivered` / `failed`。推送失败只写一条不含地址的告警日志，**不会改变退出码**——投递成功与否都不能把「队列真的坏了」这件事变成绿灯。没配通道又加了 `--notify` 时，命令会在 stderr 明确说一句，避免静默。

### 跟进事项

商机工作区新增「跟进」页签：每条事项有标题、到期日和负责人，可标记完成或重新打开。工作台与提醒口径如下：

- `GET /api/follow-ups/mine/` 把「已逾期」和「7 天内到期」分开返回，供页面和脚本使用；
- 负责人默认是创建人，也可以指派给该商机的另一位负责人；
- 只有该商机的销售负责人、售前负责人或管理员能新建和处理；已归档（停用）的商机不再接收新事项，但**已有的仍可关闭**；
- 逾期任务可用下面这条命令交给调度器，超过 `--max-overdue` 时非零退出：

```cron
0 9 * * * cd /srv/salesmind && docker compose --env-file .env.production.local exec -T web python manage.py list_due_follow_ups --max-overdue 0
```

输出形如 `{"today": "2026-11-19", "overdue": 2, "tasks": [{"project_name": "...", "title": "...", "days_late": 4, ...}]}`，只含商机名、事项和逾期天数，不含方案正文。

### 案例库

区别于知识库：文档是「事实」的证据，案例是「故事」——行业、规模、客户痛点、我们的做法、结果。售前按**相似度**找案例，不是按全文匹配。

- `GET /api/case-studies/`：按行业、规模、是否可对外引用、关键词筛选，默认只返回启用案例；`include_inactive=1` 仅管理员可用；
- `POST /api/case-studies/`、`PATCH /api/case-studies/{id}/`：**仅售前与管理员**可写。销售可读但不可写——能编辑的案例库很快会被写成没人能在客户面前复述的样子；
- `POST /api/case-studies/{id}/archive|restore/`：停用而非删除，历史引用不受影响；
- `GET /api/case-studies/match/?industry=&size_band=&limit=`：**排序而不是过滤**——同行业优先、同规模次之、可对外引用优先。严格过滤通常一条都不剩，售前就只能凭记忆写这一节。

`referenceable` 是显式字段，不从客户名称推断：要在方案里点名客户，需要对方同意。

前端入口：侧边栏「案例库」（三种角色都能进，只有售前与管理员看得到写操作）。商机详情页的「概览」还会按**客户行业**列出最接近的 5 条案例——按相似度排序，因此近似的也会出现；不可对外引用的案例在列表里显示为「匿名客户」。

### 竞品与公开陈述

竞品是**实体**而不是字符串：「华为云 / 华为云Stack / Huawei Cloud」写成三种就永远比不到一起，而比较表要跨方案复用很多年。所以先建实体（`/api/competitors/`，售前与管理员可建），再登记陈述。

每条陈述绑定一个**受控维度**、一句**中性表述**、一个**来源链接**和**采集日期**：

| 维度 | 对应受控主题 |
|---|---|
| 部署形态 | `private_deployment` / `kubernetes_deployment` |
| 数据驻留 | `intranet_data_residency` / `public_network_transfer` |
| 身份与集成 | `sso_integration` / `oa_integration` / `jwt_authentication` |
| 数据存储 | `postgresql` / `pgvector` / `oracle_compatibility` |
| 文档处理 | `scanned_pdf_ocr` |
| 交付物 | `contract_generation` / `csv_bulk_export` |
| 服务器兼容 | `server_compatibility` |
| 知识检索 | `enterprise_knowledge_query` |

三条硬规则：

1. **不做否定断言**。`不支持…`、`未提供…`、`does not support…` 这类表述在登记时就被拒（`400 competitor_negative_claim`）——它们无法用对方原话自证，写进方案被客户核对时最伤信任；
2. **必须有可访问来源**：`source_url` 只接受 http/https，另记 `published_on`（对方发布日期）与 `captured_on`（我们采集日期），方便判断是否过时；
3. **只有管理员能审批**。售前可以登记，但陈述在 `approved` 之前不会被比较表或生成引用；审批人与时间成对落库（数据库约束），和审核决定同一套规则。

竞品停用后不删除：历史陈述仍按 id 可读，但默认列表与后续比较都不再出现。

前端入口：侧边栏「竞品库」。三种角色都能看；售前可新建竞品、登记陈述（提交后为「待审批」），只有管理员能看到并点击「批准 / 拒绝」。登记被拒时页面会说明原因（例如否定断言），而不是只显示「400」。

**对照矩阵**（`GET /api/opportunities/{id}/competitor-matrix/?competitor=<招标号>`，可重复传多个；不传则用全部启用竞品，最多 5 个）：

```json
{"opportunity_id": 7, "formable_rows": 1, "total_rows": 8,
 "dimensions": [{"dimension": "deployment", "label": "部署形态",
   "competitors": [{"competitor_id": 3, "competitor_name": "竞品甲",
     "own_facts": [{"id": 12, "subject_key": "private_deployment", "statement": "..."}],
     "statements": [{"id": 5, "statement": "...", "source_url": "https://..."}],
     "can_form": true, "gap": ""}]}]}
```

每行只有「我方已批准事实 + 竞品已批准陈述」都在时 `can_form` 才为真；否则 `gap` 明确写出缺哪一侧（`missing_both` / `missing_own_fact` / `missing_competitor_statement`）。这一步先让**能不能写**变成可查询的事实，生成接入再据此决定写或留空。矩阵固定两次查询（事实一次、陈述一次），与维度数量无关。

### 异地备份

`backup` 服务在把 dump 命名为正式文件前会先用 `pg_restore -l` 读一遍目录表；读不通的归档会被丢弃，不会覆盖历史好备份，也不会被同步脚本选中。

把最新一组同步到另一台机器（依赖运维侧已配置好的 SSH key，脚本不读取或保存任何凭据）：

```powershell
$env:OFFSITE_TARGET = 'backup@nas.internal:/srv/salesmind-backups'
powershell -NoProfile -File scripts\offsite-sync.ps1
```

目标必须是 `user@host:/path` 形式。脚本会先在 backup 容器里复核 dump 完整性，再用系统 `scp` 复制 `db-*.dump` 与 `media-*.tar.gz`，任一步失败都返回非零退出码。Linux 部署可直接用等价命令：

```bash
scp backups/db-<时间>.dump backups/media-<时间>.tar.gz backup@nas.internal:/srv/salesmind-backups
```

把这条命令接在调度器里（例如每天备份后半小时），就完成了「数据库与备份不在同一块磁盘」。目标机器与 SSH 账号属于部署环境，仓库不预置。

已知限制：生成链路目前**默认仍是同步的**，单次 95–98 秒；nginx 已把 `proxy_read_timeout` 放到 300 秒。`SOLUTION_GENERATION_MAX_CONCURRENT`（默认 2）通过 PostgreSQL advisory lock 限制同时生成数，超出的请求返回 429 `workflow_capacity_reached`，不会拖垮整个实例。

要开启异步生成（`POST` 立即返回 `202`，前端轮询状态）：

```powershell
# .env.production.local
SOLUTION_GENERATION_ASYNC=true
```

compose 里的 `worker` 服务会消费 `SolutionGenerationJob` 队列；它依赖 `web` 健康启动，以保证迁移已完成。该开关默认关闭，出问题可改回 `false` 并重启 `web`，立即退回同步模式。

## 日常操作

下面按角色说明上线后每天要点的东西。所有页面都在 `http://<主机>:8080`，账号由管理员在 Django Admin 创建，没有自助注册。

### 首次上线（管理员）

1. 进入 `http://<主机>:8080/admin/`，用初始 `admin` 账号登录后**先点右上角「修改密码」**——初始密码是随机生成的，且在交付记录里出现过一次，必须换掉；
2. 在 Admin「用户」里创建同事账号，必须同时设置 `role`（销售 / 售前 / 管理员）与「员工状态」；
   - 停用账号即刻生效：禁用后该用户下一次请求就会被拒绝，不需要等 token 过期；
3. 按 `docs/admin-knowledge-workflow.md` 上传企业资料 → 确认抽取待审事实 → **逐条人工审批**。不要批准模型标为 `unconfirmed` 的条目，那等于替客户编造企业能力。

### 销售

1. 「客户」页建客户或在搜索里找到已有客户；客户资料是团队共享的，**任何销售都能修正**（改名前请确认不是另一条商机的依据）；
2. 「商机」页建商机，可指派售前负责人；
3. 进商机详情 → 保存客户需求 → 创建分析快照 → 选择快照生成方案；
4. 方案生成后先自查，再「提交售前审核」。审核状态可在方案页看到。

### 售前

1. 侧边栏「待审核」上的红色角标是待办数量，每次切换页面会刷新——不需要手动轮询；
2. 审核时可以「通过」或「退回」，退回必须给出原因（需要补充客户信息 / 需要修改技术方案）；
3. 方案作者不能审核自己提交的版本。

审核指派后可以提醒被指派人，两个通道都是可选的、互不依赖：

```powershell
# .env.production.local —— 只要群消息，不需要邮件服务器
REVIEW_WEBHOOK_URL=https://chat.example.internal/hooks/reviews
SALESMIND_PUBLIC_BASE_URL=http://salesmind.internal:8080

# 或者走邮件
NOTIFICATION_EMAIL_ENABLED=true
EMAIL_HOST=smtp.example.internal
EMAIL_PORT=587
EMAIL_HOST_USER=salesmind@example.internal
EMAIL_HOST_PASSWORD=<密码>
DEFAULT_FROM_EMAIL=salesmind@example.internal
```

Webhook 收到的是这样一份 JSON，聊天机器人可以直接贴成一条消息：

```json
{"version": 1, "kind": "solution_review_assigned", "review_id": 12,
 "project": "某某企业内部知识库", "solution_version": 3,
 "reviewer": "张三", "submitted_by": "李四",
 "url": "http://salesmind.internal:8080/solutions/42"}
```

两个通道都只在审核创建并**提交成功之后**触发（事务提交后回调），内容只有商机名、版本、审核人与链接，**不含方案正文**。任一通道失败只写一条不含地址/收件人/正文的告警日志，提交本身仍然成功；被指派人的邮箱为空时，webhook 照样会发——这正是它存在的意义。

### 管理员运维

| 想做的事 | 位置 |
|---|---|
| 看谁提交、谁审核、谁发起了生成 | 侧边栏「审计」：只读，可按操作人、状态、日期筛选，每页 20 条 |
| 知识库上传、重新索引、事实审批 | `/admin/` → 知识库 |
| 队列是否积压 / 近期失败 | `manage.py check_generation_health`（见上文） |
| 备份是否正常 | `docker compose logs backup`、`backups/` 目录 |
| 用户离职或换设备 | Admin 停用账号；用户自助改密会让所有会话立即失效 |

角色边界（后端强制，不是前端隐藏按钮）：

| 能力 | 销售 | 售前 | 管理员 |
|---|---|---|---|
| 客户建档 / 修正 | ✅ | ❌ | ✅ |
| 商机建档 | ✅ | ❌ | ❌ |
| 商机修改 | ✅ 仅自己负责的 | ❌ | ❌ |
| 提交审核 | ✅ 自己负责的商机 | ✅ 自己是售前负责人的商机 | ✅ 任意，但自己创建的不行 |
| 审核方案 | ❌ | ✅ 必须是该案被指派的审核人 | ✅ 任意，但自己创建的不行 |
| 维护跟进事项 | ✅ 自己负责的商机 | ✅ 自己是售前负责人的商机 | ✅ 任意 |
| 案例库 | ✅ 只读 | ✅ 维护（新建 / 修改 / 停用） | ✅ 任意 + 查看已停用 |
| 竞品与公开陈述 | ✅ 只读 | ✅ 登记（竞品、陈述） | ✅ 登记 + 审批 |
| 停用 / 恢复客户与商机 | ❌ | ❌ | ✅ |
| 查看已停用记录 | ❌ | ❌ | ✅ |
| 审计视图 | ❌ | ❌ | ✅ |
| 知识库写入、事实审批 | ❌ | ❌ | ✅（需同时是 Django 员工账号） |

「自己不能审自己」是硬约束，不是前端隐藏：服务端在决定环节返回 `solution_review_self_review`。

**停用不是删除。** 客户和商机都没有物理删除接口，因为方案、审核记录与逐条 provenance 都指向它们。停用后的语义是三条：

1. **历史照常可读**：按 id 打开、方案列表、审核流转都不受影响，停用前已提交的审核可以走完；
2. **不再接新工作**：不能再建需求分析、不能再生成方案、不能在其下新建商机，修改也返回 `409 record_inactive`；
3. **对非管理员不可见**：列表与搜索默认只返回启用的记录，`?include_inactive=1` 只有管理员能用（其他人得到 403）。

停用与「商机状态」是两件事：`status` 是业务结果（进行中 / 赢单 / 丢单 / 已关闭），`is_active` 是「这条记录还归不归我们继续投入」。销售不能自行改动 `is_active`，提交该字段会被当作服务端字段拒绝。

## 真实 benchmark 证据

后台资料管理的新源码入口与部署前提见 [Admin 知识文档与企业事实操作](docs/admin-knowledge-workflow.md)。
它区分上传索引、待审事实抽取和人工批准，不通过演示脚本伪造真实业务审批；新增 schema 的业务库应用与真实 provider 验收仍需单独确认。

- `manufacturing_knowledge` 已完整通过真实生成链路并持久化 Solution + Provenance，运行基线为 `33157ed`。
- `enterprise_service_approved` 在 `1141281` 完整通过；71/71 verifier claims 为 `ADMISSIBLE + ATOMIC`，写入 317 条 provenance，`solution-quality-v2.1 = 91/100`，四项自动 hard gates 全 PASS。
- 企业服务 Core 首次输出违反局部数量合同，现有 bounded regeneration 自动恢复一次；没有放宽 parser 或手工修改输出。

这是两个已观察到的成功运行，不代表五场景稳定通过。benchmark 使用固定需求与事实 fixture 准备上下文；真实调用范围及各层指标见 [真实 benchmark 总结](docs/real-provider-benchmark-summary.md)。历史 87 分使用旧 rubric，不能直接与 91 分比较。

## 交付阅读入口

- [核心架构](docs/architecture.md) / [AI pipeline](docs/ai-pipeline.md)
- [业务权限与安全规则](docs/business-rules.md)
- [真实 benchmark 总结](docs/real-provider-benchmark-summary.md) / [分层评估口径](docs/benchmark-layered-evaluation.md)
- [自动质量 rubric v2.1](docs/solution-quality-rubric.md)
- [Known Limitations](docs/known-limitations.md)
- [面试技术复盘](docs/interview-retrospective.md)
- [设计决策](docs/decisions.md) / [历史技术债](docs/technical-debt.md)

当前定位是可验证的求职展示项目，不是已证明具备高并发、生产 SLA 或自动售前审批能力的系统。

## 已审核方案导出

方案详情页提供 Word / PDF 下载。后端只允许仍有效且最新技术审核已批准的可见版本，生成后再次核验权限与来源；不调用模型，不改审批。部署需包含文档依赖和中文字体资产。操作、限制与错误见 [方案导出](docs/solution-export.md)。

### 竞品对照附录

导出时可追加 `&competitor=<竞品ID>`（可重复，最多 5 个）：

```
GET /api/solution-drafts/{id}/export/?file_type=pdf&competitor=3&competitor=4
```

它**不是模型写的**。附录由数据直接拼成：每一行要么是我方已批准事实，要么是竞品自己已批准的公开陈述（带来源链接与发布日期），只有两侧都有依据的维度才成行；缺依据的维度会以「未纳入对照的维度（缺少可引用依据）」列出来，而不是留空或补一句判断。附录开头写明「不构成评价、优劣判断或能力贬损，未列出不等于对方不具备」。

不带这个参数时，导出的就是审核通过的那一版，字节与审批时一致。

### 价目表（第一轮）

价格是这套系统里第一份商业敏感数据，所以第一版只做「可信的单价来源」，不做报价单：

| 决定 | 做法 |
|---|---|
| 谁维护 | **只有在 Django Admin 里维护**（`/admin/` → 价目条目）。价格改动是稀有且需留痕的动作，Admin 日志会记下是谁改的 |
| 可复现 | **只追加**：同一 SKU 的不同生效日各占一行，`(sku, effective_from)` 唯一；改价 = 新增一行，不是覆盖 |
| 取值 | `GET /api/price-book/` 返回每个 SKU **已生效的最新一行**；`?as_of=YYYY-MM-DD` 可查历史时点 |
| 不能删 | Admin 禁用了删除：报价会引用这些行，删掉等于删掉「当时为什么是这个价」 |
| 不含成本 | 表里没有成本价、毛利率字段——不存就不会在导出里泄漏 |

```
GET /api/price-book/?sku=SKU-1
GET /api/price-book/?q=企业&as_of=2026-06-01
```

金额在 JSON 里是**字符串**（`"1200.00"`），避免浮点在路上把它四舍五入；币种默认 `CNY`，第一版不支持多币种换算。停用（`is_active=false`）的条目默认不返回，`include_inactive=1` 仅管理员可用。

下一轮才会把价目接进报价行：报价行会**冻结**当时单价，方案重新生成后旧报价单拒绝导出。
