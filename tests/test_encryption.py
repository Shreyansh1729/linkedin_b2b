# Core Encryption Verification
import os
os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32

from linkedin.models import LinkedInProfile
from django.test import TestCase
from django.contrib.auth.models import User

class EncryptionTest(TestCase):
    def test_password_encryption(self):
        user = User.objects.create(username="testuser")
        profile = LinkedInProfile.objects.create(
            user=user,
            linkedin_username="test@example.com",
            linkedin_password="mypassword123"
        )
        # Check that the password is not stored in plaintext in the DB raw value
        # But should be decrypted transparently
        self.assertEqual(profile.linkedin_password, "mypassword123")
        
        # Verify it's actually different from raw saved value (internal check)
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT linkedin_password FROM linkedin_linkedinprofile WHERE id=%s", [profile.id])
            raw_val = cursor.fetchone()[0]
            self.assertNotEqual(raw_val, "mypassword123")
