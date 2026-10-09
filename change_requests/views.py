from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from catalogue.choices import RepositoryPermission
from catalogue.services import terraform_config
from change_requests.choices import Action, PrincipalType, Status, TargetType
from change_requests.forms import PortfolioForm, build_principal_formset
from change_requests.models import ChangeRequest
from change_requests.services.diff import diff_permissions
from change_requests.services.drafts import apply_items, save_draft
from github_users.services import list_usernames

NO_CHANGES = "No changes made."


def _require_organisation(org):
    if org not in terraform_config.list_organisations():
        raise Http404("Unknown organisation")


def _get_draft(request, **match):
    """The draft named by `?draft=`, if any. It must be the user's own and match the target."""
    draft_id = request.GET.get("draft")
    if not draft_id:
        return None
    if not draft_id.isdigit():
        raise Http404("Unknown draft")
    return get_object_or_404(
        ChangeRequest, pk=draft_id, requested_by=request.user, status=Status.DRAFT, **match
    )


def _team_choices(org):
    return [(team.slug, f"{team.name} ({team.slug})") for team in terraform_config.get_teams(org)]


def _user_choices():
    return [(username, username) for username in list_usernames()]


@require_http_methods(["GET", "POST"])
def repository_edit(request, org, repo):
    _require_organisation(org)
    repository = terraform_config.get_repository(org, repo)
    if repository is None:
        raise Http404("Unknown repository")
    if repository.archived:
        messages.error(request, f"{repository.name} is archived and cannot be edited.")
        return redirect("organisation_detail", org)

    draft = _get_draft(
        request,
        organisation=org,
        target_type=TargetType.REPOSITORY,
        target_name=repository.name,
        action=Action.MODIFY,
    )
    team_initial = repository.team_permissions
    user_initial = repository.user_permissions
    if draft:
        items = list(draft.items.all())
        team_initial = apply_items(team_initial, items, PrincipalType.TEAM)
        user_initial = apply_items(user_initial, items, PrincipalType.USER)

    data = request.POST or None
    team_formset = build_principal_formset(
        data,
        prefix="teams",
        initial=team_initial,
        principal_choices=_team_choices(org),
        permission_choices=RepositoryPermission.choices,
    )
    user_formset = build_principal_formset(
        data,
        prefix="users",
        initial=user_initial,
        principal_choices=_user_choices(),
        permission_choices=RepositoryPermission.choices,
    )
    portfolio_form = PortfolioForm(
        data, initial={"portfolio": draft.portfolio_id if draft else None}
    )

    errors = []
    forms_valid = [form.is_valid() for form in (team_formset, user_formset, portfolio_form)]
    if request.method == "POST" and all(forms_valid):
        # The diff is always against the YAML, not against what the form started with.
        items = diff_permissions(
            repository.team_permissions, team_formset.desired(), PrincipalType.TEAM
        ) + diff_permissions(
            repository.user_permissions, user_formset.desired(), PrincipalType.USER
        )
        if items:
            change_request = save_draft(
                requested_by=request.user,
                organisation=org,
                target_type=TargetType.REPOSITORY,
                target_name=repository.name,
                action=Action.MODIFY,
                portfolio=portfolio_form.cleaned_data["portfolio"],
                items=items,
                draft=draft,
            )
            return redirect("change_request_confirm", change_request.pk)
        errors.append(NO_CHANGES)

    return render(
        request,
        "change_requests/repository_edit.html",
        {
            "org": org,
            "repository": repository,
            "team_formset": team_formset,
            "user_formset": user_formset,
            "portfolio_form": portfolio_form,
            "errors": errors,
        },
    )


@require_http_methods(["GET", "POST"])
def change_request_confirm(request, pk):
    change_request = get_object_or_404(
        ChangeRequest, pk=pk, requested_by=request.user, status=Status.DRAFT
    )
    if request.method == "POST":
        change_request.submit()
        messages.success(request, f"Your request has been submitted: {change_request}.")
        return redirect("organisation_detail", change_request.organisation)

    return render(
        request,
        "change_requests/confirm.html",
        {"change_request": change_request, "summary_lines": change_request.summary_lines()},
    )
