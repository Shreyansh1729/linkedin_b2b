# linkedin/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponseRedirect, HttpResponse

from unfold.admin import ModelAdmin

from linkedin.models import ActionLog, Campaign, LinkedInProfile, SearchKeyword, SiteConfig, Task
from chat.models import ChatMessage
from django.contrib.auth.models import User, Group

admin.site.unregister(User)
admin.site.unregister(Group)

@admin.register(SiteConfig)
class SiteConfigAdmin(ModelAdmin):
    list_display = ("ai_model", "llm_api_key_status", "llm_api_base")
    icon = "settings"
    
    def llm_api_key_status(self, obj):
        return "Configured" if obj.llm_api_key else "Missing"
    llm_api_key_status.short_description = "API Key"

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()

@admin.register(Campaign)
class CampaignAdmin(ModelAdmin):
    list_display = ("name", "discovered_count", "credits_used", "connected_count", "failed_count")
    list_filter = ("is_freemium",)
    search_fields = ("name",)
    icon = "send"
    
    fieldsets = (
        (_("Campaign Configuration"), {
            "fields": (("name", "is_freemium"), ("booking_link", "action_fraction"))
        }),
        (_("Targeting Intelligence"), {
            "fields": ("product_docs", "campaign_objective")
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.users.add(request.user)

    def discovered_count(self, obj):
        return obj.deals.count()
    discovered_count.short_description = _("Discovered")

    def credits_used(self, obj):
        return obj.action_logs.count()
    credits_used.short_description = _("Credits (Sent)")

    def connected_count(self, obj):
        return obj.deals.filter(state="CONNECTED").count()
    connected_count.short_description = _("Connected")

    def failed_count(self, obj):
        return obj.deals.filter(state="FAILED").count()
    failed_count.short_description = _("Failed")

    actions = ["import_leads_action"]

    @admin.action(description="Import Leads from CSV")
    def import_leads_action(self, request, queryset):
        if request.method == "POST" and "csv_file" in request.FILES:
            from linkedin.setup.seeds import parse_seed_csv, create_seed_leads
            public_ids, skipped = parse_seed_csv(request.FILES["csv_file"].read())
            
            if not public_ids:
                self.message_user(request, "No valid LinkedIn URLs found in the uploaded file.", level="WARNING")
                return HttpResponseRedirect(request.get_full_path())

            for campaign in queryset:
                create_seed_leads(campaign, public_ids)
                
            self.message_user(request, f"Successfully imported {len(public_ids)} leads for {queryset.count()} campaign(s).")
            return HttpResponseRedirect(request.get_full_path())

        # Render a simple form
        form_html = """
        <form method="post" enctype="multipart/form-data" style="margin: 20px; font-family: sans-serif;">
            <h2>Upload a CSV file with LinkedIn URLs</h2>
            <p>We will scan every column for LinkedIn Profile URLs.</p>
            <input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
            <input type="hidden" name="action" value="import_leads_action">
            {selected}
            <div style="margin: 20px 0;">
                <input type="file" name="csv_file" accept=".csv" required>
            </div>
            <button type="submit" style="padding: 10px 20px; background: #4f46e5; color: white; border: none; border-radius: 5px; cursor: pointer;">Upload and Import</button>
        </form>
        """
        
        from django.middleware.csrf import get_token
        csrf = get_token(request)
        selected_inputs = "".join(f'<input type="hidden" name="{admin.ACTION_CHECKBOX_NAME}" value="{obj.pk}">' for obj in queryset)
        
        return HttpResponse(form_html.format(csrf=csrf, selected=selected_inputs))


@admin.register(LinkedInProfile)
class LinkedInProfileAdmin(ModelAdmin):
    list_display = ("user", "linkedin_username", "active", "legal_accepted")
    list_filter = ("active", "legal_accepted")
    icon = "user_check"
    
    fieldsets = (
        (_("Account Authentication"), {
            "fields": ("user", "linkedin_username", "linkedin_password", "active")
        }),
        (_("Throttling and Limits"), {
            "fields": (("connect_daily_limit", "connect_weekly_limit"), "follow_up_daily_limit")
        }),
        (_("Compliance Status"), {
            "fields": ("legal_accepted", "subscribe_newsletter")
        }),
    )

@admin.register(SearchKeyword)
class SearchKeywordAdmin(ModelAdmin):
    list_display = ("keyword", "campaign", "used", "used_at")
    list_filter = ("used", "campaign")
    raw_id_fields = ("campaign",)
    icon = "search"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(ActionLog)
class ActionLogAdmin(ModelAdmin):
    list_display = ("action_type", "target_info", "status_pill", "note_preview", "created_at")
    list_filter = ("action_type", "status", "campaign")
    readonly_fields = ("linkedin_profile", "campaign", "action_type", "target_name", "target_public_id", "status", "note", "created_at")
    date_hierarchy = "created_at"
    icon = "activity"

    def target_info(self, obj):
        if not obj.target_public_id:
            return "-"
        from linkedin.url_utils import public_id_to_url
        url = public_id_to_url(obj.target_public_id)
        return format_html(
            '<div class="flex flex-col">'
            '<strong>{}</strong>'
            '<a href="{}" target="_blank" class="text-xs text-blue-600 hover:underline">Profile &nearr;</a>'
            '</div>',
            obj.target_name or obj.target_public_id, url
        )
    target_info.short_description = "Target Prospect"

    def status_pill(self, obj):
        color = "bg-green-100 text-green-700" if obj.status == "success" else "bg-red-100 text-red-700"
        return format_html(
            '<span class="{} px-2 py-0.5 rounded-full text-[10px] font-bold uppercase">{}</span>',
            color, obj.status
        )
    status_pill.short_description = "Status"

    def note_preview(self, obj):
        if not obj.note:
            return "-"
        return obj.note[:50] + "..." if len(obj.note) > 50 else obj.note
    note_preview.short_description = "Note/Snippet"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Task)
class TaskAdmin(ModelAdmin):
    list_display = ("task_type", "target_info", "status_pill", "error_preview", "scheduled_at")
    list_filter = ("task_type", "status")
    readonly_fields = (
        "task_type", "status", "scheduled_at", "payload", "error",
        "created_at", "started_at", "completed_at",
    )
    icon = "clipboard_list"
    
    def status_pill(self, obj):
        colors = {"pending": "gray", "running": "blue", "completed": "green", "failed": "red"}
        color_class = f"bg-{colors.get(obj.status, 'gray')}-100 text-{colors.get(obj.status, 'gray')}-800"
        return format_html('<span class="{} px-3 py-1 rounded-full text-xs font-bold">{}</span>', color_class, obj.status.upper())
    status_pill.short_description = "Status"
    
    def target_info(self, obj):
        from crm.models import Lead
        public_id = obj.payload.get("public_id")
        if not public_id:
            return "-"
        
        lead = Lead.objects.filter(public_identifier=public_id).first()
        name = f"{lead.first_name} {lead.last_name}" if lead and (lead.first_name or lead.last_name) else public_id
        url = lead.linkedin_url if lead else f"https://www.linkedin.com/in/{public_id}/"
        
        return format_html(
            '<div class="flex flex-col">'
            '<span class="font-bold text-gray-900">{}</span>'
            '<a href="{}" target="_blank" class="text-xs text-blue-600 hover:underline">{} &nearr;</a>'
            '</div>',
            name, url, public_id
        )
    target_info.short_description = "Prospect Identity"

    def error_preview(self, obj):
        if not obj.error:
            return "-"
        return format_html('<span class="text-red-600 text-xs truncate max-w-xs block" title="{}">{}</span>', obj.error, obj.error[:50] + '...' if len(obj.error) > 50 else obj.error)
    error_preview.short_description = "Error Log"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(ChatMessage)
class ChatMessageAdmin(ModelAdmin):
    list_display = ("display_content", "owner", "is_outgoing", "is_draft", "is_approved", "creation_date")
    list_filter = ("is_draft", "is_approved", "is_outgoing", "owner")
    readonly_fields = ("content_type", "object_id", "content", "owner", "creation_date", "linkedin_urn")
    icon = "message_square"
    actions = ["approve_and_send"]

    @admin.action(description="Approve and Send Message(s)")
    def approve_and_send(self, request, queryset):
        from linkedin.models import Task
        from django.utils import timezone
        
        drafts = queryset.filter(is_draft=True)
        count = 0
        for draft in drafts:
            draft.is_approved = True
            draft.is_draft = False
            draft.save(update_fields=["is_approved", "is_draft"])
            
            public_id = None
            campaign_id = None
            
            obj = draft.content_object
            if obj and obj.__class__.__name__ == "Deal":
                public_id = obj.lead.public_identifier
                campaign_id = obj.campaign.pk
            elif obj and obj.__class__.__name__ == "Lead":
                public_id = obj.public_identifier
                deal = obj.deal_set.first()
                if deal:
                    campaign_id = deal.campaign.pk

            if public_id and campaign_id:
                Task.objects.create(
                    task_type="send_message",
                    status="pending",
                    scheduled_at=timezone.now(),
                    payload={
                        "message_id": draft.pk,
                        "public_id": public_id,
                        "campaign_id": campaign_id
                    }
                )
                count += 1
        
        self.message_user(request, f"Successfully approved {count} messages. Background tasks queued for dispatch.")

    def display_content(self, obj):
        if obj.is_draft:
            color = "bg-purple-50 text-purple-700 border border-purple-200"
            label = "AI DRAFT - NEEDS APPROVAL"
        else:
            color = "bg-green-50 text-green-700" if obj.is_outgoing else "bg-gray-100 text-gray-700"
            label = "OUTGOING" if obj.is_outgoing else "INCOMING"
        
        return format_html(
            '<div class="flex flex-col gap-1 p-2 rounded-lg {} max-w-sm">'
            '<span class="text-[10px] font-bold uppercase">{}</span>'
            '<span class="text-sm">{}</span>'
            '</div>',
            color, label, obj.content
        )
    display_content.short_description = _("Message")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
