import logging
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Create or update an admin user for the LeadPilot dashboard."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email/Username for the admin user")

    def handle(self, *args, **options):
        email = options["email"]
        
        user, created = User.objects.get_or_create(username=email, defaults={"email": email})
        
        import getpass
        password = getpass.getpass(f"Password for {email}: ")
        confirm = getpass.getpass("Confirm password: ")
        
        if password != confirm:
            self.stdout.write(self.style.ERROR("Passwords do not match."))
            return

        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()
        
        status = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"Successfully {status.lower()} admin user: {email}"))
