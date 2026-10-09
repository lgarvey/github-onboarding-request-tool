from django import forms
from django.forms import BaseFormSet, formset_factory

from portfolios.models import Portfolio

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
