# 已审核方案导出

在方案详情页“刷新”旁选择“导出 Word”或“导出 PDF”。只读已有获批版本，不重新生成、不消耗模型额度，也不提交或改变技术审核。Word 编辑后的内容不自动继承系统审核。

## 下载条件

用户当前活跃，业务 role 为 Sales、Presales 或 Admin，并有该确切版本的查看权限。独立版本审核人不会因导出得到整个商机的权限。staff/superuser 不授予业务权限。

方案投影必须 approved，最新审核尝试必须是已完成的 approved。方案不得已存或实时判定 stale，当前原始需求必须与分析原文快照按 strip 后一致。引用与持久化来源必须完整，事实审批、当前索引和分块内容仍有效。有效的旧版本可按用户选择导出，不只允许最大方案版本号。

文件生成后再次从数据库读取权限、审批、需求和来源，比对一致性指纹；中途变化拒绝返回附件。文件只证明最终检查时点的有效性，不能追回已下载的文件。

## 文件内容与限制

Word 和 PDF 共用 V1/V2 内容投影，保留保存的正文、分类、结构关系、声明标识、引用、版本和必要的批准元数据。默认不包含原始需求全文、来源 excerpt、内部审核备注/退回历史、异常诊断和密钥。

PDF 为 A4、内嵌静态 Noto Sans SC，Word 为 A4，设置中文字体但允许查看器替代。不依赖生产机安装 Office 或 LibreOffice。两种格式页数可以不同；内容不因篇幅被截断。文件上限 10 MiB，超过整体拒绝。无公开文件存储或匿名分享。

`GET /api/solution-drafts/{id}/export/?file_type=docx|pdf` 使用 JWT；不可见版本 404。二进制响应为 attachment，private/no-store，nosniff；安全 JSON 错误不当成文档下载。

| 错误 | 处理 |
| --- | --- |
| not_approved | 完成当前版本技术审核后再下载 |
| stale / requirement_changed / changed | 刷新并核对当前版本、需求和依据；不自动生成或循环下载 |
| invalid_payload | 联系维护人员检查正文及引用记录，不让使用者猜测补条件 |
| too_large | 联系维护人员处理大小，不截断正文 |
| unavailable | 检查文档依赖、字体及渲染服务，不重复调用模型 |

以上错误 code 前缀均为 `solution_export_`；HTTP 分别为409、422和503，非法格式400；认证和业务权限继续使用401/403。

## 部署

安装 `requirements/base.txt` 中锁定的 python-docx 1.2.0 / ReportLab 5.0.1；部署必须携带 `apps/sales/assets/fonts/NotoSansSC-Regular.ttf`、`manifest.json`、`OFL.txt`。PDF 请求验证静态字体 hash；缺字体或缺字拒绝下载，不偷偷切换系统字体。

字体源来自 Google Fonts 固定修订，源 hash 和静态 hash 记录在 manifest。`scripts/prepare_solution_export_font.py` 是一次性资产准备工具（fonttools 4.60.1），不会在请求中执行，拒绝覆盖已有资产。OFL 许可随文件分发。

## 验收记录

功能、下载和回归结果以当前实施 ledger 为准。DOCX/PDF 必须分别做结构/内容校验和逐页视觉检查；读取 XML 或 PDF header 不能替代排版检查。尚未具备 Word 渲染工具时，明确记录 Word 视觉验收未完成，不能声称所有验收完成。

V1 导出使用文档 ID，不额外读取到下载正文的当前文档标题；V2 保留版本接口原有标题口径。引用检查证明保存的每个陈述/引用 pair 都有对应行，并复核所有现存事实绑定；若管理员绕过不可变模型，在请求前删除同一 pair 中的一部分历史事实绑定，当前没有原始 fact-ID 清单可供重建，不能宣称能证明这种异常改库后的历史清单完整。渲染期间删除仍会因最终 gate/指纹差异而拒绝。
