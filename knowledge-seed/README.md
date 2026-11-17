# 评测语料（本地，不入库）

这个目录存放用来验证「上传 → 索引 → 事实抽取 → 人工审批 → 生成」全链路的**真实公开文档**。
文档正文不提交到仓库：它们是第三方出版物，版权归发布方所有；仓库里只保留每个子目录的
`sources.json`（URL、标题、字符数、sha256、抓取日期），凭它可以原样重建同一份语料。

## 目录

| 目录 | 内容 | 结果 |
|---|---|---|
| `fastgpt-zh/` | FastGPT 文档 8 篇（部署运维、环境变量、RAG 架构、文档导入切分、MinerU PDF 解析、身份代理、OpenAPI、双引擎检索） | 索引 143 chunk，抽出 **31** 条候选，批准 24 条 |
| `odoo-zh/` | Odoo 17 中文文档 7 篇（部署、导出导入、LDAP、文档/OCR、External API、Sign、定价） | 索引 98 chunk，抽出 **8** 条候选事实 |
| `tidb-zh/` | TiDB 中文文档 10 篇（概览、架构、存储、拓扑、TiFlash、TiProxy、兼容性、限制、备份、部署） | 索引 48 chunk，抽出 **2** 条候选事实 |

三个目录都保留，因为换语料的原因本身是结论的一部分（见下）。

## FastGPT 语料：公司资料应有什么形状

这套语料是按「一家公司应当具备的资料」组织的，而不是按厂商目录抓：

| 公司资料类型 | 对应文档 | 支撑的受控主题 |
|---|---|---|
| 产品能力说明 | RAG 架构、双引擎检索 | 企业知识检索 |
| 部署形态与要求 | 部署运维、环境变量 | 私有化部署、Kubernetes 部署、服务器兼容性、PostgreSQL、pgvector |
| 集成方式 | 身份代理、OpenAPI | SSO 集成、JWT 认证、OA 集成 |
| 文档处理能力 | 文档导入切分、MinerU PDF 解析 | 扫描型 PDF OCR、CSV 批量导出 |
| 边界与限制 | 环境变量（容量/开关）、导入说明 | 各项的量化边界 |

批准 24 条、驳回 7 条。驳回的都不是「写得不好」，而是**不能当能力用**：
「Oracle 不在支持列表内」「未记载数据驻留保证」「没有合同生成的信息」这类缺席推断，
以及把「导入 .csv」错标成导出能力的那条。

## 五次生成尝试（同一需求思路，逐步补语料与需求）

| 尝试 | 语料/需求状态 | 结果 | 卡在哪 |
|---|---|---|---|
| 1 | 8 篇 / 24 条事实，需求 7 维度 known | `solution_draft_not_grounded` | 语义审查 `INADMISSIBLE`：某条能力陈述只引 1 条事实却不被该事实支持 |
| 2 | 同上，需求收敛 | `solution_draft_not_grounded` | 确定性守卫 `unresolved_as_confirmed`：把 unclear 的「现有环境/集成范围」写成确定事实 |
| 3 | 同上，需求 9/10 known | `solution_draft_not_grounded` | 语义审查 `COMPOUND`：架构概览一条塞了多个可独立判断的判断（`decision` 已 `ADMISSIBLE`） |
| 4 | **14 篇** / 41 条事实 | `solution_draft_insufficient_approved_evidence` | 检中的 8 个 chunk **全部没有已批准事实**，准入放不出任何来源标签 |
| 5 | 14 篇 / **53 条事实** | **`succeeded`** | 草稿 7：schema v2、9 章节齐全、67 条 claim（55 条带引用）、3 个架构组件、55 条 provenance |

### 第 4 次暴露的结构性问题（值得单独记）

事实是**按 chunk 挂载**的（`EnterpriseGroundingFact.source_chunk_id`），而检索是每意图 `top_k=3` 的纯语义相似度。
两者错位时会出现极端情况：库里 53 条已批准事实，但检中的 8 个 chunk 里只有 1 个带事实，
于是准入只放行一个来源标签（`('S6',)`），草稿虽然合规却薄——55 条引用全部指向同一个来源。

也就是说：**加文档不一定让证据变厚**，只有当"带事实的那个 chunk"恰好被检索命中时才有用。
可能的改法（都属产品决策，未实施）：
1. 提高每意图 `top_k`，或对"带已批准事实的 chunk"加权；
2. 事实挂到更细的粒度（句子/段落）并允许多 chunk 共享；
3. 准入失败时回退到"带事实的 chunk 集合"，而不是直接硬失败。

## 关键结论：语料必须匹配受控主题，且必须是陈述句

事实抽取只接受 `apps/knowledge/services/grounding_facts.py` 里
`GROUNDING_SUBJECT_REGISTRY` 声明的 15 个受控主题：
企业知识检索、服务器兼容性、私有化部署、内网数据驻留、公网数据传输、PostgreSQL、
pgvector、OA 集成、SSO 集成、Kubernetes 部署、Oracle 兼容性、合同生成、CSV 批量导出、
扫描型 PDF OCR、JWT 认证。

这带来两个硬约束：

1. **主题不匹配就抽不出东西。** TiDB 是分布式数据库，它的架构与部署讲得很好，但几乎不涉及
   上表任何一个主题，所以 10 篇只出 2 条（都在 TiFlash 的「兼容 TiDB」上）。
2. **只有陈述句才成为事实。** Odoo 的「系统配置」页在讲要求（"应为 PostgreSQL 创建非超级用户"、
   "必须使用 HTTPS"），出了 8 条；而「导出和导入数据」「LDAP 认证」「External API」都是操作步骤
   （"点击设置 → 启用 LDAP"），即使主题对得上，也一条都抽不出来。

因此：**厂商 how-to 文档不是好的知识库原料**。真正能入库的是产品能力清单、架构说明、部署要求、
集成方式、案例结论这类陈述式材料——也就是说，需要企业自己的那份资料。

## 重建

```powershell
python scripts/fetch_doc_corpus.py --out knowledge-seed/odoo-zh <url1> <url2> ...
```

URL 见各子目录的 `sources.json`。抓取后按 Admin 同一 Serializer 上传、真实 embedding 索引，
再走人工事实审批。
