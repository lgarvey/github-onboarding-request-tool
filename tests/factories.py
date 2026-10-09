import factory

from catalogue.choices import RepositoryPermission
from change_requests.choices import Action, Operation, PrincipalType, TargetType
from change_requests.models import ChangeItem, ChangeRequest
from portfolios.models import Approver, Portfolio
from users.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email_user_id = factory.Sequence(lambda n: f"user{n}-abc123@id.example.com")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = "Test"
    last_name = factory.Sequence(lambda n: f"User{n}")
    password = factory.PostGenerationMethodCall("set_password", "password")

    @factory.post_generation
    def _save_password(obj, create, extracted, **kwargs):
        if create:
            obj.save()


class PortfolioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Portfolio

    name = factory.Sequence(lambda n: f"Portfolio {n}")
    description = "A portfolio"


class ApproverFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Approver

    portfolio = factory.SubFactory(PortfolioFactory)
    name = factory.Sequence(lambda n: f"Approver {n}")
    email = factory.Sequence(lambda n: f"approver{n}@example.com")


class ChangeRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChangeRequest

    requested_by = factory.SubFactory(UserFactory)
    organisation = "acme"
    target_type = TargetType.REPOSITORY
    target_name = "trade-api"
    action = Action.MODIFY
    portfolio = factory.SubFactory(PortfolioFactory)


class ChangeItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChangeItem

    change_request = factory.SubFactory(ChangeRequestFactory)
    operation = Operation.ADD
    principal_type = PrincipalType.USER
    principal_name = factory.Sequence(lambda n: f"ghuser{n}")
    old_permission = None
    new_permission = RepositoryPermission.PUSH
