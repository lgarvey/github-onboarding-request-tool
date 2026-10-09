from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from config import views
from users import views as user_views

urlpatterns = [
    # Must come before admin.site.urls so it takes over /admin/login/.
    path("admin/login/", user_views.admin_login, name="admin_login"),
    path("admin/", admin.site.urls),
    path("auth/", include("users.authbroker_urls")),
    path("login/", user_views.login, name="login"),
    path("logout/", LogoutView.as_view(template_name="users/logged_out.html"), name="logout"),
    path("healthcheck/", views.healthcheck, name="healthcheck"),
    path("", include("catalogue.urls")),
    path("", include("change_requests.urls")),
]
