from dataclasses import dataclass

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from catalogue.choices import RepositoryPermission, TeamRole
from catalogue.services import terraform_config
from change_requests.choices import Action, PrincipalType, Status, TargetType
from change_requests.forms import (
    PortfolioForm,
    RepositoryDetailsForm,
    TeamDetailsForm,
    build_principal_formset,
)
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


@dataclass(frozen=True)
class Section:
    """One group of dynamic rows on a form."""

    context_name: str
    prefix: str
    principal_type: PrincipalType
    current: dict[str, str]
    principal_choices: list
    permission_choices: list


def _team_permissions_section(org, current):
    return Section(
        context_name="team_formset",
        prefix="teams",
        principal_type=PrincipalType.TEAM,
        current=current,
        principal_choices=_team_choices(org),
        permission_choices=RepositoryPermission.choices,
    )


def _user_permissions_section(current):
    return Section(
        context_name="user_formset",
        prefix="users",
        principal_type=PrincipalType.USER,
        current=current,
        principal_choices=_user_choices(),
        permission_choices=RepositoryPermission.choices,
    )


def _members_section(current):
    return Section(
        context_name="member_formset",
        prefix="members",
        principal_type=PrincipalType.USER,
        current=current,
        principal_choices=_user_choices(),
        permission_choices=TeamRole.choices,
    )


def _change_form(
    request,
    *,
    org,
    target_type,
    action,
    sections,
    template,
    context,
    target_name=None,
    details_form_class=None,
):
    """Show and process a form that drafts a change request.

    Existing targets pass `target_name`. Creates pass `details_form_class` instead, which
    supplies the new name and the request's `details`.
    """
    match = {"organisation": org, "target_type": target_type, "action": action}
    if target_name is not None:
        match["target_name"] = target_name
    draft = _get_draft(request, **match)
    draft_items = list(draft.items.all()) if draft else []
    data = request.POST or None

    formsets = []
    for section in sections:
        initial = section.current
        if draft:
            initial = apply_items(initial, draft_items, section.principal_type)
        formset = build_principal_formset(
            data,
            prefix=section.prefix,
            initial=initial,
            principal_choices=section.principal_choices,
            permission_choices=section.permission_choices,
        )
        formsets.append((section, formset))
    portfolio_form = PortfolioForm(data, initial={"portfolio": draft and draft.portfolio_id})
    details_form = details_form_class(data, org=org, draft=draft) if details_form_class else None

    all_forms = [*(formset for _, formset in formsets), portfolio_form]
    if details_form:
        all_forms.append(details_form)
    forms_valid = [form.is_valid() for form in all_forms]

    errors = []
    if request.method == "POST" and all(forms_valid):
        # The diff is always against the YAML, not against what the form started with.
        items = []
        for section, formset in formsets:
            items += diff_permissions(section.current, formset.desired(), section.principal_type)
        if action == Action.MODIFY and not items:
            errors.append(NO_CHANGES)
        else:
            change_request = save_draft(
                requested_by=request.user,
                organisation=org,
                target_type=target_type,
                target_name=details_form.target_name() if details_form else target_name,
                action=action,
                portfolio=portfolio_form.cleaned_data["portfolio"],
                items=items,
                details=details_form.details() if details_form else None,
                draft=draft,
            )
            return redirect("change_request_confirm", change_request.pk)

    context = {
        **context,
        **{section.context_name: formset for section, formset in formsets},
        "org": org,
        "portfolio_form": portfolio_form,
        "details_form": details_form,
        "errors": errors,
    }
    return render(request, template, context)


def _get_repository(org, repo):
    _require_organisation(org)
    repository = terraform_config.get_repository(org, repo)
    if repository is None:
        raise Http404("Unknown repository")
    return repository


