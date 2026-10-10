import environ
import pytest
from authbroker_client.backends import AuthbrokerBackend
from django.contrib.auth import get_user_model
from django.urls import reverse

from tests.factories import UserFactory
from users.sso import sso_enabled

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def sso_off(settings):
    settings.DISABLE_SSO = True


class TestUserModel:
    def test_primary_key_and_username_field_are_email_user_id(self):
        assert User._meta.pk.name == "email_user_id"
        assert User.USERNAME_FIELD == "email_user_id"

    def test_create_user(self):
        user = User.objects.create_user("jo-1234@id.example.com", email="Jo@EXAMPLE.com")

        assert user.pk == "jo-1234@id.example.com"
        assert user.email == "Jo@example.com"
        assert not user.is_staff
        assert not user.is_superuser
        assert not user.has_usable_password()

    def test_create_user_requires_email_user_id(self):
        with pytest.raises(ValueError):
            User.objects.create_user("")

    def test_create_superuser(self):
        user = User.objects.create_superuser("admin@id.example.com", password="pw")

        assert user.is_staff
        assert user.is_superuser
        assert user.check_password("pw")

    def test_create_superuser_must_be_staff(self):
        with pytest.raises(ValueError):
            User.objects.create_superuser("admin@id.example.com", is_staff=False)

    def test_str_falls_back_to_email_user_id(self):
        assert str(User(email_user_id="a@id.example.com")) == "a@id.example.com"
        assert str(User(email_user_id="a@id.example.com", email="a@example.com")) == "a@example.com"


class TestSsoProfileMapping:
    profile = {
        "email_user_id": "jo.bloggs-1a2b3c4d@id.example.com",
        "email": "jo.bloggs@example.com",
        "first_name": "Jo",
        "last_name": "Bloggs",
        "user_id": "6fa3b542-9a6f-4fc3-a248-168596572999",
    }

    def test_backend_creates_user_from_profile(self):
        user = AuthbrokerBackend().get_or_create_user(self.profile)

        assert user.pk == "jo.bloggs-1a2b3c4d@id.example.com"
        assert user.email == "jo.bloggs@example.com"
        assert user.get_full_name() == "Jo Bloggs"
        assert not user.has_usable_password()
        assert not user.is_staff

    def test_backend_reuses_existing_user(self):
        existing = UserFactory(email_user_id=self.profile["email_user_id"], is_staff=True)

        user = AuthbrokerBackend().get_or_create_user(self.profile)

        assert user.pk == existing.pk
        assert user.is_staff
        assert User.objects.count() == 1


class TestDisableSsoSetting:
    def test_sso_is_enabled_by_default(self):
        assert sso_enabled()

    def test_sso_is_disabled_when_setting_is_on(self, sso_off):
        assert not sso_enabled()

    def test_setting_defaults_to_off_when_the_variable_is_unset(self, monkeypatch):
        monkeypatch.delenv("DISABLE_SSO", raising=False)

        assert environ.Env().bool("DISABLE_SSO", default=False) is False

    @pytest.mark.parametrize("value", ["on", "On", "true", "True", "1", "yes"])
    def test_accepted_ways_of_turning_it_on(self, monkeypatch, value):
        monkeypatch.setenv("DISABLE_SSO", value)

        assert environ.Env().bool("DISABLE_SSO", default=False) is True

    @pytest.mark.parametrize("value", ["off", "false", "False", "0", "no", ""])
    def test_everything_else_leaves_sso_on(self, monkeypatch, value):
        monkeypatch.setenv("DISABLE_SSO", value)

        assert environ.Env().bool("DISABLE_SSO", default=False) is False


