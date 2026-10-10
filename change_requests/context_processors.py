from change_requests.choices import Status
from change_requests.models import ChangeRequest
from portfolios.models import portfolios_approved_by


def approvals(request):
    """Whether to show the Approvals link, and how many requests are waiting."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    portfolios = portfolios_approved_by(user)
    if not portfolios.exists():
        return {"is_approver": False}
    waiting = ChangeRequest.objects.filter(
        portfolio__in=portfolios, status=Status.SUBMITTED
    ).exclude(requested_by=user)
    return {"is_approver": True, "approvals_waiting": waiting.count()}
