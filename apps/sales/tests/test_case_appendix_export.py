"""The related-cases page is data from the library, not text from the model."""

import io
import zipfile

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import CaseStudy
from apps.sales.services.case_appendix import TITLE, build_case_section
from apps.sales.tests.export_fixtures import make_export_case

pytestmark = pytest.mark.django_db(transaction=True)

PASSWORD = "StrongPassword123!"


def _author(username="case-owner"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        role=UserRole.PRESALES,
        password=PASSWORD,
    )


def _case(owner, **overrides):
    payload = {
        "title": "制造业知识库一期",
        "industry": "manufacturing",
        "size_band": "medium",
        "customer_name": "某制造集团",
        "pain_points": "文档散落在共享盘",
        "approach": "分两期迁移并做权限梳理",
        "results": "检索命中率提升",
        "referenceable": False,
        "created_by": owner,
    }
    payload.update(overrides)
    return CaseStudy.objects.create(**payload)


def _document_xml(response) -> str:
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_nothing_is_rendered_without_cases():
    assert build_case_section([]) == ()


def test_a_non_referenceable_case_is_anonymous_even_with_a_name_stored():
    text = build_case_section([_case(_author())])[0].blocks[1].text

    # The flag decides, not whether a name happens to be filled in.
    assert "匿名客户" in text
    assert "某制造集团" not in text


def test_a_referenceable_case_may_be_named():
    text = build_case_section([_case(_author("author-b"), referenceable=True)])[
        0
    ].blocks[1].text

    assert "某制造集团" in text
    assert "匿名客户" not in text


def test_the_page_stops_at_three_cases():
    author = _author("author-c")
    cases = [_case(author, title=f"案例 {n}") for n in range(5)]

    section = build_case_section(cases)[0]
    paragraphs = [block for block in section.blocks if block.kind == "paragraph"]

    assert section.title == TITLE
    # One preamble plus at most three cases.
    assert len(paragraphs) == 4


def test_exporting_with_cases_attaches_the_page(make_export_case):
    case = make_export_case()
    opportunity = case.solution.opportunity
    opportunity.customer.industry = "manufacturing"
    opportunity.customer.save(update_fields=["industry"])
    _case(case.owner)

    client = APIClient()
    client.force_authenticate(case.owner)
    response = client.get(
        f"/api/solution-drafts/{case.solution.pk}/export/?file_type=docx&cases=1"
    )

    assert response.status_code == 200
    xml = _document_xml(response)
    assert TITLE in xml
    assert "制造业知识库一期" in xml


def test_exporting_without_the_flag_leaves_it_out(make_export_case):
    case = make_export_case()
    opportunity = case.solution.opportunity
    opportunity.customer.industry = "manufacturing"
    opportunity.customer.save(update_fields=["industry"])
    _case(case.owner)

    client = APIClient()
    client.force_authenticate(case.owner)
    response = client.get(
        f"/api/solution-drafts/{case.solution.pk}/export/?file_type=docx"
    )

    assert TITLE not in _document_xml(response)


def test_a_customer_without_an_industry_gets_no_page(make_export_case):
    case = make_export_case()
    _case(case.owner)

    client = APIClient()
    client.force_authenticate(case.owner)
    response = client.get(
        f"/api/solution-drafts/{case.solution.pk}/export/?file_type=docx&cases=1"
    )

    assert response.status_code == 200
    # A generic list would read like a match that was never made.
    assert TITLE not in _document_xml(response)