class TestLoginView:
    def test_sso_on_redirects_to_authbroker(self, client):
        response = client.get(reverse("login"))

        assert response.status_code == 302
        assert response.url == "/auth/login/"

    def test_sso_on_preserves_next(self, client):
        response = client.get(reverse("login"), {"next": "/orgs/org1/?a=1"})

        assert response.url == "/auth/login/?next=%2Forgs%2Forg1%2F%3Fa%3D1"

    def test_sso_off_redirects_to_admin_login(self, client, sso_off):
        response = client.get(reverse("login"), {"next": "/orgs/org1/"})

        assert response.status_code == 302
        assert response.url == "/admin/login/?next=%2Forgs%2Forg1%2F"

    def test_authbroker_login_redirects_to_sso_provider(self, client, settings):
        response = client.get("/auth/login/", {"next": "/orgs/org1/"})

        assert response.status_code == 302
        assert response.url.startswith(f"{settings.AUTHBROKER_URL}/o/authorize/")
        assert "redirect_uri=http%3A%2F%2Ftestserver%2Fauth%2Fcallback%2F" in response.url

    def test_authbroker_callback_is_exempt_from_login(self, client):
        # No code in the query string: the view itself answers, not the login middleware.
        assert client.get("/auth/callback/").status_code == 400


class TestAdminLogin:
    def test_sso_on_redirects_to_login_url(self, client):
        response = client.get("/admin/login/", {"next": "/admin/users/user/"})

        assert response.status_code == 302
        assert response.url == "/login/?next=/admin/users/user/"

    def test_sso_on_defaults_next_to_admin_index(self, client):
        assert client.get("/admin/login/").url == "/login/?next=/admin/"

    def test_sso_on_does_not_accept_passwords(self, client):
        UserFactory(email_user_id="admin@id.example.com", is_staff=True)

        response = client.post(
            "/admin/login/", {"username": "admin@id.example.com", "password": "password"}
        )

        assert response.url == "/login/?next=/admin/"
        assert "_auth_user_id" not in client.session

    def test_sso_on_signed_in_non_staff_is_forbidden_not_looped(self, client):
        client.force_login(UserFactory())

        assert client.get("/admin/login/").status_code == 403

    def test_sso_on_signed_in_staff_goes_to_admin(self, client):
        client.force_login(UserFactory(is_staff=True))

        response = client.get("/admin/login/", {"next": "https://evil.example/"})

        assert response.url == "/admin/"

    def test_sso_off_renders_admin_login_form(self, client, sso_off):
        response = client.get("/admin/login/")

        assert response.status_code == 200
        assert b'name="password"' in response.content

    def test_sso_off_staff_can_log_in_with_password(self, client, sso_off):
        UserFactory(email_user_id="admin@id.example.com", is_staff=True)

        response = client.post(
            "/admin/login/?next=/admin/",
            {"username": "admin@id.example.com", "password": "password"},
        )

        assert response.status_code == 302
        assert response.url == "/admin/"
        assert client.session["_auth_user_id"] == "admin@id.example.com"


class TestLoginRequired:
    @pytest.mark.urls("tests.urls")
    def test_anonymous_user_is_redirected_to_login(self, client):
        response = client.get("/protected/?a=1")

        assert response.status_code == 302
        assert response.url == "/login/?next=/protected/%3Fa%3D1"

    @pytest.mark.urls("tests.urls")
    def test_signed_in_user_reaches_protected_view(self, client):
        client.force_login(UserFactory())

        assert client.get("/protected/").content == b"protected"

    def test_anonymous_admin_visit_ends_up_at_sso(self, client):
        response = client.get("/admin/", follow=True)

        assert [url for url, _ in response.redirect_chain[:3]] == [
            "/admin/login/?next=/admin/",
            "/login/?next=/admin/",
            "/auth/login/?next=%2Fadmin%2F",
        ]

    def test_healthcheck_is_exempt(self, client):
        assert client.get(reverse("healthcheck")).status_code == 200

    def test_staff_user_reaches_admin(self, client):
        client.force_login(UserFactory(is_staff=True, is_superuser=True))

        assert client.get("/admin/").status_code == 200

    def test_logout_signs_the_user_out(self, client):
        client.force_login(UserFactory())

        response = client.post(reverse("logout"))

        assert response.status_code == 200
        assert b"You have signed out" in response.content
        assert "_auth_user_id" not in client.session
