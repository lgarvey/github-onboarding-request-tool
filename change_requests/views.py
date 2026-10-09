from dataclasses import dataclass

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from catalogue.choices import RepositoryPermission, TeamRole
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


@dataclass(frozen=True)
class Section:
    """One group of dynamic rows on an edit form."""

    context_name: str
    prefix: str
    principal_type: PrincipalType
    current: dict[str, str]
    principal_choices: list
    permission_choices: list


def _edit_access(request, *, org, target_type, target_name, sections, template, context):
    """Show and process a form that changes who has access to an existing repository or team."""
    draft = _get_draft(
        request,
        organisation=org,
        target_type=target_type,
        target_name=target_name,
        action=Action.MODIFY,
    )
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

    errors = []
    forms_valid = [
        form.is_valid() for form in (*(formset for _, formset in formsets), portfolio_form)
    ]
    if request.method == "POST" and all(forms_valid):
        # The diff is always against the YAML, not against what the form started with.
        items = []
        for section, formset in formsets:
            items += diff_permissions(section.current, formset.desired(), section.principal_type)
        if items:
            change_request = save_draft(
                requested_by=request.user,
                organisation=org,
                target_type=target_type,
                target_name=target_name,
                action=Action.MODIFY,
                portfolio=portfolio_form.cleaned_data["portfolio"],
                items=items,
                draft=draft,
            )
            return redirect("change_request_confirm", change_request.pk)
        errors.append(NO_CHANGES)

    context = {
        **context,
        **{section.context_name: formset for section, formset in formsets},
        "org": org,
        "portfolio_form": portfolio_form,
        "errors": errors,
    }
    return render(request, template, context)


@require_http_methods(["GET", "POST"])
def repository_edit(request, org, repo):
    _require_organisation(org)
    repository = terraform_config.get_repository(org, repo)
    if repository is None:
        raise Http404("Unknown repository")
    if repository.archived:
        messages.error(request, f"{repository.name} is archived and cannot be edited.")
        return redirect("organisation_detail", org)

    return _edit_access(
        request,
        org=org,
        target_type=TargetType.REPOSITORY,
        target_name=repository.name,
        sections=[
            Section(
                context_name="team_formset",
                prefix="teams",
                principal_type=PrincipalType.TEAM,
                current=repository.team_permissions,
                principal_choices=_team_choices(org),
                permission_choices=RepositoryPermission.choices,
            ),
            Section(
                context_name="user_formset",
                prefix="users",
                principal_type=PrincipalType.USER,
                current=repository.user_permissions,
                principal_choices=_user_choices(),
                permission_choices=RepositoryPermission.choices,
            ),
        ],
        template="change_requests/repository_edit.html",
        context={"repository": repository},
    )


@require_http_methods(["GET", "POST"])
def team_edit(request, org, slug):
    _require_organisation(org)
    team = terraform_config.get_team(org, slug)
    if team is None:
        raise Http404("Unknown team")

    return _edit_access(
        request,
        org=org,
        target_type=TargetType.TEAM,
        target_name=team.slug,
        sections=[
            Section(
                context_name="member_formset",
                prefix="members",
                principal_type=PrincipalType.USER,
                current=team.members,
                principal_choices=_user_choices(),
                permission_choices=TeamRole.choices,
            ),
        ],
        template="change_requests/team_edit.html",
        context={"team": team},
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
