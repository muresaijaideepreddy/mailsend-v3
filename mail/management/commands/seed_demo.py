from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from mail.models import Membership, Message, Workspace

class Command(BaseCommand):
    help = 'Create isolated demo executive/assistant accounts and sample drafts. Never sends email.'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='MailSend-Demo-2026!')

    def handle(self, *args, **options):
        if not settings.DEBUG or settings.MAILSEND_DELIVERY_MODE != 'demo':
            raise CommandError('Demo accounts can only be created with DEBUG=true and demo delivery.')
        User = get_user_model()
        with transaction.atomic():
            # Never adopt an unrelated account just because its username happens
            # to match a demo username. Repeat runs may only reuse the complete,
            # internally consistent account pair created by the first run.
            existing = list(User.objects.select_for_update().filter(
                Q(username__iexact='executive') | Q(username__iexact='assistant')
                | Q(email__iexact='daniel@example.com') | Q(email__iexact='alex@example.com')
            ))
            created = not existing
            if existing:
                accounts = {user.username: user for user in existing}
                executive = accounts.get('executive')
                assistant = accounts.get('assistant')
                workspace = Workspace.objects.filter(executive=executive).first() if executive else None
                valid_pair = (
                    len(existing) == 2 and executive and assistant and workspace
                    and executive.email.lower() == 'daniel@example.com'
                    and assistant.email.lower() == 'alex@example.com'
                    and executive.is_active and assistant.is_active
                    and Membership.objects.filter(user=executive, workspace=workspace, role='executive').exists()
                    and Membership.objects.filter(user=assistant, workspace=workspace, role='assistant').exists()
                )
                if not valid_pair:
                    raise CommandError(
                        'Demo usernames or email addresses are already in use by accounts '
                        'outside a complete, consistent demo setup. Use an empty demo database; '
                        'existing accounts and memberships have not been changed.'
                    )
            else:
                try:
                    for username, email in [('executive', 'daniel@example.com'), ('assistant', 'alex@example.com')]:
                        validate_password(options['password'], user=User(username=username, email=email))
                except ValidationError as exc:
                    raise CommandError('; '.join(exc.messages)) from exc
                executive = User.objects.create_user(username='executive', email='daniel@example.com',
                    first_name='Daniel', last_name='Morgan', password=options['password'])
                assistant = User.objects.create_user(username='assistant', email='alex@example.com',
                    first_name='Alex', last_name='Rivera', password=options['password'])
                workspace = Workspace.objects.create(executive=executive,
                    name='Southwest Innovation Research Lab',
                    signature='Daniel Morgan\nSouthwest Innovation Research Lab')
                Membership.objects.create(user=executive, workspace=workspace, role='executive')
                Membership.objects.create(user=assistant, workspace=workspace, role='assistant')
            if created:
                today = timezone.localdate()
                for offset, recipient, subject, body in [
                    (-1, 'priya@example.com', 'Research partnership: next steps', 'Hi Priya,\n\nThank you for a thoughtful conversation about our research partnership. I would love to set up a follow-up next week to discuss the next phase.\n\nWould Tuesday afternoon work for you?'),
                    (0, 'james@example.com', 'A quick update on the innovation fellowship', 'Hi James,\n\nOur fellowship review is moving along well. I wanted to share a brief update and thank you for your support of the program.\n\nI look forward to discussing the finalists with you.'),
                    (0, 'maya@example.com', 'Materials for our Monday meeting', 'Hi Maya,\n\nAhead of our Monday meeting, please find the project overview below. We will cover the milestones, timeline, and opportunities to collaborate.\n\nLooking forward to it.'),
                    (2, 'team@example.com', 'This week at the lab', 'Hello team,\n\nA quick note to start the week. Please bring your research updates and any open questions to our next team meeting.\n\nThank you for the excellent work.'),
                    (8, 'partners@example.com', 'Quarterly research briefing', 'Hello everyone,\n\nWe are preparing our next quarterly research briefing. I look forward to sharing our latest findings and hearing your feedback.\n\nMore details to follow.'),
                ]:
                    Message.objects.create(workspace=workspace, created_by=assistant, to=recipient, subject=subject, body=body, send_date=today + timedelta(days=offset))
        self.stdout.write(self.style.SUCCESS('Demo ready. Usernames: executive and assistant.'))
        self.stdout.write('New accounts use --password or the documented demo password. Existing passwords are unchanged.')
