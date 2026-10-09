import factory

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
