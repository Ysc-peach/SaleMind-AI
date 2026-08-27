"""Django Admin permission and custom-user behavior tests."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import UserRole


pytestmark = pytest.mark.django_db


def test_django_admin_login_page_uses_simplified_chinese(client):
    response = client.get(reverse("admin:login"))

    assert response.status_code == 200
    assert "登录" in response.content.decode()


def test_custom_user_admin_uses_chinese_labels_with_english_role_values(
    client,
    user_data,
):
    admin_user = get_user_model().objects.create_superuser(**user_data)
    managed_user = get_user_model().objects.create_user(
        username="bob",
        email="bob@example.com",
        role=UserRole.PRESALES,
        password="AnotherStrongPassword123!",
    )
    client.force_login(admin_user)

    add_response = client.get(reverse("admin:accounts_user_add"))
    change_response = client.get(
        reverse("admin:accounts_user_change", args=[managed_user.pk])
    )

    assert add_response.status_code == 200
    assert change_response.status_code == 200

    add_content = add_response.content.decode()
    change_content = change_response.content.decode()
    assert "个人信息" in add_content
    assert "业务角色" in change_content
    assert "邮箱地址" in add_content
    assert '<option value="admin">管理员</option>' in add_content
    assert '<option value="sales">销售</option>' in add_content
    assert '<option value="presales">售前</option>' in add_content


def test_business_admin_without_staff_cannot_access_django_admin(client, user_data):
    user_data["role"] = UserRole.ADMIN
    user = get_user_model().objects.create_user(**user_data)
    client.force_login(user)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))


@pytest.mark.parametrize("role", [UserRole.SALES, UserRole.PRESALES])
def test_non_admin_business_roles_do_not_set_django_privilege_flags(user_data, role):
    user_data["role"] = role

    user = get_user_model().objects.create_user(**user_data)

    assert user.is_staff is False
    assert user.is_superuser is False


def test_technical_superuser_can_open_custom_user_changelist(client, user_data):
    user_data["role"] = UserRole.SALES
    user = get_user_model().objects.create_superuser(**user_data)
    client.force_login(user)

    response = client.get(reverse("admin:accounts_user_changelist"))

    assert response.status_code == 200
    assert user.username.encode() in response.content


def test_custom_user_admin_add_form_creates_user_with_hashed_password(client, user_data):
    admin_user = get_user_model().objects.create_superuser(**user_data)
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:accounts_user_add"),
        {
            "username": "bob",
            "email": "bob@example.com",
            "role": UserRole.PRESALES,
            "first_name": "Bob",
            "last_name": "Builder",
            "password1": "AnotherStrongPassword123!",
            "password2": "AnotherStrongPassword123!",
        },
    )

    assert response.status_code == 302
    created_user = get_user_model().objects.get(username="bob")
    assert created_user.role == UserRole.PRESALES
    assert created_user.check_password("AnotherStrongPassword123!")


def test_custom_user_admin_change_form_exposes_role(client, user_data):
    admin_user = get_user_model().objects.create_superuser(**user_data)
    managed_user = get_user_model().objects.create_user(
        username="bob",
        email="bob@example.com",
        role=UserRole.PRESALES,
        password="AnotherStrongPassword123!",
    )
    client.force_login(admin_user)

    response = client.get(reverse("admin:accounts_user_change", args=[managed_user.pk]))

    assert response.status_code == 200
    assert b'name="role"' in response.content
