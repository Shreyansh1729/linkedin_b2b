from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.db import models
from django.template.defaultfilters import truncatechars
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.urls import reverse


class ChatMessage(models.Model):
    
    class Meta:
        verbose_name = _("message")
        verbose_name_plural = _("messages")

    campaign = models.ForeignKey(
        "linkedin.Campaign", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="messages",
        verbose_name=_("Campaign")
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(db_index=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    content = models.TextField(
        blank=True, default='',
        verbose_name=_("Message")
    )    
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.CASCADE,
        verbose_name=_("Owner"),
        related_name="%(app_label)s_%(class)s_owner_related",
    )
    creation_date = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Creation date")
    )

    linkedin_urn = models.CharField(
        max_length=300, unique=True,
        verbose_name=_("LinkedIn message URN"),
        help_text=_("entityUrn from Voyager API, used for dedup"),
    )
    is_outgoing = models.BooleanField(
        default=True,
        verbose_name=_("Outgoing"),
        help_text=_("True if sent by us, False if received"),
    )
    is_draft = models.BooleanField(
        default=False,
        verbose_name=_("Is Draft"),
        help_text=_("True if the message is drafted by AI and waiting for approval"),
    )
    is_approved = models.BooleanField(
        default=False,
        verbose_name=_("Is Approved"),
        help_text=_("True if the admin has approved this drafted message to be sent"),
    )

    def __str__(self):
        return f'{truncatechars(self.content, 70)}'

    def get_absolute_url(self):
        return reverse(f'admin:chat_{self._meta.model_name}_change', args=[str(self.id)])
