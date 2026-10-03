# 本地运行与配置

对应核心基线 `1141281c07b2f5f92d51151fc9b2f0803814ef60`。本文只描述现有配置，不要求修改任何 provider、预算或数据库实例。

## 环境前置条件

- Python 3.12；项目 `.venv` 安装 [requirements/dev.txt](../requirements/dev.txt)。Windows 已验证运行方式是从项目根目录使用 `.venv\Scripts\python.exe`。
- Node.js 24+；前端使用 `npm ci` 安装 [锁定依赖](../frontend/package-lock.json)。
- 已准备好的 PostgreSQL（项目本地使用 17）及 pgvector；不支持 SQLite 替代测试或应用数据。
- 数据库账号、数据库创建、扩展权限、测试模板和 checkpoint 表的初始化由管理员在明确授权的本地目标完成；已有实例掉线时先停止，不自行重启/修复。

## 配置加载

首次复制根目录 [.env.example](../.env.example) 为 `.env`，不要覆盖已有配置。`config.settings.local` 读取被 Git 忽略的 `.env`，且进程环境优先；`config.settings.test` 不读取 `.env`。

`DJANGO_SECRET_KEY`、`JWT_SIGNING_KEY` 应分别使用独立开发随机值；`DATABASE_URL` 使用自己的本地连接。示例中的 `replace-with-*` 不可作为真实密码。API keys 仅填入本地秘密配置，禁止提交、打印或复制到 benchmark/文档。

