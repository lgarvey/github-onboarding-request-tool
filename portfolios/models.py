from django.db import models


class Portfolio(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def portfolios_approved_by(user):
    """The portfolios a user can approve requests for.

    Approvers are matched to users by email address, ignoring case.
    """
    if not user.is_authenticated or not user.email:
        return Portfolio.objects.none()
    return Portfolio.objects.filter(approvers__email__iexact=user.email).distinct()


class Approver(models.Model):
    """Someone who can approve requests for a portfolio. Not necessarily an app user."""

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="approvers")
    name = models.CharField(max_length=200)
    email = models.EmailField()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["portfolio", "email"], name="unique_approver_email_per_portfolio"
            ),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"
