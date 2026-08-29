"""Persistence models for the enterprise knowledge base."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from pgvector.django import VectorField


class KnowledgeDocumentType(models.TextChoices):
    PRODUCT = "product", _("产品资料")
    TECHNICAL = "technical", _("技术文档")
    CASE = "case", _("历史案例")
    FAQ = "faq", _("常见问题")
    SALES = "sales", _("销售资料")


class KnowledgeDocumentStatus(models.TextChoices):
    PENDING = "pending", _("待处理")
    PROCESSING = "processing", _("处理中")
    READY = "ready", _("已就绪")
    FAILED = "failed", _("处理失败")


class KnowledgeDocument(models.Model):
    DocumentType = KnowledgeDocumentType
    Status = KnowledgeDocumentStatus

    title = models.CharField(_("文档标题"), max_length=255)
    document_type = models.CharField(
        _("文档类型"),
        max_length=16,
        choices=KnowledgeDocumentType.choices,
    )
    source_file = models.FileField(
        _("源文件"),
        upload_to="knowledge/documents/%Y/%m/%d",
        max_length=500,
    )
    original_filename = models.CharField(_("原始文件名"), max_length=255)
    mime_type = models.CharField(_("MIME 类型"), max_length=100)
    file_size = models.PositiveBigIntegerField(_("文件大小"))
    checksum_sha256 = models.CharField(_("SHA-256 校验值"), max_length=64)
    status = models.CharField(
        _("状态"),
        max_length=16,
        choices=KnowledgeDocumentStatus.choices,
        default=KnowledgeDocumentStatus.PENDING,
    )
    error_code = models.CharField(
        _("错误代码"),
        max_length=64,
        blank=True,
        default="",
    )
    error_message = models.TextField(_("错误信息"), blank=True, default="")
    embedding_provider = models.CharField(
        _("向量提供方"),
        max_length=64,
        blank=True,
        default="",
    )
    embedding_model = models.CharField(
        _("向量模型"),
        max_length=255,
        blank=True,
        default="",
    )
    embedding_dimensions = models.PositiveIntegerField(
        _("向量维度"),
        null=True,
        blank=True,
    )
    chunk_count = models.PositiveIntegerField(_("分块数量"), default=0)
    indexing_run_id = models.UUIDField(_("索引运行 ID"), null=True, blank=True)
    processing_started_at = models.DateTimeField(
        _("处理开始时间"),
        null=True,
        blank=True,
    )
    last_indexed_at = models.DateTimeField(
        _("最后索引时间"),
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_knowledge_documents",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(document_type__in=KnowledgeDocumentType.values),
                name="knowledge_document_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=KnowledgeDocumentStatus.values),
                name="knowledge_document_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(chunk_count__gte=0),
                name="knowledge_document_chunk_count_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        indexing_run_id__isnull=True,
                        processing_started_at__isnull=True,
                    )
                    | models.Q(
                        indexing_run_id__isnull=False,
                        processing_started_at__isnull=False,
                    )
                ),
                name="knowledge_document_indexing_state_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=KnowledgeDocumentStatus.READY)
                    | models.Q(last_indexed_at__isnull=False)
                ),
                name="knowledge_document_ready_has_last_indexed_at",
            ),
        ]
        indexes = [models.Index(fields=["status", "document_type"])]
        verbose_name = _("知识库文档")
        verbose_name_plural = _("知识库文档")

    def __str__(self) -> str:
        return self.title


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
        verbose_name=_("知识库文档"),
    )
    chunk_index = models.PositiveIntegerField(_("分块序号"))
    content = models.TextField(_("内容"))
    embedding = VectorField(_("向量"), dimensions=1024)
    page_number = models.PositiveIntegerField(
        _("页码"),
        null=True,
        blank=True,
    )
    section_title = models.CharField(
        _("章节标题"),
        max_length=255,
        blank=True,
        default="",
    )
    source_reference = models.CharField(
        _("来源引用"),
        max_length=500,
        blank=True,
        default="",
    )
    metadata = models.JSONField(_("元数据"), default=dict, blank=True)
    char_count = models.PositiveIntegerField(_("字符数"))
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_index"],
                name="knowledge_chunk_document_index_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(chunk_index__gte=0),
                name="knowledge_chunk_index_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(page_number__isnull=True)
                    | models.Q(page_number__gte=1)
                ),
                name="knowledge_chunk_page_number_valid",
            ),
        ]
        verbose_name = _("知识库分块")
        verbose_name_plural = _("知识库分块")

    def __str__(self) -> str:
        return f"{self.document}: {self.chunk_index}"
