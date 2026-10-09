from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.urls import reverse


def test_healthcheck_returns_200(client):
    response = client.get(reverse("healthcheck"))

    assert response.status_code == 200
    assert response.content == b"OK"


def test_healthcheck_rejects_post(client):
    assert client.post(reverse("healthcheck")).status_code == 405


def test_bootstrap_is_vendored():
    assert finders.find("bootstrap/css/bootstrap.min.css")
    assert finders.find("bootstrap/js/bootstrap.bundle.min.js")


def test_base_template_uses_vendored_bootstrap():
    html = render_to_string("base.html")

    assert "/static/bootstrap/css/bootstrap.min.css" in html
    assert "/static/bootstrap/js/bootstrap.bundle.min.js" in html
    assert "cdn" not in html.lower()
