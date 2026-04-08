from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.utils import timezone
from django.utils.html import format_html, mark_safe
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from chat.models import ChatMessage
from crm.models.deal import Deal
from crm.models.lead import Lead
from linkedin.models import ActionLog, Task


@admin.register(Lead)
class LeadAdmin(ModelAdmin):
    list_display = ("full_name", "company_name", "linkedin_link", "disqualified", "creation_date")
    list_filter = ("disqualified", "company_name")
    search_fields = ("first_name", "last_name", "company_name", "public_identifier")
    readonly_fields = ("linkedin_url", "public_identifier", "creation_date", "update_date")
    icon = "users"

    def linkedin_link(self, obj):
        if not obj.linkedin_url:
            return "-"
        return format_html('<a href="{}" target="_blank" class="text-blue-600 hover:underline">Profile &nearr;</a>', obj.linkedin_url)
    linkedin_link.short_description = "LinkedIn URL"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ChatMessageInline(GenericTabularInline):
    model = ChatMessage
    verbose_name = "Message"
    verbose_name_plural = "💬 Conversation History"
    extra = 0
    max_num = 0
    fields = ("content", "is_outgoing", "is_draft", "is_approved", "creation_date")
    readonly_fields = ("content", "is_outgoing", "is_draft", "is_approved", "creation_date")
    can_delete = False
    classes = ["tab", "messaging"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Deal)
class DealAdmin(ModelAdmin):
    list_display = ("lead", "campaign", "state_pill", "connect_attempts", "short_reason", "creation_date")
    list_filter = ("state", "campaign", "closing_reason")
    search_fields = ("lead__first_name", "lead__last_name", "campaign__name")
    readonly_fields = ("lead", "campaign", "creation_date", "update_date", "reason_box", "history_feed")
    icon = "briefcase"
    inlines = [ChatMessageInline]
    
    fieldsets = (
        (_("Current Pipeline Status"), {
            "fields": (("lead", "campaign"), ("state", "closing_reason"), "connect_attempts")
        }),
        (_("AI Reasoning & Qualifications"), {
            "fields": ("reason_box",)
        }),
        (_("Engagement History (Deep Audit)"), {
            "fields": ("history_feed",)
        }),
        (_("Metadata"), {
            "fields": ("creation_date", "update_date"),
            "classes": ("collapse",)
        }),
    )

    def state_pill(self, obj):
        colors = {
            "QUALIFIED": "purple",
            "PENDING": "yellow",
            "CONNECTED": "green",
            "COMPLETED": "blue",
            "FAILED": "red",
        }
        color = colors.get(obj.state, "gray")
        return format_html(
            '<span class="bg-{}-100 text-{}-800 px-3 py-1 rounded-full text-xs font-bold">{}</span>',
            color, color, obj.state
        )
    state_pill.short_description = "Status"
    
    def short_reason(self, obj):
        if not obj.reason:
            return "-"
        return f"{obj.reason[:60]}..." if len(obj.reason) > 60 else obj.reason
    short_reason.short_description = "AI Reasoning"

    def reason_box(self, obj):
        return format_html(
            '<div class="p-4 bg-indigo-50 border-l-4 border-indigo-500 rounded text-sm text-indigo-900">'
            '<strong class="block mb-1 text-indigo-700">AI Qualification Logic:</strong>'
            '{}'
            '</div>', 
            obj.reason or "No reasoning recorded."
        )
    reason_box.short_description = "Qualification Reason"

    def history_feed(self, obj):
        # Pull Tasks for this public_id
        tasks = Task.objects.filter(payload__public_id=obj.lead.public_identifier).order_by("-created_at")
        
        rows = []
        for t in tasks:
            status_color = "bg-green-100 text-green-700" if t.status == "completed" else "bg-red-100 text-red-700" if t.status == "failed" else "bg-gray-100"
            rows.append(format_html(
                '<tr class="border-b border-gray-100">'
                '<td class="py-2 text-xs font-mono">{}</td>'
                '<td class="py-2 text-xs">'
                '<span class="px-2 py-0.5 rounded-full {}">{}</span>'
                '</td>'
                '<td class="py-2 text-xs text-gray-500">{}</td>'
                '<td class="py-2 text-xs italic">{}</td>'
                '</tr>',
                t.task_type.upper(), status_color, t.status, t.created_at.strftime('%Y-%m-%d %H:%M'), t.error or "-"
            ))
        
        if not rows:
            return "No technical activity recorded yet."
            
        return format_html(
            '<table class="w-full text-left border-collapse">'
            '<thead><tr class="text-gray-400 text-[10px] uppercase border-b">'
            '<th class="pb-2">Action</th><th class="pb-2">Status</th><th class="pb-2">Time</th><th class="pb-2">Notes</th>'
            '</tr></thead>'
            '<tbody>{}</tbody>'
            '</table>',
            mark_safe("".join(rows))
        )
    history_feed.short_description = "Technical Interaction Log"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


