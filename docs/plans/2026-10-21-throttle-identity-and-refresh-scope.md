# 批次 1.1：让限流身份可信 + 续期独立配额（交实施 agent 执行）

- 制定日期：2026-10-21
- 分支：`codex/phase-five-presales`。工作树含**批次 1 的未提交改动**与本周期更早的未提交工作；本批次**不做任何 git 提交**，完成后把分组建议写进交付报告。
- 与批次 1 重叠的文件（`config/settings/base.py`、`config/settings/production.py`、`.env.example`、`docs/known-limitations.md`）请先确认批次 1 已提交，否则同一文件两批 hunk 混在一起。
- 当前基线（本会话独立复算过）：后端 **2929 passed / 0 failed**（534s）、前端 **152 passed / 13 files**、`vue-tsc --noEmit` 干净、`manage.py check` 0 issues、`makemigrations --check --dry-run` 无变更。本批次结束后用例数不得减少。

## 0. 执行纪律（每条都必须遵守）

1. 每个 shell 调用都要重新注入环境，否则 `config.settings.test` 直接 `ImportError: Set the DATABASE_URL`，连 `--collect-only` 都跑不起来：
   ```bash
   cd "D:/pycharm-project/SalesMind AI" && set -a && . ./.env >/dev/null 2>&1; set +a
   ./.venv/Scripts/python.exe -m pytest -q --reuse-db
   ```
2. **用例数只信 `pytest --collect-only -q`**；`grep "def test_"` 会把 `.venv` 第三方测试算进来。
3. 不要修改、重启、修复或替换 PostgreSQL 实例、端口、PID、角色、模板、扩展。本机 `pip-audit` 不可用且无网络，**不要声称做过依赖漏洞扫描**。
4. 不要改动 `docs/code-review-2026-08-29.md`。
5. 每条新测试的验收是三段式：**先红 → 改实现转绿 → 把实现点改回缺陷形态确认必红**。"测试恒绿"不算通过。变异用的临时脚本放**仓库根目录**（Git Bash 的 `/tmp` 与 Windows 解释器路径不一致，`open('/tmp/x')` 会 FileNotFoundError 导致注入静默失败），用完删除。
6. 两个代码任务各自独立提交（提交消息沿用仓库 conventional commits 风格，首行祈使句、能独立检索），文档任务并入第 1 个提交。

---

## 任务 A（P1）匿名限流的身份来源必须可信

### 缺陷

`REST_FRAMEWORK` 里没有 `NUM_PROXIES`（`config/settings/base.py:141-166`，实测 `api_settings.NUM_PROXIES is None`）。DRF 3.18 的取键逻辑（`.venv/Lib/site-packages/rest_framework/throttling.py:23-41`）在 `num_proxies is None` 时执行：

```python
return ''.join(xff.split()) if xff else remote_addr
```

即**把客户端自报的整串 `X-Forwarded-For` 当作身份**。攻击者每请求换一个头值就换一个计数桶，`login 10/min` 可被无限分桶绕过 → `docs/code-review-2026-08-29.md` 的 P1-3（登录可撞库）实际上没有被关闭。`config/settings/production.py:46` 的 `SECURE_PROXY_SSL_HEADER` 证明目标部署拓扑就在反代之后，该分支必然被走到。

### 影响范围（写文档时别夸大也别缩小）

| 桶 | 取键 | 是否受伪造 XFF 影响 |
| --- | --- | --- |
| `anon`（`AnonRateThrottle`） | IP / XFF | **是** |
| `login`、`refresh`（`ScopedRateThrottle`，未认证） | IP / XFF | **是** |
| `user`（`UserRateThrottle`）与 `solution_generation` / `requirement_analysis` / `rag_answer` / `knowledge_write` | `request.user.pk` | 否 |

所以这条修的是"撞库与匿名面"，不是"全部限流可绕"；反过来也别让读者以为修完就有全局配额——进程内 LocMemCache 的非全局性见 `docs/known-limitations.md` 第 9 节。

### 改法

1. `config/settings/base.py`：`REST_FRAMEWORK` 内加 `"NUM_PROXIES": env.int("DRF_NUM_PROXIES", default=None)`。
2. `config/settings/production.py`：`DRF_NUM_PROXIES` 缺失或不是正整数即 `ImproperlyConfigured`，并入现有 `_THROTTLE_ENV_VARS` 检查块的同一风格（:22-38）。**不提供默认值**：层数设小（两层 CDN→nginx 只填 1）会把全站并进一个桶，10/min 变整站 10/min；设大（单层填 2）`addrs[-2]` 正好落在攻击者伪造段，洞原样保留。两个方向都要写进错误提示或文档。
3. `config/settings/test.py`：显式 `REST_FRAMEWORK["NUM_PROXIES"] = 1`（模拟单层可信反代），使行为测试跑在真实拓扑语义下。注意 test.py 现有写法是对 `REST_FRAMEWORK` 做 dict 覆盖（:26-32），改动要保持同一段风格。
4. `.env.example`：加 `DRF_NUM_PROXIES=1` 与一句注释"等于可信反代层数；本地直连无 XFF，填 1 无害"。
5. `docs/known-limitations.md` 第 9 节（:154 起）补三点：身份分 IP 桶与 user 桶两类；IP 桶要求反代必须用 `$proxy_add_x_forwarded_for`（追加）或 `$remote_addr`（覆盖），且 `DRF_NUM_PROXIES` 必须等于可信层数；层数错配的两个后果。

### 测试（关键：红必须落在配置守卫上）

