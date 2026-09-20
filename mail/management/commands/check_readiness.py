"""Fail closed before serving a production deployment; never contact Gmail."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.models import Q

from config.production import production_errors
from config.readiness import database_ready


class Command(BaseCommand):
    help = 'Check production configuration, database migrations and absence of known demo accounts without sending email.'

    def handle(self, *args, **options):
        errors = production_errors(settings)
        if errors:
            raise CommandError('Readiness failed: ' + ' '.join(errors))
        try:
            if not database_ready():
                raise CommandError('Readiness failed: unapplied database migrations.')
            candidates = get_user_model().objects.filter(
                Q(username__iexact='executive') | Q(username__iexact='assistant')
                | Q(email__iexact='daniel@example.com') | Q(email__iexact='alex@example.com')
            )
            if any(user.email.lower() in ('daniel@example.com', 'alex@example.com')
                   or user.check_password('MailSend-Demo-2026!') for user in candidates):
                raise CommandError('Readiness failed: known demo accounts remain. Use a separate production database.')
        except (DatabaseError, InconsistentMigrationHistory, OSError):
            raise CommandError('Readiness failed: database is unavailable or migration history is inconsistent.') from None
        self.stdout.write(self.style.SUCCESS('Ready: production configuration, database, migrations and account checks passed.'))
