"""The case library: who may write it, and how matching ranks."""

import pytest

from apps.accounts.models import UserRole
from apps.sales.models import CaseStudy

pytestmark = pytest.mark.django_db

CASES_URL = "/api/case-studies/"
MATCH_URL = "/api/case-studies/match/"

BODY = {
    "title": "制造业知识库落地",
    "industry": "manufacturing",
    "size_band": "medium",
    "customer_name": "某某集团",
    "pain_points": "文档散落在共享盘",
    "approach": "私有化部署 + 分阶段迁移",
    "results": "检索命中率显著提升",
    "referenceable": True,
}


def test_presales_can_add_a_case(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    api_client.force_authenticate(user=presales)

    response = api_client.post(CASES_URL, BODY, format="json")

    assert response.status_code == 201
    assert response.data["title"] == BODY["title"]
    assert response.data["is_active"] is True
    assert CaseStudy.objects.count() == 1


def test_a_seller_may_read_but_not_write(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    seller = user_factory(UserRole.SALES)
    api_client.force_authenticate(user=presales)
    api_client.post(CASES_URL, BODY, format="json")

    api_client.force_authenticate(user=seller)
    listing = api_client.get(CASES_URL)
    created = api_client.post(CASES_URL, BODY, format="json")

    assert listing.status_code == 200
    assert listing.data["count"] == 1
    # A library sellers can edit fills with claims nobody can defend.
    assert created.status_code == 403
    assert CaseStudy.objects.count() == 1


def test_a_case_without_an_industry_is_refused(api_client, user_factory):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))

    body = dict(BODY)
    body.pop("industry")
    response = api_client.post(CASES_URL, body, format="json")

    assert response.status_code == 400


def test_an_unknown_size_band_is_refused_on_write_and_read(
    api_client, user_factory
):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))

    bad_body = dict(BODY, size_band="gigantic")
    assert api_client.post(CASES_URL, bad_body, format="json").status_code == 400
    assert (
        api_client.get(CASES_URL, {"size_band": "gigantic"}).status_code == 400
    )


def test_the_list_filters_by_industry_and_referenceability(
    api_client, user_factory
):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))
    api_client.post(CASES_URL, BODY, format="json")
    api_client.post(
        CASES_URL,
        dict(
            BODY,
            title="金融案例",
            industry="finance",
            referenceable=False,
        ),
        format="json",
    )

    by_industry = api_client.get(CASES_URL, {"industry": "finance"}).data
    referenceable = api_client.get(CASES_URL, {"referenceable": "true"}).data
    both = api_client.get(
        CASES_URL, {"industry": "manufacturing", "referenceable": "false"}
    ).data

    assert [row["title"] for row in by_industry["results"]] == ["金融案例"]
    assert [row["title"] for row in referenceable["results"]] == [
        BODY["title"]
    ]
    assert both["count"] == 0


def test_an_archived_case_leaves_the_default_list_and_can_come_back(
    api_client, user_factory
):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))
    case_id = api_client.post(CASES_URL, BODY, format="json").data["id"]

    assert api_client.post(f"{CASES_URL}{case_id}/archive/").status_code == 200
    assert api_client.get(CASES_URL).data["count"] == 0
    assert api_client.post(f"{CASES_URL}{case_id}/restore/").status_code == 200
    assert api_client.get(CASES_URL).data["count"] == 1


def test_only_an_admin_sees_archived_cases(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    api_client.force_authenticate(user=presales)
    case_id = api_client.post(CASES_URL, BODY, format="json").data["id"]
    api_client.post(f"{CASES_URL}{case_id}/archive/")

    refused = api_client.get(CASES_URL, {"include_inactive": "1"})

    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))
    allowed = api_client.get(CASES_URL, {"include_inactive": "1"})

    assert refused.status_code == 403
    assert allowed.data["count"] == 1


def test_matching_prefers_the_same_industry_then_the_same_size(
    api_client, user_factory
):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))
    api_client.post(
        CASES_URL,
        dict(BODY, title="别的行业同规模", industry="finance", referenceable=False),
        format="json",
    )
    api_client.post(
        CASES_URL,
        dict(BODY, title="同行业别的规模", size_band="large", referenceable=False),
        format="json",
    )
    api_client.post(CASES_URL, BODY, format="json")

    ranked = api_client.get(
        MATCH_URL, {"industry": "manufacturing", "size_band": "medium"}
    ).data["results"]

    # The exact match wins; the two near misses are still offered, because a
    # strict filter would leave the section empty.
    assert ranked[0]["title"] == BODY["title"]
    assert {row["title"] for row in ranked} == {
        BODY["title"], "别的行业同规模", "同行业别的规模",
    }


def test_matching_never_returns_an_archived_case(api_client, user_factory):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))
    case_id = api_client.post(CASES_URL, BODY, format="json").data["id"]
    api_client.post(f"{CASES_URL}{case_id}/archive/")

    assert api_client.get(MATCH_URL, {"industry": "manufacturing"}).data[
        "results"
    ] == []


def test_the_match_limit_is_validated(api_client, user_factory):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))

    assert api_client.get(MATCH_URL, {"limit": "0"}).status_code == 400
    assert api_client.get(MATCH_URL, {"limit": "21"}).status_code == 400
    assert api_client.get(MATCH_URL, {"limit": "abc"}).status_code == 400


def test_updating_flips_the_reference_flag(api_client, user_factory):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))
    case_id = api_client.post(CASES_URL, BODY, format="json").data["id"]

    response = api_client.patch(
        f"{CASES_URL}{case_id}/", {"referenceable": False}, format="json"
    )

    assert response.status_code == 200
    assert response.data["referenceable"] is False
    assert CaseStudy.objects.get(pk=case_id).referenceable is False


def test_an_update_with_a_bad_size_band_is_refused(api_client, user_factory):
    api_client.force_authenticate(user=user_factory(UserRole.PRESALES))
    case_id = api_client.post(CASES_URL, BODY, format="json").data["id"]

    response = api_client.patch(
        f"{CASES_URL}{case_id}/", {"size_band": "gigantic"}, format="json"
    )

    assert response.status_code == 400
    assert CaseStudy.objects.get(pk=case_id).size_band == "medium"
