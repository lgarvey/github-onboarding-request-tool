from django.conf import settings
from django.db import models


class Portfolio(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def portfolios_approved_by(user):
    """The portfolios a user can approve requests for: those with an approver linked to them."""
    if not user.is_authenticated:
        return Portfolio.objects.none()
    return Portfolio.objects.filter(approvers__user=user).distinct()


class Approver(models.Model):
    """Someone who can approve requests for a portfolio.

    `email` is the address to contact them on, which is not necessarily the one on their
    user account: an SSO user can have several. `user` is what lets them sign in and see the
    requests waiting for them. It can be left empty until they have an account.
    """

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="approvers")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approver_roles",
        help_text="The account this approver signs in with. Without it they cannot see requests.",
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(verbose_name="contact email")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["portfolio", "email"], name="unique_approver_email_per_portfolio"
            ),
            models.UniqueConstraint(
                fields=["portfolio", "user"],
                condition=models.Q(user__isnull=False),
                name="unique_approver_user_per_portfolio",
            ),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"