@require_http_methods(["GET", "POST"])
def repository_edit(request, org, repo):
    repository = _get_repository(org, repo)
    if repository.archived:
        messages.error(request, f"{repository.name} is archived and cannot be edited.")
        return redirect("organisation_detail", org)

    return _change_form(
        request,
        org=org,
        target_type=TargetType.REPOSITORY,
        target_name=repository.name,
        action=Action.MODIFY,
        sections=[
            _team_permissions_section(org, repository.team_permissions),
            _user_permissions_section(repository.user_permissions),
        ],
        template="change_requests/repository_edit.html",
        context={"repository": repository},
    )


@require_http_methods(["GET", "POST"])
def repository_archive(request, org, repo):
    repository = _get_repository(org, repo)
    if repository.archived:
        messages.error(request, f"{repository.name} is already archived.")
        return redirect("organisation_detail", org)

    return _change_form(
        request,
        org=org,
        target_type=TargetType.REPOSITORY,
        target_name=repository.name,
        action=Action.ARCHIVE,
        sections=[],
        template="change_requests/repository_archive.html",
        context={"repository": repository},
    )


@require_http_methods(["GET", "POST"])
def repository_create(request, org):
    _require_organisation(org)
    return _change_form(
        request,
        org=org,
        target_type=TargetType.REPOSITORY,
        action=Action.CREATE,
        details_form_class=RepositoryDetailsForm,
        sections=[_team_permissions_section(org, {}), _user_permissions_section({})],
        template="change_requests/repository_create.html",
        context={},
    )


@require_http_methods(["GET", "POST"])
def team_edit(request, org, slug):
    _require_organisation(org)
    team = terraform_config.get_team(org, slug)
    if team is None:
        raise Http404("Unknown team")

    return _change_form(
        request,
        org=org,
        target_type=TargetType.TEAM,
        target_name=team.slug,
        action=Action.MODIFY,
        sections=[_members_section(team.members)],
        template="change_requests/team_edit.html",
        context={"team": team},
    )


@require_http_methods(["GET", "POST"])
def team_create(request, org):
    _require_organisation(org)
    return _change_form(
        request,
        org=org,
        target_type=TargetType.TEAM,
        action=Action.CREATE,
        details_form_class=TeamDetailsForm,
        sections=[_members_section({})],
        template="change_requests/team_create.html",
        context={},
    )


@require_http_methods(["GET", "POST"])
def change_request_confirm(request, pk):
    change_request = get_object_or_404(
        ChangeRequest, pk=pk, requested_by=request.user, status=Status.DRAFT
    )
    if request.method == "POST":
        change_request.submit()
        messages.success(request, f"Your request has been submitted: {change_request}.")
        return redirect("change_request_list")

    return render(
        request,
        "change_requests/confirm.html",
        {"change_request": change_request, "summary_lines": change_request.summary_lines()},
    )


def _submitted_requests(user):
    """A user's requests that have left draft, newest first."""
    return (
        ChangeRequest.objects.filter(requested_by=user)
        .exclude(status=Status.DRAFT)
        .select_related("portfolio")
        .order_by("-submitted_at", "-pk")
    )


def change_request_list(request):
    drafts = (
        ChangeRequest.objects.filter(requested_by=request.user, status=Status.DRAFT)
        .select_related("portfolio")
        .order_by("-created_at", "-pk")
    )
    return render(
        request,
        "change_requests/list.html",
        {"change_requests": _submitted_requests(request.user), "drafts": drafts},
    )


@require_POST
def change_request_discard(request, pk):
    draft = get_object_or_404(ChangeRequest, pk=pk, requested_by=request.user, status=Status.DRAFT)
    description = str(draft)
    draft.delete()
    messages.success(request, f"Draft discarded: {description}.")
    return redirect("change_request_list")


def change_request_detail(request, pk):
    change_request = get_object_or_404(_submitted_requests(request.user), pk=pk)
    return render(
        request,
        "change_requests/detail.html",
        {"change_request": change_request, "summary_lines": change_request.summary_lines()},
    )
