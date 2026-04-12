from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from linkedin.models import Campaign, LinkedInProfile, Task, ActionLog
from crm.models.lead import Lead

def dashboard_callback(request, context):
    """
    Enhanced LeadPilot Dashboard Callback.
    Returns structured data for the Unfold Dashboard.
    """
    from django.db.models import Count, Q
    from crm.models.deal import Deal
    
    from django.utils import timezone
    from linkedin.enums import ProfileState
    
    # [LOW-04] Three separate queries: Lead count, Deal aggregates, ActionLog aggregates.
    # These are distinct tables with no join relationship; batching isn't possible.
    total_leads = Lead.objects.count()
    
    # Batch Deal stats in 1 query
    deal_stats = Deal.objects.aggregate(
        total=Count("id"),
        connected=Count("id", filter=Q(state=ProfileState.CONNECTED)),
        failed=Count("id", filter=Q(state=ProfileState.FAILED)),
        pending=Count("id", filter=Q(state=ProfileState.PENDING)),
        completed=Count("id", filter=Q(state=ProfileState.COMPLETED)),
    )
    
    # Batch ActionLog stats in 1 query
    action_stats = ActionLog.objects.aggregate(
        today=Count("id", filter=Q(created_at__date=today)),
        week=Count("id", filter=Q(created_at__gte=last_week)),
    )
    
    total_pipeline = deal_stats["total"]
    connected = deal_stats["connected"]
    failed = deal_stats["failed"]
    pending = deal_stats["pending"]
    completed = deal_stats["completed"]
    actions_today = action_stats["today"]

    acceptance_rate = (connected / (connected + pending + failed) * 100) if (connected + pending + failed) > 0 else 0
    conversion_rate = (completed / total_pipeline * 100) if total_pipeline > 0 else 0

    active_profile = LinkedInProfile.objects.filter(active=True).first()

    context.update({
        "greeting": "LeadPilot Console",
        "tagline": "Autonomous B2B Lead Generation Active",
        "kpi": [
            {
                "title": "Total Leads",
                "metric": str(total_leads),
                "icon": "users",
                "color": "info",
            },
            {
                "title": "Acceptance Rate",
                "metric": f"{acceptance_rate:.1f}%",
                "icon": "user_check",
                "color": "success" if acceptance_rate > 30 else "warning",
            },
            {
                "title": "Actions Today",
                "metric": str(actions_today),
                "icon": "activity",
                "color": "indigo",
            },
            {
                "title": "Conversion",
                "metric": f"{conversion_rate:.1f}%",
                "icon": "trending_up",
                "color": "primary",
            },
        ],
        "profile_status": "🟢 CONNECTED" if (active_profile and active_profile.cookie_data) else "🔴 DISCONNECTED",
    })

    return context
