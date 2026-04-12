import os
import datetime
from django.test import TestCase
from django.contrib.auth.models import User
from linkedin.models import LinkedInProfile, Task, Campaign
from linkedin.daemon import run_daemon
from linkedin.exceptions import TaskSkipped
from django.utils import timezone
from unittest.mock import patch, MagicMock

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32

class DaemonHardeningTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="daemon_tester")
        self.campaign = Campaign.objects.create(name="Daemon Campaign")
        self.profile = LinkedInProfile.objects.create(
            user=self.user,
            linkedin_username="daemon@example.com",
            linkedin_password="password"
        )
        
    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.timezone.now")
    def test_daemon_skips_task(self, mock_now, mock_diag, mock_handlers):
        # Use a fixed datetime from the standard library to bypass mocks
        fixed_now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        mock_now.return_value = fixed_now
        
        # Create a pending task assigned to our campaign
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=fixed_now - datetime.timedelta(minutes=1),
            payload={"campaign_id": self.campaign.pk}
        )
        
        # Mock handler to raise TaskSkipped
        mock_handler = MagicMock(side_effect=TaskSkipped("Rate limited locally"))
        mock_handlers.get.return_value = mock_handler
        
        # Create a mock session
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]
        
        # Run one iteration of daemon
        # We also need to patch django.utils.timezone.now because Task.objects.claim_next() uses it
        with patch("django.utils.timezone.now", return_value=fixed_now):
            with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    run_daemon(mock_session)
                except KeyboardInterrupt:
                    pass
        
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.SKIPPED)
        self.assertEqual(task.error, "Rate limited locally")

    @patch("linkedin.daemon.ENABLE_ACTIVE_HOURS", False)
    @patch("linkedin.daemon._HANDLERS")
    @patch("linkedin.daemon.failure_diagnostics")
    @patch("linkedin.daemon.timezone.now")
    def test_daemon_handles_failure(self, mock_now, mock_diag, mock_handlers):
        fixed_now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        mock_now.return_value = fixed_now

        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=fixed_now - datetime.timedelta(minutes=1),
            payload={"campaign_id": self.campaign.pk}
        )
        
        mock_handler = MagicMock(side_effect=Exception("Hard failure"))
        mock_handlers.get.return_value = mock_handler
        
        # Create a mock session
        mock_session = MagicMock()
        mock_session.campaigns = [self.campaign]
        
        with patch("django.utils.timezone.now", return_value=fixed_now):
            with patch("linkedin.daemon.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    run_daemon(mock_session)
                except KeyboardInterrupt:
                    pass
        
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.FAILED)
        self.assertIn("Hard failure", task.error)
