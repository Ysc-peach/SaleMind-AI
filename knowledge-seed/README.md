# 评测语料（本地，不入库）

这个目录存放用来验证「上传 → 索引 → 事实抽取 → 人工审批 → 生成」全链路的**真实公开文档**。
文档正文不提交到仓库：它们是第三方出版物，版权归发布方所有；仓库里只保留每个子目录的
`sources.json`（URL、标题、字符数、sha256、抓取日期），凭它可以原样重建同一份语料。

## 目录

| 目录 | 内容 | 结果 |
|---|---|---|
| `odoo-zh/` | Odoo 17 中文文档 7 篇（部署、导出导入、LDAP、文档/OCR、External API、Sign、定价） | 索引 98 chunk，抽出 **8** 条候选事实 |
| `tidb-zh/` | TiDB 中文文档 10 篇（概览、架构、存储、拓扑、TiFlash、TiProxy、兼容性、限制、备份、部署） | 索引 48 chunk，抽出 **2** 条候选事实 |

两个目录都保留，因为换语料的原因本身是结论的一部分（见下）。

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
