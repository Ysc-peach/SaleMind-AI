"""Follow-up tasks: who may write them, and what the buckets contain."""

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import FollowUpTask, FollowUpTaskStatus

pytestmark = pytest.mark.django_db

MINE_URL = "/api/follow-ups/mine/"


def _tasks_url(opportunity):
    return f"/api/opportunities/{opportunity.id}/follow-ups/"


def _create(api_client, opportunity, **payload):
    body = {"title": "回访客户", "due_on": timezone.localdate().isoformat()}
    body.update(payload)
    return api_client.post(_tasks_url(opportunity), body, format="json")


def test_the_owner_can_add_a_dated_follow_up(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)

    response = _create(api_client, opportunity, title="  发送 POC 计划  ")

    assert response.status_code == 201
    assert response.data["title"] == "发送 POC 计划"
    assert response.data["owner"] == seller.pk
    assert response.data["status"] == "open"
    listed = api_client.get(_tasks_url(opportunity)).data
    assert listed["count"] == 1
    assert listed["results"][0]["title"] == "发送 POC 计划"


def test_an_archived_opportunity_takes_no_new_follow_up(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller, is_active=False
    )
    api_client.force_authenticate(user=seller)

    response = _create(api_client, opportunity)

    assert response.status_code == 409
    assert response.data["code"] == "record_inactive"
    assert FollowUpTask.objects.count() == 0


def test_a_presales_who_does_not_own_the_opportunity_cannot_even_see_it(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    other_presales = user_factory(UserRole.PRESALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=other_presales)

    assert _create(api_client, opportunity).status_code == 404
    assert api_client.get(_tasks_url(opportunity)).status_code == 404


def test_the_assigned_presales_can_add_one(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    presales = user_factory(UserRole.PRESALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"),
        sales_owner=seller,
        presales_owner=presales,
    )
    api_client.force_authenticate(user=presales)

    assert _create(api_client, opportunity).status_code == 201


def test_completing_records_the_time_and_can_be_repeated(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)
    task_id = _create(api_client, opportunity).data["id"]

    first = api_client.post(f"/api/follow-ups/{task_id}/complete/")
    second = api_client.post(f"/api/follow-ups/{task_id}/complete/")

    assert first.status_code == 200
    assert first.data["status"] == "done"
    assert first.data["completed_at"] is not None
    # A retry after a network failure must not double-complete or error.
    assert second.status_code == 200
    task = FollowUpTask.objects.get(pk=task_id)
    assert task.status == FollowUpTaskStatus.DONE


def test_reopening_clears_the_completion(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)
    task_id = _create(api_client, opportunity).data["id"]
    api_client.post(f"/api/follow-ups/{task_id}/complete/")

    response = api_client.post(f"/api/follow-ups/{task_id}/reopen/")

    assert response.status_code == 200
    assert response.data["status"] == "open"
    assert response.data["completed_at"] is None


def test_a_stranger_cannot_touch_someone_elses_task(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    stranger = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)
    task_id = _create(api_client, opportunity).data["id"]

    api_client.force_authenticate(user=stranger)
    response = api_client.post(f"/api/follow-ups/{task_id}/complete/")

    # 404 rather than 403: an id probe must not confirm the record exists.
    assert response.status_code == 404
    assert FollowUpTask.objects.get(pk=task_id).status == FollowUpTaskStatus.OPEN


def test_the_list_filters_by_state(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)
    done_id = _create(api_client, opportunity, title="已完成的事").data["id"]
    api_client.post(f"/api/follow-ups/{done_id}/complete/")
    _create(api_client, opportunity, title="还要做的事")

    open_only = api_client.get(_tasks_url(opportunity)).data
    done_only = api_client.get(_tasks_url(opportunity), {"status": "done"}).data
    everything = api_client.get(_tasks_url(opportunity), {"status": "all"}).data

    assert [row["title"] for row in open_only["results"]] == ["还要做的事"]
    assert [row["title"] for row in done_only["results"]] == ["已完成的事"]
    assert everything["count"] == 2


def test_an_unknown_state_filter_is_refused(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)

    response = api_client.get(_tasks_url(opportunity), {"status": "late"})

    assert response.status_code == 400


def test_a_blank_title_is_refused(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)

    assert _create(api_client, opportunity, title="   ").status_code == 400


def test_mine_separates_late_from_due_soon(
    api_client, user_factory, customer_factory, opportunity_factory
):
    today = timezone.localdate()
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)
    _create(
        api_client, opportunity, title="迟到的",
        due_on=(today - timedelta(days=2)).isoformat(),
    )
    _create(
        api_client, opportunity, title="本周的",
        due_on=(today + timedelta(days=3)).isoformat(),
    )
    _create(
        api_client, opportunity, title="以后再说",
        due_on=(today + timedelta(days=30)).isoformat(),
    )
    done_id = _create(
        api_client, opportunity, title="已完成",
        due_on=(today - timedelta(days=5)).isoformat(),
    ).data["id"]
    api_client.post(f"/api/follow-ups/{done_id}/complete/")

    payload = api_client.get(MINE_URL).data

    assert [row["title"] for row in payload["overdue"]] == ["迟到的"]
    assert [row["title"] for row in payload["due_soon"]] == ["本周的"]
    assert payload["counts"] == {"overdue": 1, "due_soon": 1}


def test_the_command_reports_overdue_tasks_and_fails_the_check(
    api_client, user_factory, customer_factory, opportunity_factory
):
    today = timezone.localdate()
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)
    _create(
        api_client, opportunity,
        due_on=(today - timedelta(days=4)).isoformat(),
    )

    output = StringIO()
    with pytest.raises(CommandError, match="1 overdue"):
        call_command("list_due_follow_ups", stdout=output)

    report = json.loads(output.getvalue())
    assert report["overdue"] == 1
    assert report["tasks"][0]["days_late"] == 4
    assert report["tasks"][0]["project_name"] == "Platform rollout"


def test_the_command_stays_green_within_the_agreed_limit(
    api_client, user_factory, customer_factory, opportunity_factory
):
    today = timezone.localdate()
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)
    _create(api_client, opportunity, due_on=(today - timedelta(days=1)).isoformat())

    output = StringIO()
    call_command("list_due_follow_ups", stdout=output, max_overdue=2)

    assert json.loads(output.getvalue())["overdue"] == 1
