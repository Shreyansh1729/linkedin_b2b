from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from chat.models import ChatMessage
from crm.models.deal import Deal
from crm.models.lead import Lead
from linkedin.models import ActionLog, Task


from simple_history.admin import SimpleHistoryAdmin
from import_export.admin import ImportExportModelAdmin

@admin.register(Lead)
class LeadAdmin(ImportExportModelAdmin, SimpleHistoryAdmin, ModelAdmin):
    list_display = ("full_name", "company_name_status", "linkedin_link", "current_status", "creation_date")
    list_filter = ("disqualified", "company_name")
    search_fields = ("first_name", "last_name", "company_name", "public_identifier")
    readonly_fields = ("linkedin_url", "public_identifier", "creation_date", "update_date", "profile_summary", "deal_navigation")
    icon = "users"

    # (Removed duplicate company_name_status)

    def deal_navigation(self, obj):
        deals = list(obj.deal_set.all())
        deal = deals[0] if deals else None
        if not deal:
            return "No active deal for this lead."
        from django.urls import reverse
        url = reverse("admin:crm_deal_change", args=[deal.pk])
        return format_html(
            '<a href="{}" class="bg-indigo-50 text-indigo-700 px-4 py-2 rounded-md border border-indigo-200 font-bold hover:bg-indigo-100 transition-colors">'
            'View Active Deal Pipeline &rarr;</a>',
            url
        )
    deal_navigation.short_description = "Pipeline Shortcuts"

    def current_status(self, obj):
        deals = list(obj.deal_set.all())
        deal = deals[0] if deals else None
        if not deal:
            return format_html('<span class="text-gray-400">UNQUALIFIED</span>')
        
        from linkedin.enums import ProfileState
        class_map = {
            ProfileState.QUALIFIED: "border-info-600 bg-info-50 text-info-700",
            ProfileState.PENDING: "border-warning-600 bg-warning-50 text-warning-700",
            ProfileState.CONNECTED: "border-success-600 bg-success-50 text-success-700",
            ProfileState.COMPLETED: "border-primary-600 bg-primary-50 text-primary-700",
            ProfileState.FAILED: "border-danger-600 bg-danger-50 text-danger-700",
        }
        classes = class_map.get(deal.state, "border-gray-600 bg-gray-50 text-gray-700")
        return format_html(
            '<span class="font-bold border px-2 py-0.5 rounded-md uppercase text-[10px] {}">{}</span>',
            classes, deal.state
        )

    current_status.short_description = "Status"

    def profile_summary(self, obj):
        if not obj.profile_data:
            return "No profile data available."
        
        p = obj.profile_data
        return format_html(
            '<div class="grid grid-cols-2 gap-4 p-4 bg-gray-50 rounded-lg border border-gray-200">'
            '<div><strong class="text-gray-500 uppercase text-[10px] block">Headline</strong>{}</div>'
            '<div><strong class="text-gray-500 uppercase text-[10px] block">Location</strong>{}</div>'
            '<div class="col-span-2"><strong class="text-gray-500 uppercase text-[10px] block">Summary</strong>'
            '<div class="text-sm mt-1">{}</div></div>'
            '</div>',
            p.get("headline", "-"), p.get("location_name", "-"), p.get("summary", "No summary provided.")
        )
    profile_summary.short_description = "Profile Intelligence"

    def linkedin_link(self, obj):

        if not obj.linkedin_url:
            return "-"
        return format_html('<a href="{}" target="_blank" class="text-blue-600 hover:underline">Profile &nearr;</a>', obj.linkedin_url)
    linkedin_link.short_description = "LinkedIn URL"

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        from django.db.models import Count, OuterRef, Subquery
        
        # Optimized: Thread-safe annotation instead of storing on 'self'
        lead_counts = Lead.objects.filter(
            company_name=OuterRef("company_name")
        ).values("company_name").annotate(c=Count("id")).values("c")

        return super().get_queryset(request).prefetch_related("deal_set").annotate(
            company_count=Subquery(lead_counts)
        )

    def company_name_status(self, obj):
        if not obj.company_name:
            return "-"
        
        if getattr(obj, "company_count", 0) > 1:
            return format_html(
                '<span class="flex items-center gap-1">{} <span title="Possible duplicate company" class="text-amber-500 font-bold">⚠️</span></span>',
                obj.company_name
            )
        return obj.company_name
    company_name_status.short_description = "Company"


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
class DealAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("lead", "campaign", "state_pill", "connect_attempts", "short_reason", "creation_date")
    list_filter = ("state", "campaign", "closing_reason")
    search_fields = ("lead__first_name", "lead__last_name", "campaign__name")
    readonly_fields = ("lead", "campaign", "creation_date", "update_date", "reason_box", "history_feed")
    icon = "briefcase"
    inlines = [ChatMessageInline]
    actions = ["requeue_deal", "force_requalify"]

    @admin.action(description="Re-queue Deal (Reset to QUALIFIED)")
    def requeue_deal(self, request, queryset):
        from linkedin.enums import ProfileState
        count = 0
        for deal in queryset:
            deal.state = ProfileState.QUALIFIED
            deal.closing_reason = ""
            deal.connect_attempts = 0
            deal.save(update_fields=["state", "closing_reason", "connect_attempts"])
            count += 1
        self.message_user(request, f"Successfully re-queued {count} deal(s).")

    @admin.action(description="Force Re-qualify (Reset FAILED lead)")
    def force_requalify(self, request, queryset):
        from linkedin.enums import ProfileState
        count = 0
        for deal in queryset.filter(state=ProfileState.FAILED):
            deal.state = ProfileState.QUALIFIED
            deal.closing_reason = ""
            deal.save(update_fields=["state", "closing_reason"])
            count += 1
        self.message_user(request, f"Successfully force-requalified {count} deal(s).")

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
        from linkedin.enums import ProfileState
        class_map = {
            ProfileState.QUALIFIED: "border-info-600 bg-info-50 text-info-700",
            ProfileState.PENDING: "border-warning-600 bg-warning-50 text-warning-700",
            ProfileState.CONNECTED: "border-success-600 bg-success-50 text-success-700",
            ProfileState.COMPLETED: "border-primary-600 bg-primary-50 text-primary-700",
            ProfileState.FAILED: "border-danger-600 bg-danger-50 text-danger-700",
        }
        classes = class_map.get(obj.state, "border-gray-600 bg-gray-50 text-gray-700")
        return format_html(
            '<span class="font-bold border px-2 py-0.5 rounded-md uppercase text-[10px] {}">{}</span>',
            classes, obj.state
        )

    state_pill.short_description = "Status"

    
    def short_reason(self, obj):
        if not obj.reason:
            return "-"
        return f"{obj.reason[:60]}..." if len(obj.reason) > 60 else obj.reason
    short_reason.short_description = "Qualification Reason"

    def reason_box(self, obj):
        return format_html(
            '<div class="p-4 bg-indigo-50 border-l-4 border-indigo-500 rounded text-sm text-indigo-900">'
            '<strong class="block mb-1 text-indigo-700">Qualification Logic:</strong>'
            '{}'
            '</div>', 
            obj.reason or "No reasoning recorded."
        )
    reason_box.short_description = "Qualification Reason"

    def history_feed(self, obj):
        from linkedin.models import Task
        from django.utils.html import format_html_join
        
        tasks = Task.objects.filter(deal=obj).order_by("-created_at")[:20]
        if not tasks.exists():
            return "No technical activity recorded yet."

        def get_row(t):
            status_colors = {
                "completed": "bg-green-100 text-green-700",
                "failed": "bg-red-100 text-red-700",
                "running": "bg-amber-100 text-amber-700",
                "skipped": "bg-indigo-100 text-indigo-700",
            }
            color = status_colors.get(t.status, "bg-gray-100 text-gray-700")
            return (
                t.task_type.upper(), 
                color, 
                t.status, 
                t.created_at.strftime('%Y-%m-%d %H:%M'), 
                t.error or "-"
            )

        rows_html = format_html_join(
            "\n",
            '<tr class="border-b border-gray-100">'
            '<td class="py-2 text-xs font-mono">{}</td>'
            '<td class="py-2 text-xs">'
            '<span class="px-2 py-0.5 rounded-full {}">{}</span>'
            '</td>'
            '<td class="py-2 text-xs text-gray-500">{}</td>'
            '<td class="py-2 text-xs italic">{}</td>'
            '</tr>',
            (get_row(t) for t in tasks)
        )
            
        return format_html(
            '<table class="w-full text-left border-collapse">'
            '<thead><tr class="text-gray-400 text-[10px] uppercase border-b">'
            '<th class="pb-2">Action</th><th class="pb-2">Status</th><th class="pb-2">Time</th><th class="pb-2">Notes</th>'
            '</tr></thead>'
            '<tbody>{}</tbody>'
            '</table>',
            rows_html
        )
    history_feed.short_description = "Technical Interaction Log"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("lead", "campaign")


