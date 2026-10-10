from django import forms
from django.core.validators import RegexValidator
from django.forms import BaseFormSet, formset_factory
from django.utils.text import slugify

from catalogue.services import github_teams, terraform_config
from portfolios.models import Portfolio

# From the `name` pattern in terraform-github-sample/schemas/terraform-repository-schema.yaml.
REPOSITORY_NAME_PATTERN = r"^[.a-zA-Z][a-zA-Z0-9_-]*$"

EMPTY_CHOICE = ("", "Select…")


class PortfolioForm(forms.Form):
    portfolio = forms.ModelChoiceField(
        queryset=Portfolio.objects.all(),
        empty_label="Select a portfolio…",
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="The portfolio whose approvers should sign this request off.",
    )


class PrincipalRowForm(forms.Form):
    """One row granting a principal (team or user) a permission or role."""

    principal = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-select"}))
    permission = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, principal_choices=(), permission_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["principal"].choices = [EMPTY_CHOICE, *principal_choices]
        self.fields["permission"].choices = [EMPTY_CHOICE, *permission_choices]


class BasePrincipalFormSet(BaseFormSet):
    def _kept_rows(self):
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            data = getattr(form, "cleaned_data", None)
            # Untouched extra rows validate with no data; ignore them.
            if data and data.get("principal"):
                yield data

    def clean(self):
        if any(self.errors):
            return
        seen = set()
        for row in self._kept_rows():
            if row["principal"] in seen:
                raise forms.ValidationError(f"{row['principal']} is listed more than once.")
            seen.add(row["principal"])

    def desired(self) -> dict[str, str]:
        """The `{principal: permission}` mapping the user asked for. Call after is_valid()."""
        return {row["principal"]: row["permission"] for row in self._kept_rows()}


PrincipalFormSet = formset_factory(
    PrincipalRowForm, formset=BasePrincipalFormSet, extra=0, can_delete=True
)


def build_principal_formset(data, *, prefix, initial, principal_choices, permission_choices):
    """Build a formset of rows from a `{principal: permission}` mapping.

    Principals already in `initial` are always selectable, so existing access that the
    choices don't know about is shown rather than silently dropped.
    """
    known = {value for value, _ in principal_choices}
    extra_choices = [(name, name) for name in sorted(initial) if name not in known]
    return PrincipalFormSet(
        data,
        prefix=prefix,
        initial=[{"principal": name, "permission": level} for name, level in initial.items()],
        form_kwargs={
            "principal_choices": [*principal_choices, *extra_choices],
            "permission_choices": permission_choices,
        },
    )


class RepositoryDetailsForm(forms.Form):
    """Name and description of a repository to be created."""

    name = forms.CharField(
        max_length=100,
        validators=[
            RegexValidator(
                REPOSITORY_NAME_PATTERN,
                "Use letters, numbers, hyphens and underscores, starting with a letter or a dot.",
            )
        ],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    description = forms.CharField(
        required=False, max_length=350, widget=forms.TextInput(attrs={"class": "form-control"})
    )

    def __init__(self, *args, org, draft=None, **kwargs):
        if draft:
            kwargs["initial"] = {
                "name": draft.target_name,
                "description": draft.details.get("description", ""),
            }
        super().__init__(*args, **kwargs)
        self.org = org

    def clean_name(self):
        name = self.cleaned_data["name"]
        existing = {repo.name.lower() for repo in terraform_config.get_repositories(self.org)}
        if name.lower() in existing:
            raise forms.ValidationError(f"A repository called {name} already exists in {self.org}.")
        return name

    def target_name(self):
        return self.cleaned_data["name"]

    def details(self):
        return {"description": self.cleaned_data["description"]}


class TeamDetailsForm(forms.Form):
    """Name, description and optional parent of a team to be created."""

    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={"class": "form-control"}))
    description = forms.CharField(
        required=False, max_length=350, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    parent = forms.ChoiceField(
        required=False,
        label="Parent team",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, org, draft=None, **kwargs):
        if draft:
            kwargs["initial"] = {
                "name": draft.target_name,
                "description": draft.details.get("description", ""),
                "parent": draft.details.get("parent_team", ""),
            }
        super().__init__(*args, **kwargs)
        self.org = org
        self.teams = terraform_config.get_teams(org)
        self.fields["parent"].choices = [
            ("", "No parent"),
            *((team.slug, f"{team.name} ({team.slug})") for team in self.teams),
        ]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        slug = slugify(name)
        if not slug:
            raise forms.ValidationError("Enter a name containing letters or numbers.")
        taken = {team.slug.lower() for team in self.teams} | {t.name.lower() for t in self.teams}
        if slug in taken or name.lower() in taken:
            raise forms.ValidationError(f"A team called {name} already exists in {self.org}.")
        return name

    def clean(self):
        cleaned = super().clean()
        name, parent = cleaned.get("name"), cleaned.get("parent")
        if name and parent and parent == slugify(name):
            self.add_error("parent", "A team cannot be its own parent.")
        return cleaned

    def target_name(self):
        return self.cleaned_data["name"]

    def details(self):
        details = {
            "description": self.cleaned_data["description"],
            "slug": slugify(self.cleaned_data["name"]),
        }
        parent = self.cleaned_data["parent"]
        if parent:
            details["parent_team"] = parent
            # The YAML wants GitHub's numeric ID for the parent, so record it now.
            details["parent_team_id"] = github_teams.get_team_id(self.org, parent)
        return details
