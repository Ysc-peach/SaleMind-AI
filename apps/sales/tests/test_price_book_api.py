"""The price book answers "what does this cost today", and nothing else."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import PriceBookEntry
from apps.sales.services import price_book

pytestmark = pytest.mark.django_db

PRICE_BOOK_URL = "/api/price-book/"


def _entry(owner, *, sku="SKU-1", name="标准版", price="1200.00", effective_from=None, active=True):
    return PriceBookEntry.objects.create(
        sku=sku,
        name=name,
        category="软件",
        unit="套",
        unit_price=Decimal(price),
        effective_from=effective_from or timezone.localdate(),
        is_active=active,
        created_by=owner,
    )


def _skus(payload):
    return [row["sku"] for row in payload["results"]]


def test_the_newest_started_row_wins(api_client, user_factory):
    seller = user_factory(UserRole.SALES)
    today = timezone.localdate()
    _entry(seller, price="1000.00", effective_from=today - timedelta(days=90))
    _entry(seller, price="1200.00", effective_from=today - timedelta(days=1))
    api_client.force_authenticate(user=seller)

    response = api_client.get(PRICE_BOOK_URL)

    assert response.status_code == 200
    assert response.data["count"] == 1
    row = response.data["results"][0]
    # Money stays a string so a float never rounds it on the way out.
    assert row["unit_price"] == "1200.00"


def test_a_future_price_does_not_apply_yet(api_client, user_factory):
    seller = user_factory(UserRole.SALES)
    today = timezone.localdate()
    _entry(seller, price="1000.00", effective_from=today)
    _entry(seller, price="1500.00", effective_from=today + timedelta(days=30))
    api_client.force_authenticate(user=seller)

    now = api_client.get(PRICE_BOOK_URL).data
    later = api_client.get(
        PRICE_BOOK_URL, {"as_of": (today + timedelta(days=60)).isoformat()}
    ).data

    assert now["results"][0]["unit_price"] == "1000.00"
    assert later["results"][0]["unit_price"] == "1500.00"


def test_a_retired_sku_leaves_the_default_list(api_client, user_factory):
    seller = user_factory(UserRole.SALES)
    _entry(seller, sku="SKU-OLD", active=False)
    _entry(seller, sku="SKU-NEW")
    api_client.force_authenticate(user=seller)

    assert _skus(api_client.get(PRICE_BOOK_URL).data) == ["SKU-NEW"]


def test_only_an_admin_can_list_retired_rows(api_client, user_factory):
    seller = user_factory(UserRole.SALES)
    _entry(seller, sku="SKU-OLD", active=False)
    api_client.force_authenticate(user=seller)

    refused = api_client.get(PRICE_BOOK_URL, {"include_inactive": "1"})

    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))
    allowed = api_client.get(PRICE_BOOK_URL, {"include_inactive": "1"})

    assert refused.status_code == 403
    assert _skus(allowed.data) == ["SKU-OLD"]


def test_the_list_filters_by_sku_and_text(api_client, user_factory):
    seller = user_factory(UserRole.SALES)
    _entry(seller, sku="SKU-A", name="标准版")
    _entry(seller, sku="SKU-B", name="企业版")
    api_client.force_authenticate(user=seller)

    by_sku = api_client.get(PRICE_BOOK_URL, {"sku": "sku-a"}).data
    by_text = api_client.get(PRICE_BOOK_URL, {"q": "企业"}).data

    assert _skus(by_sku) == ["SKU-A"]
    assert _skus(by_text) == ["SKU-B"]


def test_a_malformed_date_is_refused(api_client, user_factory):
    api_client.force_authenticate(user=user_factory(UserRole.SALES))

    assert api_client.get(PRICE_BOOK_URL, {"as_of": "2026/01/01"}).status_code == 400


def test_the_book_is_read_only_over_http(api_client, user_factory):
    admin = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        PRICE_BOOK_URL, {"sku": "SKU-1", "name": "x", "unit_price": "1"}, format="json"
    )

    # Prices are edited in the admin, where the edit itself is recorded.
    assert response.status_code == 405


def test_anonymous_access_is_refused(api_client):
    assert api_client.get(PRICE_BOOK_URL).status_code == 401


def test_the_same_sku_cannot_start_twice_on_one_day(user_factory):
    seller = user_factory(UserRole.SALES)
    today = timezone.localdate()
    _entry(seller, effective_from=today)

    with pytest.raises(IntegrityError), transaction.atomic():
        _entry(seller, effective_from=today, price="1300.00")


def test_a_negative_price_is_impossible(user_factory):
    seller = user_factory(UserRole.SALES)

    with pytest.raises(IntegrityError), transaction.atomic():
        _entry(seller, price="-1.00")


def test_current_price_answers_the_same_question_as_the_list(user_factory):
    seller = user_factory(UserRole.SALES)
    today = timezone.localdate()
    _entry(seller, price="1000.00", effective_from=today - timedelta(days=10))
    _entry(seller, price="1200.00", effective_from=today)

    entry = price_book.current_price("SKU-1")

    assert entry is not None
    assert entry.unit_price == Decimal("1200.00")
