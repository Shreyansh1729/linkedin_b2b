import os
from django.test import TestCase
from django.utils import timezone
from unittest.mock import MagicMock, patch
from linkedin.models import Task, Campaign, LinkedInProfile
from crm.models import Lead, Deal
from linkedin.tasks.connect import handle_connect, enqueue_connect
from linkedin.exceptions import TaskSkipped, ReachedConnectionLimit

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32

class TaskHardeningTest(TestCase):
    def setUp(self):
        self.campaign = Campaign.objects.create(name="Test Campaign")
        # Need a user for LinkedInProfile
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username="testuser")
        self.profile = LinkedInProfile.objects.create(user=self.user)
        
    def test_enqueue_connect_with_deal(self):
        lead = Lead.objects.create(
            first_name="John", 
            last_name="Doe", 
            public_identifier="johndoe",
            linkedin_url="https://www.linkedin.com/in/johndoe/"
        )
        deal = Deal.objects.create(lead=lead, campaign=self.campaign)
        
        enqueue_connect(self.campaign.id, delay_seconds=10, deal=deal)
        
        task = Task.objects.get(task_type=Task.TaskType.CONNECT)
        self.assertEqual(task.deal, deal)
        self.assertEqual(task.payload['campaign_id'], self.campaign.id)

    @patch('linkedin.tasks.connect.strategy_for')
    def test_handle_connect_rate_limit(self, mock_strategy_for):
        # Setup mocks
        mock_strategy = MagicMock()
        mock_strategy_for.return_value = mock_strategy
        
        # strategy_for is mocked to avoid DB lookups for qualifiers.
        # find_candidate is never reached because can_execute=False fires first.
        task = Task.objects.create(
            task_type=Task.TaskType.CONNECT,
            scheduled_at=timezone.now(),
            started_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        
        # Mock can_execute to return False (simulating rate limit)
        with patch.object(LinkedInProfile, 'can_execute', return_value=False):
            with self.assertRaises(TaskSkipped):
                handle_connect(task, session, {})
        
        # Verify a new task was enqueued
        # There should be the original task and a new one
        self.assertEqual(Task.objects.count(), 2)
        new_task = Task.objects.exclude(id=task.id).first()
        self.assertEqual(new_task.status, Task.Status.PENDING)
        self.assertEqual(new_task.task_type, Task.TaskType.CONNECT)

    def test_check_pending_expiry(self):
        # [NEW-CRIT-01] Test 30-day age limit logic
        from datetime import timedelta
        from linkedin.tasks.check_pending import handle_check_pending
        from linkedin.enums import ProfileState
        
        lead = Lead.objects.create(public_identifier="old_guy")
        deal = Deal.objects.create(lead=lead, campaign=self.campaign)
        
        # Manually backdate creation_date
        old_date = timezone.now() - timedelta(days=31)
        Deal.objects.filter(pk=deal.pk).update(creation_date=old_date)
        deal.refresh_from_db()
        
        task = Task.objects.create(
            task_type=Task.TaskType.CHECK_PENDING,
            payload={"campaign_id": self.campaign.id, "public_id": "old_guy"},
            scheduled_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        
        handle_check_pending(task, session, {})
        
        deal.refresh_from_db()
        self.assertEqual(deal.state, ProfileState.FAILED)
        self.assertIn("Expired", deal.reason)

    def test_send_message_missing_data(self):
        # [MED-06] send_message: ChatMessage or Deal missing
        from linkedin.tasks.send_message import handle_send_message
        
        task = Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            payload={"campaign_id": self.campaign.id, "public_id": "who", "message_id": 9999},
            scheduled_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        
        with self.assertRaisesRegex(RuntimeError, "ChatMessage 9999 no longer exists"):
            handle_send_message(task, session)

    def test_send_message_missing_deal(self):
        # [MED-06] send_message: Deal missing
        from linkedin.tasks.send_message import handle_send_message
        from chat.models import ChatMessage
        
        msg = ChatMessage.objects.create(
            content="Hello", 
            linkedin_urn="test_urn",
            content_type_id=1, object_id=1 # dummy
        )
        
        task = Task.objects.create(
            task_type=Task.TaskType.SEND_MESSAGE,
            payload={"campaign_id": self.campaign.id, "public_id": "missing_deal", "message_id": msg.pk},
            scheduled_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        
        with self.assertRaisesRegex(RuntimeError, "No Deal found"):
            handle_send_message(task, session)

    def test_freemium_model_loading(self):
        # [HIGH-01] Test freemium model loading logic in dairy builder
        from linkedin.daemon import _build_qualifiers
        
        self.campaign.is_freemium = True
        self.campaign.save()
        
        # Mock load_ml_model to return a dummy model
        mock_model = MagicMock()
        with patch.object(Campaign, 'load_ml_model', return_value=mock_model):
            qualifiers = _build_qualifiers([self.campaign], {"qualification_n_mc_samples": 100})
            
            self.assertIn(self.campaign.pk, qualifiers)
            self.assertEqual(qualifiers[self.campaign.pk]._model, mock_model)

    def test_follow_up_dedup_guard(self):
        # Verify follow_up doesn't create duplicate drafts
        from linkedin.tasks.follow_up import handle_follow_up
        from chat.models import ChatMessage
        from django.contrib.contenttypes.models import ContentType
        
        from linkedin.enums import ProfileState
        lead = Lead.objects.create(public_identifier="dedup_test")
        deal = Deal.objects.create(lead=lead, campaign=self.campaign, state=ProfileState.CONNECTED.value)
        
        task = Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            payload={"campaign_id": self.campaign.id, "public_id": "dedup_test"},
            scheduled_at=timezone.now()
        )
        
        session = MagicMock()
        session.campaign = self.campaign
        session.linkedin_profile = self.profile
        
        # Mock the agent to suggest sending a message
        decision = MagicMock()
        decision.action = "send_message"
        decision.message = "Hello again"
        
        with patch('linkedin.agents.follow_up.run_follow_up_agent', return_value=decision):
            # 1. First run creates a draft
            handle_follow_up(task, session, {})
            self.assertEqual(ChatMessage.objects.filter(is_draft=True).count(), 1)
            
            # 2. Second run should NOT create another draft
            handle_follow_up(task, session, {})
            self.assertEqual(ChatMessage.objects.filter(is_draft=True).count(), 1)
