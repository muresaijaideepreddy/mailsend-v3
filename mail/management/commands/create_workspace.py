import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from mail.models import Membership, Workspace


class Command(BaseCommand):
    help = 'Create an executive account and workspace without sending invitations.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--email', required=True)
        parser.add_argument('--name', required=True, help='Workspace display name')

    def handle(self, *args, **options):
        User = get_user_model()
        username, email = options['username'].strip(), options['email'].strip().lower()
        if User.objects.filter(username__iexact=username).exists() or User.objects.filter(email__iexact=email).exists():
            raise CommandError('An account with this username or email already exists.')
        user = User(username=username, email=email)
        try:
            validate_email(email)
            user.full_clean(exclude=['password'])
            password = getpass.getpass('Executive password: ')
            confirm = getpass.getpass('Confirm password: ')
            if password != confirm:
                raise CommandError('Passwords do not match.')
            validate_password(password, user=user)
            workspace = Workspace(name=options['name'].strip(), executive=user)
            if not workspace.name or len(workspace.name) > 160:
                raise CommandError('Workspace name must contain 1 to 160 characters.')
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages)) from exc
        with transaction.atomic():
            user.set_password(password)
            user.save()
            workspace.save()
            Membership.objects.create(user=user, workspace=workspace, role='executive')
        self.stdout.write(self.style.SUCCESS('Executive workspace created. Sign in locally, then connect the matching Google account.'))
