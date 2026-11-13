# SalesMind AI 代码审查报告

> **状态提示**：本报告是 2026-10-21 的快照，其中多项问题此后已修复。当前状态以
> [技术债实时账本](technical-debt.md#live-status-ledger-2026-11-12) 与代码、测试为准；
> 本报告正文保留原始记录，不追溯改写。

- 审查日期：2026-10-21
- 审查基准：`main` @ `b5edbf3`，工作区含 67 个已修改文件与约 40 个新增模块（未提交，约 +2,912 行）
- 审查范围：后端 `apps/` 全部业务模块、`config/settings`、前端 `frontend/src` 新增与修改文件
- 审查方式：静态走查 + 定向实机验证（不修改源码，不执行数据库写操作）

---

## 一、总体评估

**评级：B+（良好）。**

系统在权限模型、失败关闭（fail-closed）、来源可追溯这三点上保持了项目宣称的水准，导出与知识抽取是当前完成度最高的部分。主要缺口不是架构性的，而是三类具体问题：

1. 一条确定性守卫可被模型用空字段单方面关闭；
2. 面向匿名与高成本端点的速率限制仍然缺失；
3. 并发与幂等存在若干有界但真实的缺陷。

| 维度 | 评价 | 说明 |
| --- | --- | --- |
| 架构分层 | 优 | 模块化单体边界清晰，`apps/*/services` 承担业务规则，API 层薄 |
| 权限与对象可见性 | 优 | 业务角色与 Django 技术标志彻底解耦，不可见对象统一 404 |
| 失败关闭 | 优 | verifier、provider、导出、stale 判定方向一致，无"错误当通过"路径 |
| 导出链路 | 优 | 冻结快照 + 渲染后指纹复核 + mutation 矩阵测试 |
| 确定性守卫 | 良 | 规则密集且可读，但存在空 linkage 逃逸与条件标记的粗粒度匹配 |
| 并发与幂等 | 中 | advisory lock 无超时；幂等键可选；复检非原子 |
| 接口防护 | 差 | 全局无 throttle，登录接口可无限尝试 |
| 可维护性 | 中 | `solution_prompt_v2.py` 单文件 94 KB；`IntegrityError` 无兜底 |
| 测试 | 良 | 2,897 个用例可收集，参数化覆盖到位；本次未实跑 |

与 2026-08-29 报告的关系：那份报告的问题清单已部分过期——迁移漂移、`budget` 负值、`q` 长度上限三项均已修复；全局限流一项仍未修复。本报告不复述已修复项。

---

## 二、实机验证摘要

| 验证项 | 命令 | 结果 |
| --- | --- | --- |
| Django 系统检查 | `manage.py check` | 通过，0 issues |
| 迁移漂移 | `manage.py makemigrations --check --dry-run` | 通过，`No changes detected`，退出码 0 |
| 依赖一致性 | `pip check` | `No broken requirements found` |
| 测试用例收集 | `pytest --collect-only -q` | 2,897 tests collected |
| 后端测试实跑 | `pytest` | **未执行**：`config.settings.test` 要求 `DATABASE_URL`，本机未提供可用的 pgvector 测试模板 |
| 前端测试与构建 | `npm test` / `npm run build` | **未执行** |

未执行项的原因与边界：测试设置刻意不提供 SQLite 兜底，本次审查也未获授权操作 PostgreSQL 实例或其模板库。因此本报告中的并发结论来自代码与既有测试的对照阅读，不是新一次并发实测。

---

## 三、P1：建议本轮修复

### P1-1　空 requirement linkage 使 unresolved 确定性守卫完全失效

**严重度：高**（确定性安全防线可被生成模型单方面关闭）

**证据链**

```text
apps/sales/services/solution_prompt_v2.py:1242-1245
    validate_claim_fields(..., require_linkage=False)

apps/sales/services/solution_generation_contract.py:99-100,135
    require_linkage=False 时 related_requirement_fields 被移出闭合键集
    fields = value.get("related_requirement_fields", [])   # 默认空列表

apps/sales/services/solution_grounding.py:598-605
    has_unresolved_dependency = any(... for field in related_fields)   # 空集合 -> False
    return has_unresolved_dependency and not (...conditional markers...)

apps/sales/services/solution_unresolved_policy.py:75-78
    unresolved = frozenset(... for field in related_fields ...)        # 空集合
    if not unresolved: return None                                      # 交回原守卫，而原守卫同样放过
```

**触发条件**：模型在任一 proposal 中输出 `"related_requirement_fields": []`，或直接省略该字段。

**后果**：`unresolved → confirmed` 的确定性检查对该条建议返回"不拦截"。此时唯一剩下的防线是概率性 semantic verifier；precision 守卫只识别带数字的断言。这直接违反 `docs/business-rules.md` 中"Explicit non-known object dependencies cannot be hidden by clearing linkage"的声明，也与 `docs/ai-pipeline.md` 对"不能靠清空关联逃避规则"的描述不符。

**修复方向**（两层，建议同时做）

1. 合同层：对 `_TARGETS` 覆盖的 8 个 placement（implementation 的 objective/tasks/deliverables/timing、risk 的 condition/impact/mitigation、milestone 的 outcome）要求 `related_requirement_fields` 至少一项，且该维度满足 `_requirement_has_context`。语义上确实不需要客户需求关联的 placement（architecture overview、component identity、out_of_scope 等）保持可选。
2. 可观测性：`related_fields` 为空时不要直接短路返回 `False`。至少让空 linkage 且文本含 capability 断言/精确数字的 proposal 进入诊断记录，避免"零否决且无日志"。当前这条路径连 `record_rejection` 都不会触发，运维无法发现。

**回归测试**：为 8 个 placement 各补一条"空 linkage + 未确认断言"的负例，断言返回 `unresolved_as_confirmed` 或 `invalid_requirement_linkage`。

---

### P1-2　全局无速率限制，登录与高成本端点裸奔

**严重度：高**（生产安全与费用风险）

**证据**

```text
config/settings/base.py:132-139
    REST_FRAMEWORK = {
        "DEFAULT_AUTHENTICATION_CLASSES": (...),
        "DEFAULT_PERMISSION_CLASSES": (...),
    }
    # 无 DEFAULT_THROTTLE_CLASSES，全仓无任何 Throttle 类

apps/accounts/api/urls.py
    login/ 与 refresh/ 使用 AllowAny
```

**影响**

- `POST /api/auth/login/` 可无限次尝试密码，无锁定、无退避；
- 任意认证用户可无限调用 `/api/rag/answer/`、需求分析、方案生成，直接消耗真实 LLM 与 embedding 额度；
- `knowledge/documents/<pk>/reindex/` 在请求内同步执行 embedding，可被用来占满 worker。

这一项在 2026-08-29 的报告中已列为 P1-3，至今未修复。

**修复方向**

```python
# config/settings/base.py
REST_FRAMEWORK = {
    ...,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {"anon": "20/min", "user": "120/min"},
}
```

登录/刷新接口另用 `ScopedRateThrottle`（例如 `5/min` 按 IP），并对生成类端点单独设更严的 scope。补一条"超过阈值返回 429"的测试。

---

## 四、P2：应排期

### P2-1　幂等键可选，重复提交会重复生成

`apps/sales/api/solution_workflow_views.py:224-237`：未带 `Idempotency-Key` 时 `uuid4()` 生成新 thread，重复 POST 会走完整生成链路并新增版本，只靠版本号唯一约束避免冲突。

后果：用户双击、前端重试或网络重发都会产生重复 provider 调用与重复版本。建议强制幂等键，或由 `(user, opportunity, analysis)` 派生默认键。

### P2-2　advisory lock 无超时且为会话级

`apps/sales/services/solution_persistence.py:280-294` 使用 `pg_advisory_lock`，锁覆盖整段生成与验证（第 145-171 行），无 `lock_timeout`；`pg_advisory_unlock` 未校验返回值。

后果：同一幂等键的第二个请求会阻塞一个 worker 与一条数据库连接直到第一个请求结束（真实链路可达数十秒至分钟级）。当前 `CONN_MAX_AGE` 未设置（默认 0），连接关闭会释放会话级锁，因此暂不构成锁泄漏；一旦启用连接池则会残留。

建议：改为 `pg_try_advisory_lock` + 有界等待并返回 409，或改用 `pg_advisory_xact_lock` 只包住"查重 + 插入"短事务，配合唯一键兜底。

### P2-3　审批期 provenance 复检非原子，误判会被永久持久化

`apps/sales/services/solution_review.py:250-255` 只 `select_for_update(of=("self",))` 锁 draft 行；`_require_current`（351-357 行）随后分多次独立查询 provenance、文档与 chunks。并发 reindex 提交的瞬间可能读到跨快照组合，判为 `GROUNDING_PROVENANCE_INVALID` 并写入 `stale_reasons`。

`project_solution_draft_staleness` 是单调并集，写入后不可清除，该合法版本将永久无法审批与导出，只能人工改库。

方向是 fail-closed（不会放行不安全方案），因此评为 P2 而非 P1。建议在事务内按 `document → fact` 顺序加 `FOR SHARE` 复检，或让 stale 只做读时投影、不落库。

### P2-4　上传无请求体上限，大小校验在接收之后

`apps/knowledge/api/views.py` 使用 DRF `MultiPartParser`，`apps/knowledge/admin_forms.py` 使用 `FileField`；`KNOWLEDGE_MAX_FILE_SIZE_BYTES` 在 `parsers/validation.py` 解析阶段才生效。Django 的 `FILE_UPLOAD_MAX_MEMORY_SIZE` 只决定落内存还是临时文件，不拒绝超限请求。

后果：认证管理员可写入任意大的临时文件与 MEDIA 目录。建议在反向代理设 `client_max_body_size`，并在 `base.py` 显式设置 `DATA_UPLOAD_MAX_MEMORY_SIZE` / 上传流式读取上限。

### P2-5　导出渲染异常被统一报成 503

`solution_export_pdf.py:72` 的 `next(v for k, v in metadata if k == '方案版本')` 可抛 `StopIteration`；空表可抛 `ZeroDivisionError`。这些都被 `solution_export_views.py:49-51` 吞成 `solution_export_unavailable`（503）。

后果：数据缺陷或模板缺陷被伪装成"服务不可用"，掩盖真实问题并污染告警。建议对渲染期异常单独分类为 422 `solution_export_invalid_payload`，仅在真正的基础设施不可用时返回 503。

### P2-6　前端导出 URL 过早释放，可能静默失败

`frontend/src/utils/download.ts:10`：`anchor.click()` 后立即 `setTimeout(() => URL.revokeObjectURL(url), 0)`。

在 Firefox/Safari 或大文件场景，浏览器尚未开始读取 blob URL 即被撤销。此时 `exporting` 已复位、提示已消失、无任何报错，用户以为导出成功但磁盘无文件。建议延迟撤销（≥1s）或在窗口 `focus` 后撤销。

### P2-7　刷新令牌竞态会踢掉刚登录的会话

`frontend/src/stores/auth.ts:16,18-27`：`logout()` 不清空闭包变量 `refreshing`。若旧 refresh 仍在飞行时用户登出并重新登录，新会话的首个 401 会复用旧 promise，旧 promise 因 epoch 变化抛 `session_changed`，`api/http.ts` 判定 session 未变而调用 `expire()` 强制登出。

窗口较窄，但后果是用户正在填写的内容丢失。修复：`logout()` 中重置 `refreshing`，或用 epoch 包裹整个 refresh promise。

### P2-8　JWT 无吊销机制

`config/settings/base.py:141-149` 未安装 `token_blacklist`，`ROTATE_REFRESH_TOKENS` 与 `BLACKLIST_AFTER_ROTATION` 均为 False，也没有登出端点。

后果：refresh token 泄漏后有 7 天有效窗口，只能靠停用账号止损。若定位是展示项目，可在 `known-limitations.md` 明写；若要生产化，应引入黑名单与登出端点。

### P2-9　知识库无文档级可见性

`apps/knowledge/services/search.py:40-47` 只按 `status / provider / model / dimension / document_type` 过滤，`apps/rag/api/views.py` 也仅依赖 `IsKnowledgeSearchUser`。任一 sales 或 presales 用户可检索全部文档正文、标题与原始文件名。

若企业知识库确为全员共享，这是设计选择，但当前 `business-rules.md` 未明确声明知识库的可见性边界，建议补充一句可审计的说明；否则这是一处越权读取。

### P2-10　知识 API 与 Admin 的门禁不对称

`apps/knowledge/api/permissions.py:8-15` 的 `IsBusinessAdmin` 只检查 `role == ADMIN`；而事实审批（`grounding_fact_approval.py`）要求 `is_active + is_staff + role == ADMIN`。

后果：`role=admin` 但 `is_staff=False` 的用户可通过 API 上传文档、触发索引与抽取（产生真实费用），却无法审批事实。`business-rules.md` 已声明这是有意分层，但两个入口的差异容易被后续开发误用为"审批门禁只需 role"。建议在权限类 docstring 与文档中加交叉引用。

---

## 五、P3：观察项

1. **初始索引无崩溃接管路径**：`_start_indexing` 要求 `PENDING`（`indexing.py:129-152`），`_start_reindexing` 要求 `READY`（155-164）。进程在 `PROCESSING` 中崩溃后文档永久卡住，`KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS` 只用于 reindex 分支。建议初始索引同样支持超时接管。
2. **唯一约束冲突无兜底**：生产代码中 `IntegrityError` 引用数为 0（仅测试使用）。`sales_solution_one_pending_review`、`knowledge_extract_active_run_unique` 被违反时返回 500 而非 409。
3. **超长单文件**：`solution_prompt_v2.py` 94 KB，同时承担提示词、解析、合同映射与预算计算。建议按 pass 拆分。
4. **默认配置下 verifier 不独立**：`solution_draft.py:313-320`，`VERIFIER_PROVIDER` 为空时回退为生成 provider，"独立语义审查"在默认路径不成立。属有意的向后兼容，但文档表述应显式标注该降级。
5. **过期的历史审查报告**：`docs/code-review-2026-08-29.md` 的 P1-1、P1-2、P2-1 已修复，P1-3 未修复。会误导后续读者，建议在新报告中标注替代关系（本报告不修改该文件）。
6. **未提交工作区**：约 2,912 行改动与 `apps/knowledge/migrations/0004`、`apps/sales/migrations/0007` 均未跟踪，存在丢失与误部署风险。

---

## 六、已验证正确、无需改动的部分

以下结论来自代码走查与既有测试的对照，不是重新实跑：

| 不变量 | 证据 |
| --- | --- |
| `is_staff` / `is_superuser` 不越权 | `apps/sales/api/opportunity_access.py`、各 `has_permission` 只读 `role`；技术标志仅出现在测试 |
| 不可见对象统一 404 | 导出、工作流、审核均复用 `visible_solution_drafts_for`，无 403/404 混淆 |
| 导出 fail-closed | `solution_export_guard.py:63-93` 校验审批状态、最新决策、stale、需求一致、provenance 完整性 |
| 渲染后复核有效 | `solution_export_views.py:35-38` 重建快照并比对指纹；`test_solution_export_revalidation.py` 用 15 项 mutation 矩阵覆盖 |
| 导出无注入面 | PDF 先 `escape` 再入段落、固定字体路径 + SHA-256、`Content-Disposition` 只拼整数、`nosniff` + `no-store` |
| 上传基于内容校验 | `parsers/validation.py` 校验 `%PDF-` 签名、扩展名白名单、控制字符、页数与大小、basename 化 |
| verifier 严格 veto-only | `solution_grounding.py:811-829` 结果只用于否决，proposals 原样返回，无法写事实 |
| provider 失败 fail-closed | 错误直接抛出，空响应判 `LLM_INVALID_RESPONSE`，超时分类为 `TIMEOUT` |
| 三段隔离与预算 | `MAX_CORE_PROPOSALS=46/18/20/84`，逐段合同校验，前段只以 `<validated_*>` 传入 |
| 准入只认当前来源 | `solution_admission.py:233-246` 要求 `APPROVED + 非 stale + READY + 当前 run + hash 匹配` |
| 无 SQL 拼接与 XSS 面 | 全仓无 `raw()` / `extra()` / `RawSQL` / `mark_safe` / `csrf_exempt`；前端无 `v-html` |
| 生产配置 fail-closed | `production.py` 强制 `DEBUG=False`、HSTS、安全 Cookie、`ALLOWED_HOSTS` 缺失即抛错 |

---

## 七、建议修复顺序

1. **P1-1** 空 linkage 守卫（合同层强制 + 可观测性），补 8 个 placement 的负例
2. **P1-2** DRF 限流与登录 scope，补 429 测试
3. **P2-1 / P2-2** 幂等键强制化、advisory lock 加超时
4. **P2-3** 审批复检加锁或改为只读投影
5. **P2-6 / P2-7** 前端导出撤销时机、`logout()` 清理 `refreshing`
6. **P2-4 / P2-5** 上传请求体上限、导出异常分类
7. **P2-9 / P2-10 / P3-5** 文档边界声明与历史报告标注
8. 提交工作区改动并补齐迁移文件

每一项修复都应附带一条会先失败、后通过的回归测试；并发类修复需要在具备 pgvector 测试模板的环境中实跑，不能用静态阅读替代。

---

## 附：审查动作留痕

- 未修改任何项目源码、迁移或配置；本次仅新增本报告文件
- 未读取、未打印 `.env` 中的任何值；仅确认文件存在
- 未启动、重启或修改 PostgreSQL，未创建测试数据库；`pytest` 因缺少 `DATABASE_URL` 未执行
- 未调用任何真实 provider
- `docs/code-review-2026-08-29.md` 与 `.workbuddy/` 未被读取以外的操作触及
