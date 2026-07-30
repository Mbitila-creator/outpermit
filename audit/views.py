from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.dateparse import parse_date

from .models import AuditLog


def _is_admin(user):
    if user.is_superuser:
        return True

    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "ADMIN")


@login_required
def audit_log_list(request):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Not allowed.")

    logs = AuditLog.objects.select_related("user").all()

    q = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()
    module = request.GET.get("module", "").strip()
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))

    if q:
        logs = logs.filter(
            Q(user__username__icontains=q) |
            Q(reference_no__icontains=q) |
            Q(description__icontains=q)
        )

    if action:
        logs = logs.filter(action=action)

    if module:
        logs = logs.filter(module__icontains=module)

    if start_date:
        logs = logs.filter(created_at__date__gte=start_date)

    if end_date:
        logs = logs.filter(created_at__date__lte=end_date)

    logs = logs.order_by("-created_at")

    paginator = Paginator(logs, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "audit/audit_log_list.html", {
        "logs": page_obj,
        "page_obj": page_obj,
        "q": q,
        "action": action,
        "module": module,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
        "actions": AuditLog.ACTION_CHOICES,
    })