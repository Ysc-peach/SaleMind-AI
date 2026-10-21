# SalesMind AI 能力与边界说明（待人工审核）

资料编号：SM-REVIEW-001。

整理日期：2026-10-05。

核对源码版本：`b5edbf3fec7ea548d7f83e5e3103d30407c5adfa`。

用途：为本地销售／售前流程测试提供来源清楚的能力说明草稿。本文不是客户交付案例、产品认证或已批准的 Grounding Fact，尚未入库、索引或审批。

## 1. 产品身份与适用范围

本文所说的产品是当前仓库中的 SalesMind AI：企业售前需求分析与技术方案辅助系统，内含知识检索及基于证据的问答模块。它不是一款已验证可满足所有制造企业知识门户需求的独立成品。

不得将本文的项目能力改写成另一家公司的产品能力。客户提出需求，也不代表 SalesMind AI 已经满足该需求。

## 2. 已有实现证据的能力

以下描述指代码实现范围，不代表生产环境已完成部署、容量验证或商业交付。每项证据均可在当前仓库核对；本次资料整理未重新执行完整测试或真实模型调用。

### 2.1 文档解析

SalesMind AI 的知识文档入口支持 UTF-8 TXT。

SalesMind AI 的知识文档入口支持 Markdown。

SalesMind AI 的知识文档解析模块能够从可提取文字的 PDF 中提取文本。

PDF 文本解析保留来源页码。Markdown 解析保留章节来源信息。

证据：[格式校验](../../apps/knowledge/parsers/validation.py)、[PDF 解析](../../apps/knowledge/parsers/pdf.py)、[Markdown 解析](../../apps/knowledge/parsers/markdown.py)。已有离线测试：[文件格式](../../apps/knowledge/tests/test_file_validation.py)、[PDF](../../apps/knowledge/tests/test_pdf_parser.py)、[Markdown](../../apps/knowledge/tests/test_markdown_parser.py)。

### 2.2 企业知识检索

SalesMind AI 实现了知识文档分块流程。

SalesMind AI 实现了通过配置的 embedding 服务建立文档向量索引的流程。

SalesMind AI 使用 PostgreSQL 的 pgvector 能力执行向量相似度检索。

检索仅使用已就绪且与当前 embedding provider、model、dimension 匹配的文档。

检索结果包含来源文档与分块定位信息。

证据：[分块](../../apps/knowledge/services/chunking.py)、[索引](../../apps/knowledge/services/indexing.py)、[检索](../../apps/knowledge/services/search.py)。已有离线测试：[初始索引](../../apps/knowledge/tests/test_initial_indexing.py)、[检索](../../apps/knowledge/tests/test_search.py)。

### 2.3 基于检索证据的问答

SalesMind AI 的 RAG 问答模块将检索到的来源片段提供给生成模型。

该模块要求回答使用本次检索的来源标签。

没有检索来源时，该模块返回证据不足提示，而不是调用生成模型补造答案。

这些约束不等于模型答案已被证明完全正确；问答引用也不等于企业能力事实已获得批准。

证据：[问答服务](../../apps/rag/services/answering.py)、[引用处理](../../apps/llm/citations.py)。已有离线测试：[问答](../../apps/rag/tests/test_answering.py)。

### 2.4 身份认证与审核

SalesMind AI 实现了 JWT 登录认证。

SalesMind AI 区分 admin、sales、presales 业务角色。

企业事实提议须由具备相应权限的人批准或拒绝；模型不批准自己抽取的事实。

生成的技术方案仍需正式售前审核，自动生成成功不代表客户认可或正式交付批准。

证据：[认证入口](../../apps/accounts/api/urls.py)、[知识库权限](../../apps/knowledge/api/permissions.py)、[事实审批](../../apps/knowledge/services/grounding_fact_approval.py)、[方案审核](../../apps/sales/services/solution_review.py)。

## 3. 不能从上述能力推出的承诺

- 当前文档 parser 不支持直接解析 Word/DOCX。Word 资料需要另行转换为受支持格式，不能宣称已有原生 Word 接入。
- 当前 PDF parser 没有 OCR 流程。扫描版 PDF 不能仅凭“支持 PDF”被认定为可检索。
- 当前 JWT 登录实现不能证明已经完成客户 SSO、OIDC、SAML 或 LDAP 对接。
- 业务角色和商机可见性控制不能证明已经实现客户要求的按部门／文档级权限过滤。当前知识检索入口的角色权限不是文档 ACL 证明。
- 没有依据承诺支持某个并发人数、查询延迟、QPS、SLA、服务器规格或交付期限。
- 没有依据声称已在某客户现场交付、已通过生产验收或具备某行业实施经验。
- 本地运行不等于所有数据不出公网。embedding、generation、verifier 会使用配置的服务端点；若端点是外部服务，相关输入可能离开本机／客户内网。

参考：[已知限制](../known-limitations.md)、[本地配置](../local-configuration.md)、[知识检索](../../apps/knowledge/services/search.py)、[embedding 调用](../../apps/knowledge/embeddings/openai_compatible.py)、[方案 grounding/verifier](../../apps/sales/services/solution_grounding.py)。

## 4. 对当前制造业测试需求的影响

当前测试客户要求资料与问题不发送到公网。本文不能作为该要求已满足的证据。

当前测试客户首批资料包含 Word。本文不能作为 Word 已获原生支持的证据。

当前测试客户要求部门与文档访问隔离。本文不能作为文档级权限能力已实现的证据。

客户的统一身份协议、服务器资源、预算和上线时间未确认时，必须继续保留信息缺口。

因此，本资料包适合核验系统能否区分已有能力、技术建议和能力缺口；不能用它保证该客户方案通过全部准入检查。不得为了通过演示修改客户真实约束。

## 5. 人工审核清单

- 确认“我方产品”确实指 SalesMind AI，而不是未提供资料的另一款产品。
- 逐项核对源码证据及必要的功能测试，判断能力描述是否准确。
- 判断哪些条目适合现有受控企业事实主题；资料中的条目编号不等于系统 fact ID。
- 对未证明的能力保留未确认或不支持状态，不改成支持。
- 不将本文“待审核”的标记当作系统审批状态；实际入库后的事实审批必须单独执行。
- 在批准任何“内网驻留”“文档权限”“SSO”“Word 支持”事实前，要求相应的真实实施和验证证据。

审核结束前，请勿将本文整份视为已批准产品白皮书。
