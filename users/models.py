from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email_user_id, email, password, **extra_fields):
        if not email_user_id:
            raise ValueError("The email_user_id must be set")
        user = self.model(
            email_user_id=email_user_id,
            email=self.normalize_email(email),
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email_user_id, email="", password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email_user_id, email, password, **extra_fields)

    def create_superuser(self, email_user_id, email="", password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email_user_id, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Staff SSO user.

    The field names match what `authbroker_client.backends.AuthbrokerBackend` writes:
    it looks users up by `USERNAME_FIELD` using the profile's `email_user_id`, and sets
    `email`, `first_name` and `last_name` on creation.
    """

    email_user_id = models.CharField(max_length=255, primary_key=True)
    email = models.EmailField(blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email_user_id"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email"]

    def __str__(self):
        return self.email or self.email_user_id

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name
