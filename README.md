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
| `EMBEDDING_*` / `LLM_*` / `VERIFIER_*` | provider 凭据与模型名 |

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

### 定时备份与队列监控

compose 的 `backup` 服务默认启动，在 compose 网络内直连数据库，**不需要宿主机 cron、也不挂载 Docker socket**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `BACKUP_INTERVAL_SECONDS` | `86400` | 备份间隔（秒） |
| `RETENTION_DAYS` | `14` | 保留天数，过期文件自动删除 |

产物写到宿主机 `./backups/`（`db-*.dump` + `media-*.tar.gz`）。`scripts/backup.sh` 仍可随时手动执行一次。恢复演练与 Windows 二进制重定向注意事项见上文。**备份仍在该磁盘上，生产环境请把 `backups/` 再同步到另一台机器或对象存储**，否则磁盘故障会同时丢库和备份。

队列健康检查输出一行 JSON，超阈值时返回非零退出码，交给调度器告警即可：

```bash
docker compose --env-file .env.production.local exec -T web \
    python manage.py check_generation_health
# {"health": {"queued": 0, "running": 0, "oldest_queued_wait_seconds": 0.0,
#             "failed_last_hour": 0}, "thresholds": {...}, "breaches": []}
```

crontab 示例（每 5 分钟，非零退出码发邮件）：

```cron
*/5 * * * * cd /srv/salesmind && docker compose --env-file .env.production.local exec -T web python manage.py check_generation_health --max-queued 10 --max-wait-seconds 600 --max-failed-last-hour 5
```

三个阈值分别对应：排队任务数、最老排队任务等待秒数、近一小时失败数。命令只读，不碰 provider、不改任务状态。

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