新建 `apps/accounts/tests/test_throttle_identity.py`（或与 `test_rate_limiting.py` 同域二选一，别造第三处）：

1. **配置守卫**：断言生效配置里 `NUM_PROXIES is not None`；再加一条 production 语义的守卫（可在被测模块层面断言"缺 `DRF_NUM_PROXIES` 会 `ImproperlyConfigured`"，用 `override_settings`/import 期检查或最小化 env 复现，别和真实测试库耦合）。**这条在修复前必须是红的**；删掉 `NUM_PROXIES` 配置项后也必须红。
2. **行为对（同桶）**：在 `NUM_PROXIES=1` 下，两次登录带 `X-Forwarded-For: 1.1.1.1, <固定末段>`、`3.3.3.3, <同一末段>`，第三次应 **429** —— 证明前缀被丢弃、只取反代追加的那一段。
3. **行为对（不并桶）**：末段换成不同值时**不得 429** —— 证明不是把所有客户端并进一个桶（防止"设成 0"这类假修复）。
4. **防退化**：同一已认证用户伪造 XFF，其 `solution_generation` 配额仍按 `user.pk` 累计（防将来有人把全部 scope 改成 IP 键）。

⚠️ 只用 `override_settings(NUM_PROXIES=1)` 然后断言"伪造失败"的那条测试**在修复前后同绿**，不能当唯一防线——这就是为什么第 1 条必须存在。

## 任务 B（可用性）refresh 用独立 scope

`apps/accounts/api/views.py:23-28` 的 `RefreshView` 现在复用 `login` 桶（两个视图都 `throttle_scope = "login"`，:20 与 :28）。后果不是安全而是可用性：同一 NAT 出口下有人撞库打满 `login` 后，所有合法 token 续期一起 429，用户表现为"正在填表被踢出"。

改法：新增 scope（如 `token_refresh`）+ `base.py` 的 `DEFAULT_THROTTLE_RATES` 加对应项 + `production.py` 必填清单同步加一项 + `.env.example` 补值 + `RefreshView.throttle_scope` 改为新值。

**不要做** IP+username 复合键：攻击者换用户名即换桶，等于把桶数量开放给攻击者。保持 IP 桶 + 在限制文档写明"共享出口下互相牵连"是成本收益最好的形态。

测试：至少一条"login 桶打满不影响合法 refresh 续期"，以及一条"refresh 桶自身超限返回 429 + `code: rate_limited`"。

## 任务 C（纯文档，无代码）把 checkpoint 正向分叉记为已知限制

已在批次 1 复核确认：这不是放宽守卫能解决的。`solution_review.py` 的 `_validate_submission` 要求 `review_status == DRAFT`（约 :120-124），而工作流的 `can_recover_terminal_review_submission` 会走同一校验，因此**即使把 `solution_review_workflow.py:328` 的 `solution.reviews.exists()` 收窄，恢复依然被拒**。真正的缺口是"业务库已是 PENDING_REVIEW、LangGraph 线程仍停在 sales 确认中断"时，没有任何入口把线程推进到 `wait_for_presales_review`；补它需要新增一条显式对账分支。REST 审核路径仍可用、业务数据不损坏，属可用性死胡同。

本任务**只**在 `docs/known-limitations.md` 第 8 节（:144 起，"尚未扩展的产品范围"）加一句事实：该情形下工作流线程不可恢复，须改走 REST 审核完成该版本；checkpoint 只保存编排路由状态，不是业务真值，不回填历史。

**明确禁止**：不要写任何"自动推进线程 / 机器补一次人工动作"的代码。红线是"概率或程序不得替人做业务决定"，推进线程虽属对账，但没有真实误拦案例前不实现。

## 不进本批次（不要顺手做）

- **真并发测试**：改为断言锁语义（线程 A 在 `evaluate` 前挂住并持 document 锁，线程 B 的 `UPDATE KnowledgeDocument` 必须被挡、A 释放后 B 完成，B 设短 `statement_timeout`），沿用 `test_grounding_fact_attempt_concurrency.py` 的 threads + `Barrier` + `close_old_connections` 范式。放批次 1.2。不要去复现"跨快照误判"——那要注入延迟且必然 flaky。
- **8/8 组合漂移守卫**：已存在，`test_solution_ir_linkage_required.py:134-135`。
- **`processing` 卡住的人工重置入口**：单独立项。已定方向：Admin action（门禁与事实审批一致 `is_staff + role == ADMIN`）、有成功 run → READY / 从未成功 → FAILED、`error_code='indexing_stalled_reset'` 并保留 `indexing_run_id`、且列表与后台必须把"processing 且已超窗"显示成显式可见状态（检索只认 READY，卡住即企业能力池静默缩小）。自动化的正解是租约/心跳抢占，需 schema 变更。
- **`schema_version` 默认 1→2**：61 个测试调用点吃默认值，独立清扫。

## 交付要求

改动文件清单与 file:line、`2929 → N` 的用例数对比（不得减少）、每条新测试的三段式记录（尤其"删掉 `NUM_PROXIES` 配置项"与"把 `RefreshView` 改回 login scope"两处注入必红）、`manage.py check` 与 `makemigrations --check --dry-run` 结果、前端 `vue-tsc --noEmit` 与 `vitest run`（若动 `errors.ts`）、**未做项与原因**、工作树状态与建议提交分组。

最后一条硬要求：如果第 1 类"配置守卫"测试写出来在修复前就是绿的，说明它没测到东西——把它改掉或换成会红的形态，不要交上去。
