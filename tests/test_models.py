import os
from django.test import TestCase
from django.contrib.auth.models import User
from linkedin.models import LinkedInProfile, Task, Campaign
from django.utils import timezone
import os

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32

class ModelHardeningTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")
        self.campaign = Campaign.objects.create(name="Test Campaign")

    def test_linkedin_profile_encryption(self):
        profile = LinkedInProfile.objects.create(
            user=self.user,
            linkedin_username="test@example.com",
            linkedin_password="secretpassword"
        )
        
        # Verify transparency
        self.assertEqual(profile.linkedin_password, "secretpassword")
        
        # Verify DB storage is encrypted
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT linkedin_password FROM linkedin_linkedinprofile WHERE id=%s", [profile.id])
            raw_value = cursor.fetchone()[0]
            self.assertTrue(raw_value.startswith("gAAAA"))
            self.assertNotEqual(raw_value, "secretpassword")

    def test_task_status_methods(self):
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=timezone.now()
        )
        
        self.assertEqual(task.status, Task.Status.PENDING)
        
        task.mark_running()
        self.assertEqual(task.status, Task.Status.RUNNING)
        self.assertIsNotNone(task.started_at)
        
        task.mark_skipped("Rate limited")
        self.assertEqual(task.status, Task.Status.SKIPPED)
        self.assertEqual(task.error, "Rate limited")
        self.assertIsNotNone(task.ended_at)
        
        task.mark_failed("Fatal error")
        self.assertEqual(task.status, Task.Status.FAILED)
        self.assertEqual(task.error, "Fatal error")
        self.assertIsNotNone(task.ended_at)
