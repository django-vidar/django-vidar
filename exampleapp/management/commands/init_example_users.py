import logging
import os
from django.core.management.base import BaseCommand

from django.contrib.auth import get_user_model

UserModel = get_user_model()

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Initializes Django with superuser"

    def handle(self, *args, **options):

        if UserModel.objects.all().exists():
            self.stdout.write("Users already exist in the system.")
            return

        UserModel.objects.create_superuser(
            username=os.environ.get('DJANGO_SUPERUSER_USERNAME'),
            password=os.environ.get('DJANGO_SUPERUSER_PASSWORD'),
            email=os.environ.get('DJANGO_SUPERUSER_EMAIL'),
        )