默认本地入口为 Django `127.0.0.1:8000` 与 Vite `127.0.0.1:5173`；Vite 代理 `/api`，不需要在前端暴露模型密钥。初始化命令见 [README](../README.md#本地运行)。

## 三个独立 provider

| 用途 | 对应环境配置 | 本地展示配置 |
| --- | --- | --- |
| Embedding | `EMBEDDING_PROVIDER / MODEL / API_KEY / BASE_URL / DIMENSIONS` | `openai_compatible`、`BAAI/bge-m3`、1024 维；服务地址和 key 自行安全填写 |
| Generation | `LLM_PROVIDER / MODEL / API_KEY / BASE_URL` | `deepseek`、`deepseek-v4-flash`、`https://api.deepseek.com` |
| Proposal verifier | `VERIFIER_PROVIDER / MODEL / API_KEY / BASE_URL` | `openai_compatible`、`qwen3.8-flash`、`https://dashscope.aliyuncs.com/compatible-mode/v1` |

这些是项目配置值，不保证任意外部账号都有模型权限或额度；本文没有进行实时 provider 能力/价格查询。

### Qwen verifier

```dotenv
VERIFIER_PROVIDER=openai_compatible
VERIFIER_MODEL=qwen3.8-flash
VERIFIER_API_KEY=
VERIFIER_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VERIFIER_TIMEOUT_SECONDS=60
VERIFIER_MAX_RETRIES=0
VERIFIER_MAX_OUTPUT_TOKENS=1500
VERIFIER_MAX_CONCURRENCY=2
```

`VERIFIER_API_KEY` 在示例中必须空白。当前 [verifier_factory.py](../apps/llm/verifier_factory.py) 固定 `thinking_enabled=False`；支持 Qwen3 thinking control 时正式 wrapper 发送 `extra_body={"enable_thinking": false}`。没有 `VERIFIER_THINKING_ENABLED` 环境变量，不要添加一个无效配置项。`LLM_THINKING_ENABLED` 属于生成 provider，不控制独立 verifier。

如果 `VERIFIER_PROVIDER` 未配置，代码保留由生成 provider 执行 verification 的历史路径；这不是 provider 失败后的自动 fallback。本项目真实展示基线应显式配置独立 Qwen。

### 输出空间与结构预算

`SOLUTION_DRAFT_MAX_OUTPUT_TOKENS=6000` 是每个 Solution V2 pass 的输出 hard ceiling，覆盖普通 LLM 任务的默认 token 参数；`LLM_MAX_OUTPUT_TOKENS=1024` 仍是普通任务默认值，不应据此认为方案只得到 1024 tokens。

结构预算不是环境变量：Core 46、Implementation 18、Assurance 20、global 84、components 4 来自 [正式 generation contract](../apps/sales/services/solution_generation_contract.py)。它们是上限，不是必须填满的数量。不要用运行配置偷偷放宽合同。

## 数据与 checkpoint

应用 migrations 包括 pgvector 与业务表。只在确认允许初始化的数据库执行 `manage.py migrate`，不在共享/生产数据上随意建立测试资源。

`LANGGRAPH_CHECKPOINT_DATABASE_URL` 默认空白，durable review workflows 和 `seed_demo / clear_demo` 需要显式配置。可以使用已授权的本地数据库连接；checkpointer 不在 import 时建表。

对明确授权初始化的 checkpoint 数据库，可显式执行：

```powershell
.\.venv\Scripts\python.exe manage.py shell -c "from apps.sales.services.solution_workflow_checkpoint import setup_solution_workflow_checkpoint_schema; setup_solution_workflow_checkpoint_schema()"
```

该操作建立官方 PostgresSaver 表，不是 Django migration；`seed_demo` 也会显式调用它。checkpoint 只保存编排 ID/状态，业务批准仍在 SalesMind 数据表。

## 离线 Demo 与真实生成不要混用

`seed_demo` 读取**进程环境**中的 `SALESMIND_DEMO_PASSWORD`，经 Django password validation 后创建专用演示账号；不要把演示密码写进仓库。命令构造五套不同的 solution fixture 并走正式 parser/assembler/admissibility/persistence/review，provider 为明确注入的 deterministic 实现。

重复 seed 使用已有身份和幂等 key；冲突会 fail closed，不 silent overwrite。`clear_demo` 校验 graph 与外部引用后只清理已拥有的 demo records/checkpoints，不清理一般用户数据。

真实生成需可用模型凭据、正式 BGE 索引与已审批 facts。search 会校验 provider/model/dimension；改变配置后不能把旧 demo vectors 伪装成 BGE metadata。真实 benchmark 使用 [隔离 harness](../apps/sales/services/real_provider_benchmark.py) 的正式 indexing/preflight 与 ownership cleanup，不能以 demo renderer 截图证明模型质量。

## 离线测试

测试使用 `config.settings.test`、PostgreSQL、fake/deterministic providers。独立 verifier 凭据在 test settings 被清空；不要手工添加真实调用到普通测试。

由管理员预先准备带 pgvector 的 `salesmind_test_template`，或通过 `TEST_DATABASE_TEMPLATE` 指向合格模板。测试账号需要 pytest-django 创建测试数据库的权限。此文不提供自动修改角色或模板的“修复”脚本。

在专用测试终端安全提供环境配置：

```powershell
$env:DATABASE_URL = Read-Host '输入本地 PostgreSQL 测试连接（不要粘贴到聊天或文档）'
$env:TEST_DATABASE_TEMPLATE = 'salesmind_test_template'
.\.venv\Scripts\python.exe -m pytest
```

运行结束清除该终端的连接变量。进程环境优先于 `.env`，因此不要让测试连接无意覆盖随后开发 server 的目标。

`manage.py check` 与 `makemigrations --check --dry-run` 不应触发真实模型调用；后者需要正常数据库连接以验证迁移历史，但不应用新 migration。前端在 `frontend/` 执行 `npm test / npm run type-check / npm run build`。

## 常见问题的边界

- `ModuleNotFoundError: environ / config`：核对项目解释器、根目录和 `manage.py` 启动上下文；不要用临时脚本目录当 import root 或切换全局 Python 掩盖问题。
- 无检索结果：检查 READY 和 provider/model/dimension/index-run，不绕过兼容过滤器。
- 403：查看安全 SDK/status/provider code；可能是权限或额度，不等于 credential 错误，也不等于业务 veto。
- 无法审批 facts：检查 active + staff + business admin；不要给生产权限规则开例外。
- contract / grounding / verifier failure：系统应失败且不保存半份 Solution；不要修改 payload 使它“能演示”。

限制与结果见 [Known Limitations](known-limitations.md)、[真实 benchmark](real-provider-benchmark-summary.md)。
