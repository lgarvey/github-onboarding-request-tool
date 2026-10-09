from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.views.decorators.http import require_GET


@login_not_required
@require_GET
def healthcheck(request):
    return HttpResponse("OK", content_type="text/plain")
