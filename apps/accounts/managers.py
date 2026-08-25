"""Managers for the accounts application."""

from django.contrib.auth.models import UserManager as DjangoUserManager


class UserManager(DjangoUserManager):
    """Create users while requiring their identity and business role."""

    use_in_migrations = True

    def _create_user_object(self, username, email, password, **extra_fields):
        if not email or not str(email).strip():
            raise ValueError("The email must be set")
        role = extra_fields.get("role")
        if not role or not str(role).strip():
            raise ValueError("The role must be set")

        return super()._create_user_object(
            username,
            str(email).strip(),
            password,
            **extra_fields,
        )

    def create_user(self, username, email, role, password=None, **extra_fields):
        return super().create_user(
            username,
            email,
            password,
            role=role,
            **extra_fields,
        )

    create_user.alters_data = True

    async def acreate_user(self, username, email, role, password=None, **extra_fields):
        return await super().acreate_user(
            username,
            email,
            password,
            role=role,
            **extra_fields,
        )

    acreate_user.alters_data = True

    def create_superuser(self, username, email, role, password=None, **extra_fields):
        return super().create_superuser(
            username,
            email,
            password,
            role=role,
            **extra_fields,
        )

    create_superuser.alters_data = True

    async def acreate_superuser(
        self,
        username,
        email,
        role,
        password=None,
        **extra_fields,
    ):
        return await super().acreate_superuser(
            username,
            email,
            password,
            role=role,
            **extra_fields,
        )

    acreate_superuser.alters_data = True
