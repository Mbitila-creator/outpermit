import io
import os
import openpyxl
from functools import wraps
from xml.sax.saxutils import escape
from system_admin.models import SystemSetting
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db.models import Q, Count, Avg, F, ExpressionWrapper, DurationField
from django.http import HttpResponse, HttpResponseForbidden, FileResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4, A6, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from core.workflow import get_first_approver_for_requester, get_director_for_department
from core.notifications import notify_user
from core.audit import log_action
from forms_builder.services import generate_qr_png

from .models import Department, ExternalWorkRequest, UserProfile, GroupMember, ModuleRoleAssignment
from .module_roles import set_module_roles
from .forms import (
    LoginForm,
    ExternalWorkRequestForm,
    GroupMemberFormSet,
    ReportUploadForm,
    DirectorDecisionForm,
    AdminUserCreateForm,
    AdminUserUpdateForm,
    AdminPasswordResetForm,
    UserPasswordChangeForm,
)


TANZANIA_TIMEZONE = ZoneInfo(
    "Africa/Dar_es_Salaam"
)


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------

def _get_profile(user):
    profile, created = UserProfile.objects.get_or_create(
        user=user
    )
    return profile


def _get_user_role(user):
    """
    Return one standardized role code for Permit permissions.

    Standard output values:
    - ADMIN
    - DIRECTOR
    - ASSISTANT_DIRECTOR
    - HEAD_OF_UNIT
    - DIVISION_BUDGET_OFFICER
    - ACCOUNTANT
    - REQUESTER
    - STAFF
    """
    if user.is_superuser:
        return "ADMIN"

    profile = _get_profile(user)

    approval_role = getattr(
        profile,
        "approval_role",
        None,
    )

    approval_role_code = getattr(
        approval_role,
        "code",
        None,
    )

    if approval_role_code:
        role_code = (
            approval_role_code
            .strip()
            .upper()
        )

        if role_code == "SYSTEM_ADMIN":
            return "ADMIN"

        return role_code

    legacy_role = getattr(
        profile,
        "role",
        None,
    )

    if legacy_role:
        role_code = legacy_role.strip().upper()

        if role_code == "SYSTEM_ADMIN":
            return "ADMIN"

        return role_code

    groups = {
        group_name.strip().upper()
        for group_name in user.groups.values_list(
            "name",
            flat=True,
        )
        if group_name
    }

    group_priority = [
        "SYSTEM_ADMIN",
        "ADMIN",
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
        "HEAD_OF_UNIT",
        "DIVISION_BUDGET_OFFICER",
        "ACCOUNTANT",
        "REQUESTER",
    ]

    for group_name in group_priority:
        if group_name in groups:
            if group_name == "SYSTEM_ADMIN":
                return "ADMIN"

            return group_name

    return "STAFF"


def _requester_org_context(profile):
    department = getattr(
        profile,
        "department",
        None,
    )

    department_unit = getattr(
        profile,
        "department_unit",
        None,
    )

    return {
        "requester_department": department,
        "requester_department_unit": department_unit,
        "requester_department_has_units": bool(
            department
            and department.has_units
        ),
    }


def _get_approval_role_from_role_code(role_code):
    """
    Return an ApprovalRole using the standardized role code.
    """
    from .models import ApprovalRole

    normalized_role = (
        role_code or ""
    ).strip().upper()

    role_map = {
        "REQUESTER": "REQUESTER",
        "ADMIN": "SYSTEM_ADMIN",
        "SYSTEM_ADMIN": "SYSTEM_ADMIN",
        "DIRECTOR": "DIRECTOR",
        "ASSISTANT_DIRECTOR": "ASSISTANT_DIRECTOR",
        "HEAD_OF_UNIT": "HEAD_OF_UNIT",
        "DIVISION_BUDGET_OFFICER": (
            "DIVISION_BUDGET_OFFICER"
        ),
        "ACCOUNTANT": "ACCOUNTANT",
    }

    target_code = role_map.get(
        normalized_role
    )

    if not target_code:
        return None

    return ApprovalRole.objects.filter(
        code=target_code,
        is_active=True,
    ).first()


def _admin_allowed(user):
    return _get_user_role(user) == "ADMIN"


def _director_allowed(user):
    return _get_user_role(user) == "DIRECTOR"


def _assistant_director_allowed(user):
    return (
        _get_user_role(user)
        == "ASSISTANT_DIRECTOR"
    )


def _director_level_allowed(user):
    """
    Director-level access includes the Director and Assistant Director.

    This helper is for viewing, reviewing, and department-level access.
    It must not be used where final Director approval is required.
    """
    return _get_user_role(user) in [
        "ADMIN",
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]


def _director_scope_queryset(user, qs):
    """
    Limit Director and Assistant Director request lists to their own
    department.

    System Administrators may see requests from all departments.
    """
    profile = _get_profile(user)
    role = _get_user_role(user)

    if role == "ADMIN":
        return qs

    if role not in [
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]:
        return qs.none()

    if not profile.department_id:
        return qs.none()

    qs = qs.filter(
        requester__profile__department_id=(
            profile.department_id
        )
    )

    # A unit-assigned Assistant Director must never receive
    # department-wide visibility. Department-wide Assistant Directors
    # have department_unit=None and retain department visibility.
    if (
        role == "ASSISTANT_DIRECTOR"
        and profile.department_unit_id
    ):
        unit_values = {
            str(profile.department_unit.code or "").strip(),
            str(profile.department_unit.name or "").strip(),
            str(profile.unit_name or "").strip(),
        }
        unit_values.discard("")

        qs = qs.filter(
            Q(
                requester__profile__department_unit_id=(
                    profile.department_unit_id
                )
            )
            | Q(
                requester__profile__department_unit__isnull=True,
                requester__profile__unit_name__in=unit_values,
            )
        )

    return qs


def _director_can_access_request(user, req):
    """
    Prevent a Director or Assistant Director from opening a request
    belonging to another department by changing the URL.
    """
    profile = _get_profile(user)
    role = _get_user_role(user)

    if role == "ADMIN":
        return True

    if role not in [
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]:
        return False

    requester_profile = getattr(
        req.requester,
        "profile",
        None,
    )

    if (
        not profile.department_id
        or not requester_profile
        or not requester_profile.department_id
    ):
        return False

    if (
        requester_profile.department_id
        != profile.department_id
    ):
        return False

    if (
        role == "ASSISTANT_DIRECTOR"
        and profile.department_unit_id
    ):
        if (
            requester_profile.department_unit_id
            == profile.department_unit_id
        ):
            return True

        allowed_unit_values = {
            str(profile.department_unit.code or "").strip().lower(),
            str(profile.department_unit.name or "").strip().lower(),
            str(profile.unit_name or "").strip().lower(),
        }
        allowed_unit_values.discard("")

        requester_unit_name = str(
            requester_profile.unit_name or ""
        ).strip().lower()

        return requester_unit_name in allowed_unit_values

    return True


def _head_of_unit_allowed(user):
    return (
        _get_user_role(user)
        == "HEAD_OF_UNIT"
    )


def _head_of_unit_scope_queryset(user, qs):
    """
    Restrict HOU access to requests from the HOU's exact department
    and unit, even if an older permit contains a stale head_of_unit FK.
    """
    profile = _get_profile(user)

    if user.is_superuser:
        return qs.filter(head_of_unit=user)

    if (
        _get_user_role(user) != "HEAD_OF_UNIT"
        or not profile.department_id
    ):
        return qs.none()

    qs = qs.filter(
        head_of_unit=user,
        requester__profile__department_id=(
            profile.department_id
        ),
    )

    if profile.department_unit_id:
        unit_values = {
            str(profile.department_unit.code or "").strip(),
            str(profile.department_unit.name or "").strip(),
            str(profile.unit_name or "").strip(),
        }
        unit_values.discard("")

        qs = qs.filter(
            Q(
                requester__profile__department_unit_id=(
                    profile.department_unit_id
                )
            )
            | Q(
                requester__profile__department_unit__isnull=True,
                requester__profile__unit_name__in=unit_values,
            )
        )

    return qs


def _division_budget_officer_allowed(user):
    return (
        _get_user_role(user)
        == "DIVISION_BUDGET_OFFICER"
    )


def _accountant_allowed(user):
    return (
        _get_user_role(user)
        == "ACCOUNTANT"
    )


def _returned_statuses():
    return ["RETURNED_HOU", "RETURNED_DIRECTOR"]


def _rejected_statuses():
    return ["REJECTED_HOU", "REJECTED_DIRECTOR"]


def _final_statuses():
    return ["APPROVED", "CLOSED"]


def _open_statuses():
    return [
        "PENDING_HOU",
        "PENDING_DIRECTOR",
        "RETURNED_HOU",
        "RETURNED_DIRECTOR",
        "APPROVED",
    ]


def _blocking_statuses():
    """
    These statuses block a user from creating another request.
    APPROVED is included so a permit must be closed first.
    """
    return [
        "PENDING_HOU",
        "PENDING_DIRECTOR",
        "RETURNED_HOU",
        "RETURNED_DIRECTOR",
        "APPROVED",
    ]


def _is_total_status(status):
    return status in [None, "", "ALL", "TOTAL", "TOTAL_REQUESTS"]


def _is_view_only_status(status):
    return status in _final_statuses()


def _resolve_display_status(req, context="detail"):
    raw_status = getattr(req, "raw_status", None) or getattr(req, "status", "")

    if context == "requester_list":
        if raw_status in ["PENDING_HOU", "PENDING_DIRECTOR"]:
            return "Submitted"
        if raw_status in ["RETURNED_HOU", "RETURNED_DIRECTOR"]:
            return "Returned"
        if raw_status in ["REJECTED_HOU", "REJECTED_DIRECTOR"]:
            return "Rejected"
        if raw_status == "APPROVED":
            return "Approved"
        if raw_status == "CLOSED":
            return "Closed"
        return req.get_status_display()

    if context == "list":
        if raw_status in ["PENDING_HOU", "PENDING_DIRECTOR"]:
            return "Submitted"
        if raw_status in ["RETURNED_HOU", "RETURNED_DIRECTOR"]:
            return "Returned"
        if raw_status in ["REJECTED_HOU", "REJECTED_DIRECTOR"]:
            return "Rejected"
        if raw_status == "APPROVED":
            return "Approved"
        if raw_status == "CLOSED":
            return "Closed"
        return req.get_status_display()

    if raw_status == "PENDING_HOU":
        return "Under Head of Unit Review"

    if raw_status == "PENDING_DIRECTOR":
        assigned_approver = getattr(req, "director", None)

        if (
            assigned_approver
            and _get_user_role(assigned_approver)
            == "ASSISTANT_DIRECTOR"
        ):
            return "Under Assistant Director Review"

        return "Under Director Review"

    if raw_status == "RETURNED_HOU":
        return "Returned by Head of Unit"

    if raw_status == "RETURNED_DIRECTOR":
        return "Returned by Director"

    return req.get_status_display()


def _attach_display_status(req, context="detail"):
    """
    Keeps the raw DB status intact while exposing display helpers.
    """
    raw_status = getattr(req, "status", "")
    label = _resolve_display_status(req, context=context)
    req.raw_status = raw_status
    req.display_status = label
    req.status_label = label
    req.is_view_only = _is_view_only_status(raw_status)
    req.is_finalized = _is_view_only_status(raw_status)
    req.can_upload_report = raw_status == "APPROVED"
    req.has_summary_report = bool(getattr(req, "report_file", None))
    return req


def _attach_display_status_list(items, context="list"):
    prepared = list(items)
    now = timezone.now()

    for item in prepared:
        _attach_display_status(item, context=context)
        item.is_overdue = (
            getattr(item, "end_time", now) < now
            and item.raw_status not in (["CLOSED"] + _rejected_statuses())
        )
    return prepared


def _normalize_action(action):
    return (action or "").strip().lower()


def _validate_director_action_value(action):
    """
    Strict whitelist for the hidden director action field.
    Returns the normalized action or raises PermissionDenied.
    """
    normalized = _normalize_action(action)
    valid_actions = ["approve", "reject", "return"]
    if normalized not in valid_actions:
        raise PermissionDenied("Invalid action attempted.")
    return normalized


def _to_tanzania_datetime(value):
    """Return a datetime explicitly converted to Tanzania time."""
    if not value:
        return None

    if timezone.is_naive(value):
        return timezone.make_aware(
            value,
            TANZANIA_TIMEZONE,
        )

    return value.astimezone(
        TANZANIA_TIMEZONE
    )


def _format_local_datetime(
    value,
    empty_value="",
):
    """Format a Tanzania datetime consistently using a 24-hour clock."""
    local_value = _to_tanzania_datetime(
        value
    )

    if not local_value:
        return empty_value

    return local_value.strftime(
        "%d %b %Y %H:%M"
    )


def _format_dt(value):
    """Compatibility formatter used by existing Permit functions."""
    return _format_local_datetime(
        value,
        empty_value="N/A",
    )


def _get_blocking_request_for_user(user, exclude_pk=None):
    """
    Returns the newest request that should block a new submission.

    CROSS-ROLE BLOCKING: A user is blocked if they are involved in ANY
    active/pending/unclosed permit as:
      - The requester (who submitted the request)
      - The group leader (named on a group permit)
      - A group member (listed in GroupMember table)
    """
    blocking = _blocking_statuses()

    # CROSS-ROLE BLOCKING: Check all three roles the user could occupy
    qs = ExternalWorkRequest.objects.filter(
        Q(requester=user, status__in=blocking) |
        Q(group_leader=user, status__in=blocking) |
        Q(members__member_user=user, status__in=blocking)
    ).distinct()

    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    return qs.order_by("-updated_at", "-created_at").first()


# CROSS-ROLE BLOCKING: New helper to check blocking for a specific member user
def _get_blocking_request_for_member(member_user, exclude_pk=None):
    """
    Check if a specific User is already involved in an active/pending/unclosed
    permit — as requester, group leader, or group member.
    Returns the blocking request or None.
    """
    blocking = _blocking_statuses()

    qs = ExternalWorkRequest.objects.filter(
        Q(requester=member_user, status__in=blocking) |
        Q(group_leader=member_user, status__in=blocking) |
        Q(members__member_user=member_user, status__in=blocking)
    ).distinct()

    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    return qs.order_by("-updated_at", "-created_at").first()


# CROSS-ROLE BLOCKING: Updated to accept optional person_name parameter
def _build_blocking_request_message(req, person_name=None):
    now = timezone.now()
    reference_no = req.reference_no or "Unknown"
    status_label = _resolve_display_status(req, context="detail")

    # Build the subject prefix
    if person_name:
        subject = f"{person_name} cannot be included in a new request"
    else:
        subject = "You cannot submit a new request"

    if req.status == "APPROVED":
        if req.end_time and req.end_time < now:
            return (
                f"{subject} because permit {reference_no} "
                f"was completed on {_format_dt(req.end_time)} but is not yet closed. "
                f"Please upload the summary report and close it first."
            )
        return (
            f"{subject} because permit {reference_no} is already approved "
            f"and still active. It must be completed and closed first."
        )

    if req.status in ["PENDING_HOU", "PENDING_DIRECTOR"]:
        return (
            f"{subject} because request {reference_no} is still in progress "
            f"({status_label})."
        )

    if req.status in _returned_statuses():
        return (
            f"{subject} because request {reference_no} was returned and still "
            f"needs action. Please edit, re-submit, or delete it first."
        )

    return (
        f"{subject} because request {reference_no} is still open "
        f"({status_label})."
    )


def _add_qr_line(lines, label, value):
    value = str(value).strip() if value is not None else ""
    if value:
        lines.append(f"{label}: {value}")


def _format_role_label(user):
    if not user:
        return ""
    return _get_profile(user).role.replace("_", " ")


def _wrap_text_for_width(text, font_name, font_size, max_width):
    text = str(text or "").strip()
    if not text:
        return [""]

    paragraphs = text.split("\n")
    all_lines = []

    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            all_lines.append("")
            continue

        current_line = words[0]

        for word in words[1:]:
            test_line = f"{current_line} {word}"
            if stringWidth(test_line, font_name, font_size) <= max_width:
                current_line = test_line
            else:
                all_lines.append(current_line)
                current_line = word

        all_lines.append(current_line)

    return all_lines


def _measure_wrapped_block(text, font_name, font_size, max_width, line_height):
    lines = _wrap_text_for_width(text, font_name, font_size, max_width)
    return len(lines) * line_height, lines


def _select_pdf_layout(blocks, font_name, max_width, available_height):
    """
    Select a body font size and line height that fits into available height.
    """
    candidates = [
        (8.5, 10),
        (8.0, 9),
        (7.5, 8.5),
        (7.0, 8),
        (6.5, 7.5),
    ]

    for font_size, line_height in candidates:
        total_height = 0
        for block in blocks:
            measure_text = block.get("measure_text", block["text"])
            block_height, _ = _measure_wrapped_block(
                measure_text,
                font_name,
                font_size,
                max_width,
                line_height
            )
            total_height += block_height

        if total_height <= available_height:
            return font_size, line_height

    return candidates[-1]


def _escape_pdf_value(value):
    return escape(str(value or "")).replace("\n", "<br/>")


def _build_pdf_field(label, value):
    return f"<b>{escape(label)}:</b> {_escape_pdf_value(value)}"


def _draw_paragraph_block(
    p,
    text,
    x,
    y,
    max_width,
    font_name="Helvetica",
    font_size=8.0,
    leading=9,
    justify=False,
    space_after=1
):
    """
    Draw a paragraph block using platypus Paragraph.
    This gives true justification in PDF output.
    Returns the next y position.
    """
    style = ParagraphStyle(
        name="PermitParagraph",
        fontName=font_name,
        fontSize=font_size,
        leading=leading,
        alignment=TA_JUSTIFY if justify else TA_LEFT,
        spaceBefore=0,
        spaceAfter=0,
        allowWidows=1,
        allowOrphans=1,
        splitLongWords=True,
    )

    para = Paragraph(text, style)
    para_width, para_height = para.wrap(max_width, 1000)
    para.drawOn(p, x, y - para_height)

    return y - para_height - space_after


def get_director_user(department=None):
    """
    Return the active Director assigned to the specified department.

    The function must not select a Director from another department.
    """
    queryset = UserProfile.objects.filter(
        approval_role__code="DIRECTOR",
        user__is_active=True,
    ).select_related(
        "user",
        "department",
        "approval_role",
    )

    if department:
        queryset = queryset.filter(
            department=department
        )
    else:
        return None

    profile = queryset.order_by(
        "user__username"
    ).first()

    return profile.user if profile else None


def get_head_of_unit_for_unit(
    department=None,
    department_unit=None,
    unit_name="",
):
    """
    Return the active Head of Unit assigned to the exact department
    and department unit.

    The legacy unit_name fallback is retained only for older permit
    records that do not yet contain department_unit.
    """
    if not department:
        return None

    queryset = UserProfile.objects.filter(
        approval_role__code="HEAD_OF_UNIT",
        department=department,
        user__is_active=True,
    ).select_related(
        "user",
        "department",
        "department_unit",
        "approval_role",
    )

    if department_unit:
        profile = queryset.filter(
            department_unit=department_unit
        ).order_by(
            "user__username"
        ).first()

        return profile.user if profile else None

    if unit_name:
        profile = queryset.filter(
            unit_name=unit_name
        ).order_by(
            "user__username"
        ).first()

        return profile.user if profile else None

    return None


def get_assistant_director_for_unit(
    department=None,
    department_unit=None,
    unit_name="",
):
    """
    Return the active Assistant Director for the exact unit.

    This deliberately has no department-wide fallback: when a unit has
    no Head of Unit, its request may bypass the HOU only when that same
    unit has an assigned Assistant Director.
    """
    if not department:
        return None

    queryset = (
        UserProfile.objects.filter(
            approval_role__code="ASSISTANT_DIRECTOR",
            department=department,
            user__is_active=True,
        )
        .select_related(
            "user",
            "department",
            "department_unit",
            "approval_role",
        )
        .order_by("user__username")
    )

    if department_unit:
        unit_values = {
            str(department_unit.code or "").strip(),
            str(department_unit.name or "").strip(),
        }
        unit_values.discard("")

        profile = queryset.filter(
            Q(department_unit=department_unit)
            | Q(unit_name__in=unit_values)
        ).first()

        return profile.user if profile else None

    legacy_unit_name = (unit_name or "").strip()

    if not legacy_unit_name:
        return None

    profile = queryset.filter(
        Q(unit_name__iexact=legacy_unit_name)
        | Q(department_unit__name__iexact=legacy_unit_name)
        | Q(department_unit__code__iexact=legacy_unit_name)
    ).first()

    return profile.user if profile else None


def _get_profile_approval_role_code(profile):
    """
    Return the standardized ApprovalRole code assigned to a profile.
    """
    if not profile:
        return None

    approval_role = getattr(
        profile,
        "approval_role",
        None,
    )

    approval_role_code = getattr(
        approval_role,
        "code",
        None,
    )

    if not approval_role_code:
        return None

    role_code = approval_role_code.strip().upper()

    if role_code == "SYSTEM_ADMIN":
        return "ADMIN"

    return role_code


def _get_department_workflow_steps(
    department,
    module="PERMIT",
):
    if not department:
        return []

    from .models import DepartmentApprovalWorkflow

    return list(
        DepartmentApprovalWorkflow.objects.filter(
            department=department,
            module=module,
            is_active=True,
            is_required=True,
        )
        .select_related("approval_role")
        .order_by("step_order")
    )


def _find_approver_for_workflow_step(
    requester_profile,
    approval_role_code,
):
    """
    Find an active approver using the requester's department and unit.

    Routing:
    - HEAD_OF_UNIT: exact department and exact unit
    - ASSISTANT_DIRECTOR: exact department and exact unit first,
      then any Assistant Director in the same department
    - DIRECTOR: same department
    - Central roles: organization-wide fallback
    """
    if not requester_profile or not approval_role_code:
        return None

    role_code = approval_role_code.strip().upper()

    queryset = UserProfile.objects.filter(
        approval_role__code=role_code,
        user__is_active=True,
    ).select_related(
        "user",
        "department",
        "department_unit",
        "approval_role",
    ).order_by(
        "user__username"
    )

    if requester_profile.user_id:
        queryset = queryset.exclude(
            user=requester_profile.user
        )

    department = requester_profile.department
    department_unit = requester_profile.department_unit

    if role_code == "HEAD_OF_UNIT":
        if not department or not department_unit:
            return None

        profile = queryset.filter(
            department=department,
            department_unit=department_unit,
        ).first()

        return profile.user if profile else None

    if role_code == "ASSISTANT_DIRECTOR":
        if not department:
            return None

        if department_unit:
            unit_profile = queryset.filter(
                department=department,
                department_unit=department_unit,
            ).first()

            if unit_profile:
                return unit_profile.user

        department_profile = queryset.filter(
            department=department
        ).first()

        return (
            department_profile.user
            if department_profile
            else None
        )

    if role_code == "DIRECTOR":
        if not department:
            return None

        profile = queryset.filter(
            department=department
        ).first()

        return profile.user if profile else None

    if role_code in [
        "SYSTEM_ADMIN",
        "ADMIN",
        "DIVISION_BUDGET_OFFICER",
        "ACCOUNTANT",
    ]:
        profile = queryset.first()
        return profile.user if profile else None

    return None


def _apply_legacy_permit_routing(req, profile):
    """
    Compatibility routing for Permit records that cannot use the
    configured DepartmentApprovalWorkflow.

    All role decisions use standardized approval-role codes.
    """
    role_code = _get_profile_approval_role_code(
        profile
    )

    req.unit_name = (
        profile.department_unit.name
        if profile.department_unit
        else profile.unit_name
    )

    req.head_of_unit = get_head_of_unit_for_unit(
        department=profile.department,
        department_unit=profile.department_unit,
        unit_name=profile.unit_name,
    )

    req.director = get_director_user(
        department=profile.department
    )

    assistant_director = get_assistant_director_for_unit(
        department=profile.department,
        department_unit=profile.department_unit,
        unit_name=profile.unit_name,
    )

    direct_to_director_roles = [
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
        "HEAD_OF_UNIT",
    ]

    if role_code in direct_to_director_roles:
        req.status = "PENDING_DIRECTOR"

    elif (
        profile.department_unit
        and profile.department_unit.code == "CCU"
    ):
        req.status = "PENDING_DIRECTOR"

    elif req.head_of_unit:
        req.status = "PENDING_HOU"

    elif assistant_director:
        # No HOU exists for this unit. The unit Assistant Director is
        # the next approver and will forward to the Department Director.
        req.director = assistant_director
        req.status = "PENDING_DIRECTOR"

    else:
        req.status = "PENDING_DIRECTOR"

    return req


def _apply_permit_workflow_routing(req, profile):
    """
    Apply the Permit approval chain for the requester's exact unit.

    Normal chain:
        Head of Unit -> unit Assistant Director -> Department Director

    If the exact unit has no Head of Unit:
        unit Assistant Director -> Department Director

    Existing status values are retained. PENDING_DIRECTOR means the
    request is waiting for whichever director-level user is stored in
    req.director (Assistant Director or final Director).
    """
    req.unit_name = (
        profile.department_unit.name
        if profile.department_unit
        else profile.unit_name
    )
    req.head_of_unit = None
    req.director = None

    if not profile.department:
        return _apply_legacy_permit_routing(req, profile)

    requester_role = _get_profile_approval_role_code(profile)
    unit_head = get_head_of_unit_for_unit(
        department=profile.department,
        department_unit=profile.department_unit,
        unit_name=profile.unit_name,
    )
    assistant_director = get_assistant_director_for_unit(
        department=profile.department,
        department_unit=profile.department_unit,
        unit_name=profile.unit_name,
    )
    department_director = get_director_user(
        department=profile.department
    )

    # A Director's own request cannot be routed back to the same user.
    if requester_role == "DIRECTOR":
        req.director = assistant_director
        if not req.director:
            req.director = department_director
        req.status = "PENDING_DIRECTOR"
        return req

    # An Assistant Director's own request goes to the final Director.
    if requester_role == "ASSISTANT_DIRECTOR":
        req.director = department_director
        req.status = "PENDING_DIRECTOR"
        return req

    # A HOU request starts at its unit Assistant Director.
    if requester_role == "HEAD_OF_UNIT":
        req.director = assistant_director or department_director
        req.status = "PENDING_DIRECTOR"
        return req

    if unit_head:
        req.head_of_unit = unit_head
        # Pre-store the next approver; HOU approval re-resolves it to
        # protect against later staffing changes.
        req.director = assistant_director or department_director
        req.status = "PENDING_HOU"
        return req

    if assistant_director:
        req.director = assistant_director
        req.status = "PENDING_DIRECTOR"
        return req

    # Final safety fallback when neither a HOU nor unit Assistant
    # Director exists: keep the request inside its own department.
    req.director = department_director
    req.status = "PENDING_DIRECTOR"
    return req


def notify_user_email(user, subject, message):
    return notify_user(
        user=user,
        subject=subject,
        message=message,
    )


def notify_head_of_unit(req):
    if req.head_of_unit:
        notify_user_email(
            req.head_of_unit,
            "Permit Request Awaiting Your Approval",
            f"Permit request {req.reference_no} is waiting for your approval."
        )


def notify_director(req):
    if req.director:
        notify_user_email(
            req.director,
            "Permit Request Awaiting Director Approval",
            f"Permit request {req.reference_no} is waiting for your approval."
        )


def notify_requester(req, action_text):
    notify_user_email(
        req.requester,
        "Update on Your Permit Request",
        f"Your permit request {req.reference_no} has been {action_text}."
    )


# Role-based access control decorator
def require_role(*roles):
    """
    Decorator to require specific user roles.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user_role = _get_profile(request.user).role if request.user.is_authenticated else None

            print("DEBUG ROLE:", request.user.username, "|", user_role, "| allowed:", roles)

            if request.user.is_superuser or user_role in roles:
                return view_func(request, *args, **kwargs)

            return HttpResponseForbidden("Not allowed.")
        return wrapper
    return decorator


# CROSS-ROLE BLOCKING: Helper to validate all participants in a group request
def _validate_group_participants(form, formset, exclude_pk=None):
    """
    Validates that the group leader and every group member with a member_user
    are not blocked by an existing active/pending/unclosed permit.

    Returns a list of error messages. Empty list means all clear.
    """
    errors = []

    # Check group leader
    group_leader = form.cleaned_data.get("group_leader")
    if group_leader:
        blocking = _get_blocking_request_for_member(group_leader, exclude_pk=exclude_pk)
        if blocking:
            leader_name = group_leader.get_full_name() or group_leader.username
            errors.append(
                _build_blocking_request_message(blocking, person_name=f"Group leader '{leader_name}'")
            )

    # Check each group member that has a linked user account
    if formset.is_valid():
        for member_form in formset:
            if member_form.cleaned_data and not member_form.cleaned_data.get("DELETE", False):
                member_user = member_form.cleaned_data.get("member_user")
                if member_user:
                    blocking = _get_blocking_request_for_member(member_user, exclude_pk=exclude_pk)
                    if blocking:
                        member_name = (
                            member_form.cleaned_data.get("full_name")
                            or member_user.get_full_name()
                            or member_user.username
                        )
                        errors.append(
                            _build_blocking_request_message(blocking, person_name=f"Group member '{member_name}'")
                        )

    return errors


# ---------------------------------------------------------------------
# Authentication / role redirects
# ---------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect("system_home")

    form = LoginForm(request, data=request.POST or None)

    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            login(request, user)

            log_action(
                user=user,
                action="LOGIN",
                module="AUTH",
                reference_no=user.username,
                description="User logged in.",
                request=request,
            )

            return redirect("system_home")
    return render(request, "permits/login.html", {"form": form})



def _reports_allowed(user):
    return _get_user_role(user) in [
        "ADMIN",
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]


def _filter_reports_by_date(qs, request):
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    if start_date:
        parsed_start = parse_date(start_date)
        if parsed_start:
            qs = qs.filter(created_at__date__gte=parsed_start)

    if end_date:
        parsed_end = parse_date(end_date)
        if parsed_end:
            qs = qs.filter(created_at__date__lte=parsed_end)

    return qs


def _format_duration(duration):
    if not duration:
        return "N/A"

    total_seconds = int(duration.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _percent(part, total):
    if not total:
        return 0
    return round((part / total) * 100, 1)

# ---------------------------------------------------------------------
# Permit Report Filter Helper Function
# ---------------------------------------------------------------------

def _apply_permit_report_filters(qs, request):
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    status = request.GET.get("status", "").strip()
    unit = request.GET.get("unit", "").strip()
    requester_id = request.GET.get("requester", "").strip()

    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)

    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)

    if status:
        qs = qs.filter(status=status)

    if unit:
        qs = qs.filter(requester__profile__unit_name=unit)

    if requester_id:
        qs = qs.filter(requester_id=requester_id)

    return qs

@login_required
def role_redirect(request):
    """
    Redirect users according to the standardized approval role.
    """
    role = _get_user_role(request.user)

    if role == "ADMIN":
        return redirect("admin_dashboard")

    if role == "HEAD_OF_UNIT":
        return redirect("head_of_unit_requests")

    if role in [
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]:
        return redirect("director_dashboard")

    return redirect("requester_dashboard")




def logout_view(request):

    log_action(
        user=request.user,
        action="LOGOUT",
        module="AUTH",
        reference_no=request.user.username,
        description="User logged out.",
        request=request,
    )

    logout(request)
    return redirect("login")


# ---------------------------------------------------------------------
# Staff details AJAX endpoint
# ---------------------------------------------------------------------

@login_required
def acting_officer_details(request, user_id):
    try:
        officer = User.objects.select_related("profile").get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        return JsonResponse({"error": "Officer not found."}, status=404)

    profile = getattr(officer, "profile", None)

    return JsonResponse({
        "id": officer.id,
        "full_name": officer.get_full_name().strip() or officer.username,
        "employee_id": getattr(profile, "employee_id", "") or "",
        "phone_number": getattr(profile, "phone_number", "") or "",
    })


# ---------------------------------------------------------------------
# Permit verification
# ---------------------------------------------------------------------

def verify_permit(request, reference_no):
    req = get_object_or_404(
        ExternalWorkRequest.objects.prefetch_related("members"),
        reference_no=reference_no
    )

    _attach_display_status(req, context="detail")

    now = timezone.now()

    is_valid = req.status in ["APPROVED", "CLOSED"]
    is_expired = req.end_time < now
    is_active = req.status == "APPROVED" and req.start_time <= now <= req.end_time

    approved_by_name = ""
    approved_by_role = ""

    if req.director_approved_by:
        approved_by_name = req.director_approved_by.get_full_name() or req.director_approved_by.username
        approved_by_role = _get_profile(req.director_approved_by).role

    context = {
        "req": req,
        "is_valid": is_valid,
        "is_expired": is_expired,
        "is_active": is_active,
        "approved_by_name": approved_by_name,
        "approved_by_role": approved_by_role,
        "now": now,
        "is_view_only": True,
    }

    return render(request, "permits/verify_permit.html", context)


# ---------------------------------------------------------------------
# Requester dashboard
# ---------------------------------------------------------------------
def _get_system_setting():
    setting, created = SystemSetting.objects.get_or_create(id=1)
    return setting


@login_required
def requester_dashboard(request):
    setting = _get_system_setting()

@login_required
def requester_dashboard(request):
    setting = _get_system_setting()

    if not setting.open_permit_enabled:
        messages.error(request, "Open Permit module is currently disabled by the System Administrator.")
        return redirect("system_home")

    status = request.GET.get("status")
    now = timezone.now()

    base_requests = ExternalWorkRequest.objects.filter(requester=request.user)

    if status == "OVERDUE":
        requests = base_requests.filter(
            end_time__lt=now
        ).exclude(
            status__in=["CLOSED"] + _rejected_statuses()
        )
    elif status in ["RETURNED", "RETURNED_HOU", "RETURNED_DIRECTOR"]:
        requests = base_requests.filter(status__in=_returned_statuses())
    elif status in ["REJECTED", "REJECTED_HOU", "REJECTED_DIRECTOR"]:
        requests = base_requests.filter(status__in=_rejected_statuses())
    elif status in ["SUBMITTED", "PENDING", "PENDING_HOU", "PENDING_DIRECTOR"]:
        requests = base_requests.filter(status__in=["PENDING_HOU", "PENDING_DIRECTOR"])
    elif _is_total_status(status):
        requests = base_requests
    else:
        requests = base_requests.filter(status=status)

    requests = requests.order_by("-updated_at")
    request_list = list(requests)

    for r in request_list:
        r.is_overdue = (
            r.end_time < now and r.status not in (["CLOSED"] + _rejected_statuses())
        )
        _attach_display_status(r, context="requester_list")

    total_requests = base_requests.count()
    returned_count = base_requests.filter(status__in=_returned_statuses()).count()
    approved_count = base_requests.filter(status="APPROVED").count()
    rejected_count = base_requests.filter(status__in=_rejected_statuses()).count()
    closed_count = base_requests.filter(status="CLOSED").count()
    overdue_count = base_requests.filter(
        end_time__lt=now
    ).exclude(
        status__in=["CLOSED"] + _rejected_statuses()
    ).count()

    blocking_request = _get_blocking_request_for_user(request.user)
    blocking_request_message = None

    if blocking_request:
        blocking_request_message = _build_blocking_request_message(blocking_request)

    welcome_name = request.user.get_full_name().strip() or request.user.username

    context = {
        "requests": request_list,
        "selected_status": status,
        "total_requests": total_requests,
        "returned_count": returned_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "closed_count": closed_count,
        "overdue_count": overdue_count,
        "has_blocking_request": bool(blocking_request),
        "blocking_request_message": blocking_request_message,
        "welcome_name": welcome_name,
    }

    return render(request, "permits/requester_dashboard.html", context)


# ---------------------------------------------------------------------
# System home / role redirects
# ---------------------------------------------------------------------

@login_required
def system_home(request):
    """
    System home page with standardized role-aware navigation.
    """
    # The module launcher is not the destination for workflow feedback.
    # Consume any notification left by a previous page so it cannot appear on
    # an unrelated dashboard later.
    list(messages.get_messages(request))
    role = _get_user_role(request.user)
    module_roles = request.user.module_role_assignments.filter(
        is_active=True
    ).order_by("module")

    context = {
        "role": role,
        "module_roles": module_roles,
        "is_admin": role == "ADMIN",
        "is_head_of_unit": role == "HEAD_OF_UNIT",
        "is_director_level": role in [
            "DIRECTOR",
            "ASSISTANT_DIRECTOR",
        ],
    }

    return render(
        request,
        "system_home.html",
        context,
    )


# ---------------------------------------------------------------------
# Admin dashboard / user management
# ---------------------------------------------------------------------

@login_required
def admin_dashboard(request):
    profile = _get_profile(request.user)

    if not (request.user.is_superuser or profile.role == "ADMIN"):
        return HttpResponseForbidden("Not allowed.")

    leadership_profiles = (
        UserProfile.objects.select_related(
            "user", "department", "department_unit", "approval_role"
        )
        .filter(user__is_active=True, department__is_active=True)
        .filter(
            Q(role__in=["DIRECTOR", "ASSISTANT_DIRECTOR", "HEAD_OF_UNIT"])
            | Q(approval_role__code__in=[
                "DIRECTOR", "ASSISTANT_DIRECTOR", "HEAD_OF_UNIT"
            ])
        )
        .order_by("department__code", "department_unit__code", "user__last_name")
    )
    leaders_by_department = {}
    for leadership_profile in leadership_profiles:
        role_code = (
            leadership_profile.approval_role.code
            if leadership_profile.approval_role_id
            else leadership_profile.role
        )
        department_group = leaders_by_department.setdefault(
            leadership_profile.department_id,
            {
                "department": leadership_profile.department,
                "directors": [],
                "assistant_directors": [],
                "heads_of_unit": [],
            },
        )
        destination = {
            "DIRECTOR": "directors",
            "ASSISTANT_DIRECTOR": "assistant_directors",
            "HEAD_OF_UNIT": "heads_of_unit",
        }.get(role_code)
        if destination:
            department_group[destination].append(leadership_profile)

    context = {
        "department_role_groups": list(leaders_by_department.values()),
        "departments_without_leaders": Department.objects.filter(
            is_active=True
        ).exclude(pk__in=leaders_by_department).order_by("code"),
    }

    return render(request, "permits/admin_dashboard.html", context)


@login_required
def user_management(request):
    if not _admin_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    from .models import (
        ApprovalRole,
        Department,
        DepartmentUnit,
    )

    section = request.GET.get(
        "section",
        "create",
    ).strip().lower()

    if section not in ["create", "existing"]:
        section = "create"

    query = request.GET.get("q", "").strip()
    department_filter = request.GET.get(
        "department",
        "",
    ).strip()
    unit_filter = request.GET.get(
        "department_unit",
        "",
    ).strip()
    role_filter = request.GET.get(
        "role",
        "",
    ).strip().upper()
    account_status_filter = request.GET.get(
        "account_status",
        "",
    ).strip().lower()
    staff_filter = request.GET.get(
        "staff_access",
        "",
    ).strip().lower()

    users = (
        User.objects
        .select_related(
            "profile",
            "profile__department",
            "profile__department_unit",
            "profile__approval_role",
            "profile__head_of_unit",
        )
        .prefetch_related("module_role_assignments")
        .all()
        .order_by("username")
    )

    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(profile__employee_id__icontains=query)
            | Q(profile__check_number__icontains=query)
            | Q(profile__phone_number__icontains=query)
            | Q(profile__department__code__icontains=query)
            | Q(profile__department__name__icontains=query)
            | Q(profile__department_unit__code__icontains=query)
            | Q(profile__department_unit__name__icontains=query)
            | Q(profile__approval_role__code__icontains=query)
            | Q(profile__role__icontains=query)
            | Q(module_role_assignments__role_code__icontains=query)
        ).distinct()

    if department_filter.isdigit():
        users = users.filter(
            profile__department_id=department_filter
        )

    if unit_filter.isdigit():
        users = users.filter(
            profile__department_unit_id=unit_filter
        )

    if role_filter:
        users = users.filter(
            Q(profile__approval_role__code=role_filter)
            | Q(profile__role=role_filter)
            | Q(module_role_assignments__role_code=role_filter)
        ).distinct()

    if account_status_filter == "active":
        users = users.filter(is_active=True)
    elif account_status_filter == "inactive":
        users = users.filter(is_active=False)

    if staff_filter == "staff":
        users = users.filter(is_staff=True)
    elif staff_filter == "normal":
        users = users.filter(is_staff=False)

    departments = Department.objects.filter(
        is_active=True
    ).order_by("code", "name")

    department_units = DepartmentUnit.objects.filter(
        is_active=True
    ).select_related("department")

    if department_filter.isdigit():
        department_units = department_units.filter(
            department_id=department_filter
        )

    department_units = department_units.order_by(
        "department__code",
        "code",
        "name",
    )

    approval_roles = ApprovalRole.objects.filter(
        is_active=True
    ).order_by("code")

    create_form = AdminUserCreateForm()

    return render(
        request,
        "permits/user_management.html",
        {
            "users": users,
            "create_form": create_form,
            "query": query,
            "section": section,
            "departments": departments,
            "department_units": department_units,
            "approval_roles": approval_roles,
            "department_filter": department_filter,
            "unit_filter": unit_filter,
            "role_filter": role_filter,
            "account_status_filter": account_status_filter,
            "staff_filter": staff_filter,
        }
    )


@login_required
def create_user_account(request):
    if not _admin_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    if request.method != "POST":
        return redirect("user_management")

    form = AdminUserCreateForm(request.POST)

    if form.is_valid():
        user = User.objects.create_user(
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            email=form.cleaned_data["email"],
        )
        user.is_staff = form.cleaned_data["is_staff"]
        user.save()

        profile, created = UserProfile.objects.get_or_create(user=user)
        profile.role = form.cleaned_data["role"]
        profile.approval_role = _get_approval_role_from_role_code(form.cleaned_data["role"])
        profile.employee_id = form.cleaned_data["employee_id"]
        profile.check_number = form.cleaned_data["check_number"]
        profile.phone_number = form.cleaned_data["phone_number"]
        profile.department = form.cleaned_data["department"]
        profile.department_unit = form.cleaned_data["department_unit"]
        profile.unit_name = ""
        profile.head_of_unit = form.cleaned_data["head_of_unit"]
        profile.save()

        for module, field_name in (
            (ModuleRoleAssignment.Module.EVENT, "event_role"),
            (ModuleRoleAssignment.Module.FINANCE, "finance_role"),
            (ModuleRoleAssignment.Module.TASK, "task_role"),
        ):
            set_module_roles(
                user,
                module,
                form.cleaned_data[field_name],
                profile.department,
            )

        log_action(
            user=request.user,
            action="CREATE",
            module="USER_MANAGEMENT",
            reference_no=user.username,
            description=f"User account created for {user.username}.",
            request=request,
        )

        messages.success(request, "User account created successfully.")
        return redirect("user_management")

    users = (
        User.objects.select_related("profile")
        .prefetch_related("module_role_assignments")
        .all()
        .order_by("username")
    )
    return render(
        request,
        "permits/user_management.html",
        {
            "users": users,
            "create_form": form,
            "query": "",
        }
    )


@login_required
def edit_user_account(request, user_id):
    if not _admin_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    target_user = get_object_or_404(User, pk=user_id)
    profile, created = UserProfile.objects.get_or_create(user=target_user)

    if request.method == "POST":
        form = AdminUserUpdateForm(request.POST)

        if form.is_valid():
            target_user.first_name = form.cleaned_data["first_name"]
            target_user.last_name = form.cleaned_data["last_name"]
            target_user.email = form.cleaned_data["email"]
            target_user.is_staff = form.cleaned_data["is_staff"]
            target_user.save()

            profile.role = form.cleaned_data["role"]
            profile.approval_role = _get_approval_role_from_role_code(form.cleaned_data["role"])
            profile.employee_id = form.cleaned_data["employee_id"]
            profile.check_number = form.cleaned_data["check_number"]
            profile.phone_number = form.cleaned_data["phone_number"]
            profile.department = form.cleaned_data["department"]
            profile.department_unit = form.cleaned_data["department_unit"]
            profile.unit_name = ""
            profile.head_of_unit = form.cleaned_data["head_of_unit"]
            profile.save()

            for module, field_name in (
                (ModuleRoleAssignment.Module.EVENT, "event_role"),
                (ModuleRoleAssignment.Module.FINANCE, "finance_role"),
                (ModuleRoleAssignment.Module.TASK, "task_role"),
            ):
                set_module_roles(
                    target_user,
                    module,
                    form.cleaned_data[field_name],
                    profile.department,
                )

            log_action(
                user=request.user,
                action="UPDATE",
                module="USER_MANAGEMENT",
                reference_no=target_user.username,
                description=f"User account updated for {target_user.username}.",
                request=request,
            )

            messages.success(request, "User account updated successfully.")
            return redirect("user_management")
    else:
        assigned_roles = {}
        for module, role_code in target_user.module_role_assignments.filter(
            is_active=True
        ).values_list("module", "role_code"):
            assigned_roles.setdefault(module, []).append(role_code)
        form = AdminUserUpdateForm(initial={
            "first_name": target_user.first_name,
            "last_name": target_user.last_name,
            "email": target_user.email,
            "employee_id": profile.employee_id,
            "check_number": profile.check_number,
            "phone_number": profile.phone_number,
            "department": profile.department,
            "department_unit": profile.department_unit,
            "unit_name": profile.unit_name,
            "head_of_unit": profile.head_of_unit,
            "role": profile.role,
            "event_role": assigned_roles.get(ModuleRoleAssignment.Module.EVENT, []),
            "finance_role": assigned_roles.get(ModuleRoleAssignment.Module.FINANCE, []),
            "task_role": assigned_roles.get(ModuleRoleAssignment.Module.TASK, []),
            "is_staff": target_user.is_staff,
        })

    return render(
        request,
        "permits/edit_user_account.html",
        {
            "target_user": target_user,
            "form": form,
        }
    )


@login_required
def reset_user_password(request, user_id):
    if not _admin_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    target_user = get_object_or_404(User, pk=user_id)

    if request.method == "POST":
        form = AdminPasswordResetForm(request.POST)

        if form.is_valid():
            target_user.set_password(form.cleaned_data["new_password"])
            target_user.save()

            log_action(
                user=request.user,
                action="UPDATE",
                module="USER_MANAGEMENT",
                reference_no=target_user.username,
                description=f"Password reset for user {target_user.username}.",
                request=request,
            )

            messages.success(request, "Password reset successfully.")
            return redirect("user_management")
    else:
        form = AdminPasswordResetForm()

    return render(
        request,
        "permits/reset_user_password.html",
        {
            "target_user": target_user,
            "form": form,
        }
    )


@login_required
def change_my_password(request):
    if request.method == "POST":
        form = UserPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["new_password"])
            request.user.save()
            update_session_auth_hash(request, request.user)

            log_action(
                user=request.user,
                action="UPDATE",
                module="USER_ACCOUNT",
                reference_no=request.user.username,
                description="User changed own password.",
                request=request,
            )

            messages.success(request, "Password changed successfully.")
            return redirect("role_redirect")
    else:
        form = UserPasswordChangeForm(request.user)

    return render(request, "permits/change_my_password.html", {"form": form})


# ---------------------------------------------------------------------
# Director dashboard (for DIRECTOR role only)
# ---------------------------------------------------------------------

@login_required
@require_role('DIRECTOR')
def director_dashboard(request):
    """
    Director Dashboard - Accessible only to users with DIRECTOR role.
    Displays all requests except those at PENDING_HOU stage.
    """
    status = request.GET.get("status")
    now = timezone.now()

    visible_requests = _director_scope_queryset(
        request.user,
        ExternalWorkRequest.objects.exclude(status="PENDING_HOU")
    )

    if status == "OVERDUE":
        recent_requests = visible_requests.filter(
            end_time__lt=now
        ).exclude(
            status__in=["CLOSED"] + _rejected_statuses()
        )
    elif status in ["RETURNED", "RETURNED_HOU", "RETURNED_DIRECTOR"]:
        recent_requests = visible_requests.filter(status__in=_returned_statuses())
    elif status in ["REJECTED", "REJECTED_HOU", "REJECTED_DIRECTOR"]:
        recent_requests = visible_requests.filter(status__in=_rejected_statuses())
    elif status in ["PENDING", "PENDING_DIRECTOR"]:
        recent_requests = visible_requests.filter(status="PENDING_DIRECTOR")
    elif _is_total_status(status):
        recent_requests = visible_requests
    else:
        recent_requests = visible_requests.filter(status=status)

    total_requests = visible_requests.count()
    pending_director_count = visible_requests.filter(status="PENDING_DIRECTOR").count()
    returned_count = visible_requests.filter(status__in=_returned_statuses()).count()
    approved_count = visible_requests.filter(status="APPROVED").count()
    rejected_count = visible_requests.filter(status__in=_rejected_statuses()).count()
    closed_count = visible_requests.filter(status="CLOSED").count()
    overdue_count = visible_requests.filter(
        end_time__lt=now
    ).exclude(
        status__in=["CLOSED"] + _rejected_statuses()
    ).count()

    recent_requests = recent_requests.order_by("-updated_at")[:10]
    recent_requests = _attach_display_status_list(recent_requests, context="list")

    context = {
        "selected_status": status,
        "total_requests": total_requests,
        "pending_director_count": pending_director_count,
        "returned_count": returned_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "closed_count": closed_count,
        "overdue_count": overdue_count,
        "recent_requests": recent_requests,
    }

    return render(request, "permits/director_dashboard.html", context)


# ---------------------------------------------------------------------
# Assistant Director Dashboard
# ---------------------------------------------------------------------

@login_required
@require_role("ASSISTANT_DIRECTOR")
def assistant_director_dashboard(request):
    """
    Dashboard for all Assistant Directors.

    Visibility rules:
    - A department-wide Assistant Director with no assigned unit sees
      requests from the entire assigned department.
    - A unit-specific Assistant Director sees requests only from the
      assigned department and department unit.
    - Requests still awaiting Head of Unit review are excluded.
    """
    profile = _get_profile(request.user)
    role = _get_user_role(request.user)
    if role != "ASSISTANT_DIRECTOR":
        return HttpResponseForbidden(
            "You are not allowed to access this dashboard."
        )

    status = request.GET.get(
        "status",
        "",
    ).strip()

    now = timezone.now()

    visible_requests = (
        ExternalWorkRequest.objects
        .select_related(
            "requester",
            "requester__profile",
            "requester__profile__department",
            "requester__profile__department_unit",
            "head_of_unit",
            "director",
        )
        .exclude(status="PENDING_HOU")
    )

    # Assistant Director must have a Department.
    if not profile.department_id:
        visible_requests = visible_requests.none()

    # Unit-specific Assistant Director:
    # for example DTVET/VTU, DTVET/FDU or DTVET/TEU.
    elif profile.department_unit_id:
        unit_values = {
            str(profile.department_unit.code or "").strip(),
            str(profile.department_unit.name or "").strip(),
            str(profile.unit_name or "").strip(),
        }
        unit_values.discard("")

        visible_requests = visible_requests.filter(
            requester__profile__department_id=(
                profile.department_id
            ),
        ).filter(
            Q(
                requester__profile__department_unit_id=(
                    profile.department_unit_id
                )
            )
            | Q(
                requester__profile__department_unit__isnull=True,
                requester__profile__unit_name__in=unit_values,
            )
        )

    # Department-wide Assistant Director:
    # for example the former ADRD and ADSTI accounts in DSTI.
    else:
        visible_requests = visible_requests.filter(
            requester__profile__department_id=(
                profile.department_id
            )
        )

    if status == "OVERDUE":
        recent_requests = visible_requests.filter(
            end_time__lt=now
        ).exclude(
            status__in=[
                "CLOSED",
            ] + _rejected_statuses()
        )

    elif status in [
        "RETURNED",
        "RETURNED_HOU",
        "RETURNED_DIRECTOR",
    ]:
        recent_requests = visible_requests.filter(
            status__in=_returned_statuses()
        )

    elif status in [
        "REJECTED",
        "REJECTED_HOU",
        "REJECTED_DIRECTOR",
    ]:
        recent_requests = visible_requests.filter(
            status__in=_rejected_statuses()
        )

    elif status in [
        "PENDING",
        "PENDING_DIRECTOR",
    ]:
        recent_requests = visible_requests.filter(
            status="PENDING_DIRECTOR"
        )

    elif _is_total_status(status):
        recent_requests = visible_requests

    elif status:
        recent_requests = visible_requests.filter(
            status=status
        )

    else:
        recent_requests = visible_requests

    total_requests = visible_requests.count()

    pending_director_count = visible_requests.filter(
        status="PENDING_DIRECTOR"
    ).count()

    returned_count = visible_requests.filter(
        status__in=_returned_statuses()
    ).count()

    approved_count = visible_requests.filter(
        status="APPROVED"
    ).count()

    rejected_count = visible_requests.filter(
        status__in=_rejected_statuses()
    ).count()

    closed_count = visible_requests.filter(
        status="CLOSED"
    ).count()

    overdue_count = visible_requests.filter(
        end_time__lt=now
    ).exclude(
        status__in=[
            "CLOSED",
        ] + _rejected_statuses()
    ).count()

    recent_requests = recent_requests.order_by(
        "-updated_at"
    )[:10]

    recent_requests = _attach_display_status_list(
        recent_requests,
        context="list",
    )

    scope_name = (
        profile.department_unit.name
        if profile.department_unit
        else (
            profile.department.name
            if profile.department
            else "Not Assigned"
        )
    )

    context = {
        "profile": profile,
        "role": role,
        "dashboard_title": (
            "Assistant Director Dashboard"
        ),
        "scope_name": scope_name,
        "is_unit_specific": bool(
            profile.department_unit_id
        ),
        "selected_status": status,
        "total_requests": total_requests,
        "pending_director_count": (
            pending_director_count
        ),
        "returned_count": returned_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "closed_count": closed_count,
        "overdue_count": overdue_count,
        "recent_requests": recent_requests,
    }

    return render(
        request,
        "permits/assistant_director_dashboard.html",
        context,
    )


# ---------------------------------------------------------------------
# Request creation / submission / edit / resubmit / delete
# ---------------------------------------------------------------------

@login_required
def create_request(request):
    profile = _get_profile(request.user)
    blocking_request = _get_blocking_request_for_user(request.user)

    if blocking_request:
        messages.error(request, _build_blocking_request_message(blocking_request))
        return redirect("requester_dashboard")

    if request.method == "POST":
        blocking_request = _get_blocking_request_for_user(request.user)
        if blocking_request:
            messages.error(request, _build_blocking_request_message(blocking_request))
            return redirect("requester_dashboard")

        form = ExternalWorkRequestForm(request.POST, request.FILES, user=request.user)
        formset = GroupMemberFormSet(request.POST)

        if form.is_valid():
            blocking_request = _get_blocking_request_for_user(request.user)
            if blocking_request:
                messages.error(request, _build_blocking_request_message(blocking_request))
                return redirect("requester_dashboard")

            req = form.save(commit=False)
            req.requester = request.user
            req.requester_name = request.user.get_full_name() or request.user.username
            req.requester_employee_id = profile.employee_id
            req.is_group_request = (form.cleaned_data.get("request_type") == "GROUP")

            req = _apply_permit_workflow_routing(req, profile)

            if req.is_group_request:
                formset = GroupMemberFormSet(request.POST, instance=req)
                if not formset.is_valid():
                    context = {
                        "form": form,
                        "formset": formset,
                        "blocking_request": None,
                    }
                    context.update(_requester_org_context(profile))
                    return render(request, "permits/request_form.html", context)

                # CROSS-ROLE BLOCKING: Validate group leader and all members
                participant_errors = _validate_group_participants(form, formset, exclude_pk=None)
                if participant_errors:
                    for err in participant_errors:
                        messages.error(request, err)
                    context = {
                        "form": form,
                        "formset": formset,
                        "blocking_request": None,
                    }
                    context.update(_requester_org_context(profile))
                    return render(request, "permits/request_form.html", context)

            req.save()

            if req.is_group_request:
                formset.instance = req
                formset.save()
            else:
                req.members.all().delete()

            if req.status == "PENDING_HOU":
                notify_head_of_unit(req)
            else:
                notify_director(req)

            log_action(
                user=request.user,
                action="SUBMIT",
                module="PERMIT",
                reference_no=req.reference_no,
                description="Permit request submitted.",
                request=request,
            )

            messages.success(request, "Request submitted successfully.")
            return redirect("submission_status", pk=req.pk)

    else:
        form = ExternalWorkRequestForm(
            user=request.user,
            initial={
                "requester_name": request.user.get_full_name() or request.user.username,
                "requester_employee_id": profile.employee_id,
            }
        )
        formset = GroupMemberFormSet()

    context = {
        "form": form,
        "formset": formset,
        "blocking_request": None,
    }
    context.update(_requester_org_context(profile))
    return render(request, "permits/request_form.html", context)


@login_required
def submission_status(request, pk):
    req = get_object_or_404(
        ExternalWorkRequest.objects.prefetch_related("members"),
        pk=pk
    )

    if req.requester != request.user and not request.user.is_staff:
        return HttpResponseForbidden("Not allowed.")

    _attach_display_status(req, context="detail")

    context = {
        "req": req,
        "is_view_only": req.is_view_only,
        "can_edit_returned": req.raw_status in _returned_statuses(),
    }
    return render(request, "permits/submission_status.html", context)


@login_required
def request_detail(request, pk):
    req = get_object_or_404(
        ExternalWorkRequest.objects.prefetch_related("members"),
        pk=pk
    )

    if req.requester != request.user and not request.user.is_staff:
        return HttpResponseForbidden("Not allowed.")

    _attach_display_status(req, context="detail")

    context = {
        "req": req,
        "is_view_only": req.is_view_only,
    }
    return render(request, "permits/request_detail.html", context)


@login_required
def edit_request(request, pk):
    req = get_object_or_404(
        ExternalWorkRequest.objects.prefetch_related("members"),
        pk=pk
    )

    if req.requester != request.user:
        return HttpResponseForbidden("Not allowed.")

    if req.status not in _returned_statuses():
        return HttpResponseForbidden("Only returned requests can be edited.")

    profile = _get_profile(request.user)

    if request.method == "POST":
        form = ExternalWorkRequestForm(
            request.POST,
            request.FILES,
            instance=req,
            user=request.user
        )
        formset = GroupMemberFormSet(request.POST, instance=req)

        if form.is_valid():
            req = form.save(commit=False)
            req.requester = request.user
            req.requester_name = request.user.get_full_name() or request.user.username
            req.requester_employee_id = profile.employee_id
            req.is_group_request = (form.cleaned_data.get("request_type") == "GROUP")

            if not req.is_group_request:
                req.group_leader = None
                req.group_leader_name = ""
                req.group_leader_employee_id = ""
                req.save()
                req.members.all().delete()

                log_action(
                    user=request.user,
                    action="UPDATE",
                    module="PERMIT",
                    reference_no=req.reference_no,
                    description="Permit request updated.",
                    request=request,
                )

                messages.success(request, "Request updated successfully.")
                return redirect("request_detail", pk=req.pk)

            if formset.is_valid():
                # CROSS-ROLE BLOCKING: Validate group leader and all members on edit
                participant_errors = _validate_group_participants(form, formset, exclude_pk=req.pk)
                if participant_errors:
                    for err in participant_errors:
                        messages.error(request, err)
                    context = {
                        "form": form,
                        "formset": formset,
                        "edit_mode": True,
                        "req": req,
                        "blocking_request": None,
                    }
                    context.update(_requester_org_context(profile))
                    return render(request, "permits/request_form.html", context)

                req.save()
                formset.instance = req
                formset.save()

                log_action(
                    user=request.user,
                    action="UPDATE",
                    module="PERMIT",
                    reference_no=req.reference_no,
                    description="Permit request updated.",
                    request=request,
                )

                messages.success(request, "Request updated successfully.")
                return redirect("request_detail", pk=req.pk)

    else:
        form = ExternalWorkRequestForm(instance=req, user=request.user)
        formset = GroupMemberFormSet(instance=req)

    context = {
        "form": form,
        "formset": formset,
        "edit_mode": True,
        "req": req,
        "blocking_request": None,
    }
    context.update(_requester_org_context(profile))
    return render(request, "permits/request_form.html", context)


@login_required
def resubmit_request(request, pk):
    req = get_object_or_404(ExternalWorkRequest, pk=pk)

    if req.requester != request.user:
        return HttpResponseForbidden("Not allowed.")

    if req.status not in _returned_statuses():
        return HttpResponseForbidden("Only returned requests can be re-submitted.")

    if request.method == "POST":
        profile = _get_profile(request.user)

        blocking_request = _get_blocking_request_for_user(request.user, exclude_pk=req.pk)
        if blocking_request:
            messages.error(request, _build_blocking_request_message(blocking_request))
            return redirect("requester_dashboard")

        req = _apply_permit_workflow_routing(req, profile)
        req.resubmitted_at = timezone.now()

        req.save()

        if req.status == "PENDING_HOU":
            notify_head_of_unit(req)
        else:
            notify_director(req)

        log_action(
            user=request.user,
            action="SUBMIT",
            module="PERMIT",
            reference_no=req.reference_no,
            description="Permit request re-submitted.",
            request=request,
        )

        messages.success(request, "Request re-submitted successfully.")
        return redirect("submission_status", pk=req.pk)

    return render(request, "permits/resubmit_request.html", {"req": req})


@login_required
@require_POST
def delete_request(request, pk):
    req = get_object_or_404(ExternalWorkRequest, pk=pk)

    if req.requester != request.user:
        return HttpResponseForbidden("Not allowed.")

    if req.status not in _returned_statuses():
        return HttpResponseForbidden("Only returned requests can be deleted.")

    reference_no = req.reference_no

    log_action(
        user=request.user,
        action="DELETE",
        module="PERMIT",
        reference_no=reference_no,
        description="Returned permit request deleted.",
        request=request,
    )

    req.delete()
    messages.success(request, "Request deleted successfully.")
    return redirect("requester_dashboard")


# ---------------------------------------------------------------------
# Report upload / PDF export
# ---------------------------------------------------------------------

@login_required
def upload_summary_report(request, pk):
    req = get_object_or_404(ExternalWorkRequest, pk=pk)

    if req.requester != request.user and not request.user.is_staff:
        return HttpResponseForbidden("Not allowed.")

    if req.status != "APPROVED":
        return HttpResponseForbidden("Summary report can only be uploaded after approval.")

    if request.method == "POST":
        form = ReportUploadForm(request.POST, request.FILES, instance=req)
        if form.is_valid():
            req = form.save(commit=False)
            if req.report_file:
                req.status = "CLOSED"
            req.save()

            log_action(
                user=request.user,
                action="CLOSE",
                module="PERMIT",
                reference_no=req.reference_no,
                description="Permit closed after summary report upload.",
                request=request,
            )

            messages.success(request, "Summary report uploaded successfully.")
            return redirect("request_detail", pk=req.pk)
    else:
        form = ReportUploadForm(instance=req)

    return render(request, "permits/upload_report.html", {"form": form, "req": req})


@login_required
def export_permit_pdf(request, pk):
    req = get_object_or_404(
        ExternalWorkRequest.objects.prefetch_related("members"),
        pk=pk
    )

    if req.status not in ["APPROVED", "CLOSED"]:
        return HttpResponseForbidden("Permit available only after approval.")

    _attach_display_status(req, context="detail")

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A6)

    width, height = A6
    p.setTitle(f"Permit_{req.reference_no}")

    tz_green = colors.HexColor("#1EB53A")
    tz_yellow = colors.HexColor("#FCD116")
    tz_black = colors.black
    tz_blue = colors.HexColor("#00A3DD")
    light_bg = colors.HexColor("#F9FBFD")
    border_gray = colors.HexColor("#BFC7D1")

    p.setFillColor(light_bg)
    p.rect(0, 0, width, height, fill=1, stroke=0)

    outer_margin = 8
    inner_margin = 12

    p.setStrokeColor(border_gray)
    p.setLineWidth(1.2)
    p.roundRect(
        outer_margin,
        outer_margin,
        width - (outer_margin * 2),
        height - (outer_margin * 2),
        6,
        stroke=1,
        fill=0
    )

    p.setStrokeColor(colors.black)
    p.setLineWidth(0.8)
    p.roundRect(
        inner_margin,
        inner_margin,
        width - (inner_margin * 2),
        height - (inner_margin * 2),
        5,
        stroke=1,
        fill=0
    )

    stripe_y = height - 18
    left_x = inner_margin + 4
    right_x = width - inner_margin - 4

    p.setStrokeColor(tz_green)
    p.setLineWidth(3)
    p.line(left_x, stripe_y, right_x, stripe_y)

    p.setStrokeColor(tz_yellow)
    p.setLineWidth(2)
    p.line(left_x, stripe_y - 4, right_x, stripe_y - 4)

    p.setStrokeColor(tz_black)
    p.setLineWidth(3)
    p.line(left_x, stripe_y - 8, right_x, stripe_y - 8)

    p.setStrokeColor(tz_blue)
    p.setLineWidth(2)
    p.line(left_x, stripe_y - 12, right_x, stripe_y - 12)

    bottom_y = inner_margin + 8

    p.setStrokeColor(tz_blue)
    p.setLineWidth(2)
    p.line(left_x, bottom_y + 8, right_x, bottom_y + 8)

    p.setStrokeColor(tz_black)
    p.setLineWidth(3)
    p.line(left_x, bottom_y + 4, right_x, bottom_y + 4)

    p.setStrokeColor(tz_yellow)
    p.setLineWidth(2)
    p.line(left_x, bottom_y, right_x, bottom_y)

    y = height - 48

    p.setFillColor(colors.black)
    p.setFont("Helvetica-Bold", 11)
    requester_profile = getattr(req.requester, "profile", None)
    requester_department = getattr(requester_profile, "department", None)

    if requester_department:
        permit_header = f"MoEST - {requester_department.code}"
    else:
        permit_header = "MoEST"
    p.drawCentredString(width / 2, y, permit_header)
    y -= 26

    try:
        logo_path = os.path.join(settings.BASE_DIR, "static", "logo", "moest_logo.png")
        logo = ImageReader(logo_path)
        p.drawImage(logo, width / 2 - 15, y - 10, width=30, height=30, mask="auto")
        y -= 38
    except Exception:
        y -= 8

    p.setFont("Helvetica-Bold", 10)
    p.drawCentredString(width / 2, y, "EXTERNAL WORK PERMIT")
    y -= 14

    p.setStrokeColor(border_gray)
    p.setLineWidth(0.6)
    p.line(inner_margin + 8, y, width - inner_margin - 8, y)
    y -= 12

    requester_display = req.requester_name or req.requester.username

    requester_profile = getattr(req.requester, "profile", None)
    requester_department = getattr(requester_profile, "department", None) if requester_profile else None
    requester_department_unit = getattr(requester_profile, "department_unit", None) if requester_profile else None

    department_code = requester_department.code if requester_department else "MoEST"
    department_name = requester_department.name if requester_department else "Ministry of Education, Science and Technology"
    department_unit_name = requester_department_unit.name if requester_department_unit else ""
    legacy_unit_name = req.unit_name or ""

    permit_header = f"MoEST - {department_code}" if department_code else "MoEST"

    approved_by_name = ""
    approved_by_role = ""
    approved_at_display = ""

    if req.director_approved_by:
        approved_by_name = req.director_approved_by.get_full_name() or req.director_approved_by.username
        approved_by_role = _format_role_label(req.director_approved_by)

    if req.director_approved_at:
        approved_at_display = _format_local_datetime(req.director_approved_at)

    content_bottom_limit = 116
    max_text_width = width - 36
    font_name = "Helvetica"

    body_blocks = [
        {
            "text": _build_pdf_field("Permit No", req.reference_no),
            "measure_text": f"Permit No: {req.reference_no}",
            "justify": False
        },
        {
            "text": _build_pdf_field("Requester", requester_display),
            "measure_text": f"Requester: {requester_display}",
            "justify": False
        },
    ]

    if requester_department:
        body_blocks.append({
            "text": _build_pdf_field("Department", f"{department_code} - {department_name}"),
            "measure_text": f"Department: {department_code} - {department_name}",
            "justify": False
        })

    if requester_department_unit:
        body_blocks.append({
            "text": _build_pdf_field("Department Unit", department_unit_name),
            "measure_text": f"Department Unit: {department_unit_name}",
            "justify": False
        })
    elif legacy_unit_name:
        body_blocks.append({
            "text": _build_pdf_field("Unit", legacy_unit_name),
            "measure_text": f"Unit: {legacy_unit_name}",
            "justify": False
        })

    body_blocks.append({
        "text": _build_pdf_field("Purpose", req.purpose or ""),
        "measure_text": f"Purpose: {req.purpose or ''}",
        "justify": True
    })
    body_blocks.append({
        "text": _build_pdf_field("Destination", req.destination or ""),
        "measure_text": f"Destination: {req.destination or ''}",
        "justify": False
    })
    body_blocks.append({
        "text": _build_pdf_field("Start", _format_local_datetime(req.start_time)),
        "measure_text": f"Start: {_format_local_datetime(req.start_time)}",
        "justify": False
    })
    body_blocks.append({
        "text": _build_pdf_field("End", _format_local_datetime(req.end_time)),
        "measure_text": f"End: {_format_local_datetime(req.end_time)}",
        "justify": False
    })
    body_blocks.append({
        "text": _build_pdf_field("Submitted At", _format_local_datetime(req.created_at)),
        "measure_text": f"Submitted At: {_format_local_datetime(req.created_at)}",
        "justify": False
    })

    if req.resubmitted_at:
        body_blocks.append({
            "text": _build_pdf_field("Re-Submitted At", _format_local_datetime(req.resubmitted_at)),
            "measure_text": f"Re-Submitted At: {_format_local_datetime(req.resubmitted_at)}",
            "justify": False
        })

    if approved_by_name:
        body_blocks.append({
            "text": _build_pdf_field("Approved by", approved_by_name),
            "measure_text": f"Approved by: {approved_by_name}",
            "justify": False
        })

    if approved_by_role:
        body_blocks.append({
            "text": _build_pdf_field("Role", approved_by_role),
            "measure_text": f"Role: {approved_by_role}",
            "justify": False
        })

    if approved_at_display:
        body_blocks.append({
            "text": _build_pdf_field("Approved At", approved_at_display),
            "measure_text": f"Approved At: {approved_at_display}",
            "justify": False
        })

    available_height = y - content_bottom_limit
    body_font_size, body_line_height = _select_pdf_layout(
        body_blocks,
        font_name=font_name,
        max_width=max_text_width,
        available_height=available_height
    )

    for block in body_blocks:
        y = _draw_paragraph_block(
            p,
            text=block["text"],
            x=18,
            y=y,
            max_width=max_text_width,
            font_name=font_name,
            font_size=body_font_size,
            leading=body_line_height,
            justify=block.get("justify", False),
            space_after=1
        )

    if y < content_bottom_limit:
        y = content_bottom_limit

    sig_y = 100
    sig_x1 = 18
    sig_x2 = width - 78

    signature_drawn = False
    #try:
    #    signature_path = os.path.join(settings.BASE_DIR, "static", "signatures", "director_signature.png")
    #    if os.path.exists(signature_path):
    #        signature_img = ImageReader(signature_path)
    #        p.drawImage(
    #            signature_img,
    #            sig_x1 + 8,
    #            sig_y - 8,
    #            width=60,
    #            height=18,
    #            mask="auto",
    #            preserveAspectRatio=True
    #        )
    #        signature_drawn = True
    #except Exception:
    #    signature_drawn = False

    #p.setFont("Helvetica", 7)

    #if signature_drawn:
    #    p.drawString(sig_x1, sig_y - 12, "Authorized Signature")
    #else:
    #    p.setStrokeColor(colors.black)
    #    p.setLineWidth(0.8)
    #    p.line(sig_x1, sig_y, sig_x2, sig_y)
    #    p.drawString(sig_x1, sig_y - 9, "Authorized Signature")

    hou_approved_by_name = ""
    if req.hou_approved_by:
        hou_approved_by_name = req.hou_approved_by.get_full_name() or req.hou_approved_by.username

    director_approved_by_name = ""
    if req.director_approved_by:
        director_approved_by_name = req.director_approved_by.get_full_name() or req.director_approved_by.username

    verify_path = reverse(
        "verify_permit",
        args=[req.reference_no],
    )

    # PUBLIC_BASE_URL should be the address reachable by the scanner,
    # for example https://permits.example.go.tz. During development it
    # falls back to the host used to open the current request.
    public_base_url = str(
        getattr(settings, "PUBLIC_BASE_URL", "") or ""
    ).strip().rstrip("/")

    if public_base_url:
        verify_url = f"{public_base_url}{verify_path}"
    else:
        verify_url = request.build_absolute_uri(
            verify_path
        )

    # Keep the QR payload deliberately small. The verification page is
    # the authoritative, current source for all permit and audit data.
    qr_image = ImageReader(io.BytesIO(generate_qr_png(verify_url)))

    qr_size = 34
    qr_x = (width - qr_size) / 2
    qr_y = 38
    p.drawImage(qr_image, qr_x, qr_y, width=qr_size, height=qr_size)

    p.setFont("Helvetica", 6.3)
    p.drawCentredString(width / 2, qr_y - 6, "Scan QR to verify permit")

    p.showPage()
    p.save()

    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f"permit_{req.reference_no}.pdf")


# ---------------------------------------------------------------------
# Head of Unit views
# ---------------------------------------------------------------------

@login_required
def head_of_unit_requests(request):
    profile = _get_profile(request.user)
    viewed_officer = request.user

    if _admin_allowed(request.user) and request.GET.get("officer"):
        viewed_officer = get_object_or_404(
            User.objects.select_related(
                "profile__department", "profile__department_unit"
            ).filter(
                Q(profile__role="HEAD_OF_UNIT")
                | Q(profile__approval_role__code="HEAD_OF_UNIT")
            ),
            pk=request.GET.get("officer"),
            is_active=True,
        )
        profile = viewed_officer.profile
    elif not _head_of_unit_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    status = request.GET.get("status")
    now = timezone.now()
    base_queryset = ExternalWorkRequest.objects.select_related(
            "requester",
            "requester__profile",
            "requester__profile__department",
            "requester__profile__department_unit",
        )
    if viewed_officer != request.user:
        base_requests = base_queryset.filter(
            head_of_unit=viewed_officer,
            requester__profile__department_id=profile.department_id,
        )
        if profile.department_unit_id:
            base_requests = base_requests.filter(
                requester__profile__department_unit_id=profile.department_unit_id
            )
    else:
        base_requests = _head_of_unit_scope_queryset(
            request.user,
            base_queryset,
        )
    if status == "OVERDUE":
        requests = base_requests.filter(
            end_time__lt=now
        ).exclude(
            status__in=["CLOSED"] + _rejected_statuses()
        )
    elif status in ["PENDING", "PENDING_HOU"]:
        requests = base_requests.filter(status="PENDING_HOU")
    elif status in ["RETURNED", "RETURNED_HOU", "RETURNED_DIRECTOR"]:
        requests = base_requests.filter(status__in=_returned_statuses())
    elif status in ["REJECTED", "REJECTED_HOU", "REJECTED_DIRECTOR"]:
        requests = base_requests.filter(status__in=_rejected_statuses())
    elif status in ["APPROVED", "CLOSED"]:
        requests = base_requests.filter(status=status)
    elif status in ["APPROVED_FORWARDED", "FORWARDED", "PENDING_DIRECTOR"]:
        requests = base_requests.filter(
            hou_approved_by=viewed_officer,
            status__in=["PENDING_DIRECTOR", "APPROVED", "CLOSED", "RETURNED_DIRECTOR", "REJECTED_DIRECTOR"]
        )
    elif _is_total_status(status):
        requests = base_requests
    else:
        requests = base_requests.filter(status=status)

    requests = requests.order_by("-updated_at")
    requests = _attach_display_status_list(requests, context="list")

    total_requests = base_requests.count()
    pending_hou_count = base_requests.filter(status="PENDING_HOU").count()
    returned_count = base_requests.filter(status__in=_returned_statuses()).count()
    rejected_count = base_requests.filter(status__in=_rejected_statuses()).count()
    approved_count = base_requests.filter(status="APPROVED").count()
    closed_count = base_requests.filter(status="CLOSED").count()
    approved_forwarded_count = base_requests.filter(
        hou_approved_by=viewed_officer
    ).exclude(status="PENDING_HOU").count()
    overdue_count = base_requests.filter(
        end_time__lt=now
    ).exclude(
        status__in=["CLOSED"] + _rejected_statuses()
    ).count()

    welcome_name = request.user.get_full_name().strip() or request.user.username

    return render(
        request,
        "permits/head_of_unit_requests.html",
        {
            "requests": requests,
            "selected_status": status,
            "total_requests": total_requests,
            "pending_hou_count": pending_hou_count,
            "returned_count": returned_count,
            "rejected_count": rejected_count,
            "approved_count": approved_count,
            "closed_count": closed_count,
            "approved_forwarded_count": approved_forwarded_count,
            "overdue_count": overdue_count,
            "welcome_name": welcome_name,
            "viewed_officer": viewed_officer,
            "admin_scope_query": (
                f"officer={viewed_officer.pk}"
                if viewed_officer != request.user
                else ""
            ),
        }
    )


@login_required
def head_of_unit_request_detail(request, pk):
    profile = _get_profile(request.user)
    viewed_officer = request.user

    if _admin_allowed(request.user) and request.GET.get("officer"):
        viewed_officer = get_object_or_404(
            User.objects.filter(
                Q(profile__role="HEAD_OF_UNIT")
                | Q(profile__approval_role__code="HEAD_OF_UNIT")
            ),
            pk=request.GET.get("officer"),
            is_active=True,
        )
    elif not _head_of_unit_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    scoped_requests = (
        ExternalWorkRequest.objects
            .select_related(
                "requester",
                "requester__profile",
                "requester__profile__department",
                "requester__profile__department_unit",
            )
            .prefetch_related("members")
    )
    if viewed_officer != request.user:
        scoped_requests = scoped_requests.filter(head_of_unit=viewed_officer)
    else:
        scoped_requests = _head_of_unit_scope_queryset(
            request.user, scoped_requests
        )
    req = get_object_or_404(scoped_requests, pk=pk)
    _attach_display_status(req, context="detail")

    can_take_hou_action = (
        viewed_officer == request.user and req.raw_status == "PENDING_HOU"
    )
    is_view_only = req.raw_status in ["APPROVED", "CLOSED", "PENDING_DIRECTOR", "REJECTED_HOU", "REJECTED_DIRECTOR", "RETURNED_HOU", "RETURNED_DIRECTOR"]

    if request.method == "POST":
        if viewed_officer != request.user:
            return HttpResponseForbidden("Administrator access is view-only.")
        if req.status != "PENDING_HOU":
            return HttpResponseForbidden("Only pending Head of Unit requests can be acted on.")

        action = _normalize_action(request.POST.get("action"))
        hou_comment = (request.POST.get("hou_comment") or "").strip()

        if action in ["approve", "approved"]:
            req.hou_comment = hou_comment
            req.hou_approved_by = request.user
            req.hou_approved_at = timezone.now()

            requester_profile = _get_profile(req.requester)
            assistant_director = get_assistant_director_for_unit(
                department=requester_profile.department,
                department_unit=(
                    requester_profile.department_unit
                ),
                unit_name=requester_profile.unit_name,
            )

            req.director = (
                assistant_director
                or get_director_user(
                    department=requester_profile.department
                )
            )
            req.status = "PENDING_DIRECTOR"
            req.save()

            notify_director(req)
            next_approver_label = (
                "Assistant Director"
                if assistant_director
                else "Director"
            )
            notify_requester(
                req,
                "approved by Head of Unit and forwarded to "
                f"{next_approver_label}"
            )
            log_action(
                user=request.user,
                action="APPROVE",
                module="PERMIT",
                reference_no=req.reference_no,
                description=(
                    "Permit approved by Head of Unit and forwarded to "
                    f"{next_approver_label}."
                ),
                request=request,
            )

            messages.success(
                request,
                "Request approved and forwarded to "
                f"{next_approver_label}."
            )
            return redirect("head_of_unit_requests")

        elif action in ["return", "returned"]:
            if not hou_comment:
                messages.error(request, "Please provide a reason for return.")
                _attach_display_status(req, context="detail")
                return render(
                    request,
                    "permits/head_of_unit_request_detail.html",
                    {
                        "req": req,
                        "can_take_hou_action": can_take_hou_action,
                        "is_view_only": is_view_only,
                    }
                )

            req.hou_comment = hou_comment
            req.returned_at = timezone.now()
            req.status = "RETURNED_HOU"
            req.save()

            notify_requester(req, "returned by Head of Unit for correction")
            log_action(
                user=request.user,
                action="RETURN",
                module="PERMIT",
                reference_no=req.reference_no,
                description="Permit returned by Head of Unit.",
                request=request,
            )

            messages.success(request, "Request returned to requester.")
            return redirect("head_of_unit_requests")

        elif action in ["reject", "rejected"]:
            if not hou_comment:
                messages.error(request, "Please provide a rejection reason.")
                _attach_display_status(req, context="detail")
                return render(
                    request,
                    "permits/head_of_unit_request_detail.html",
                    {
                        "req": req,
                        "can_take_hou_action": can_take_hou_action,
                        "is_view_only": is_view_only,
                    }
                )

            req.hou_comment = hou_comment
            req.rejected_by = request.user
            req.rejected_by_role = profile.role
            req.rejected_at = timezone.now()
            req.status = "REJECTED_HOU"
            req.save()

            notify_requester(req, "rejected by Head of Unit")
            log_action(
                user=request.user,
                action="REJECT",
                module="PERMIT",
                reference_no=req.reference_no,
                description="Permit rejected by Head of Unit.",
                request=request,
            )

            messages.success(request, "Request rejected.")
            return redirect("head_of_unit_requests")

        else:
            messages.error(request, "Invalid action selected.")
            _attach_display_status(req, context="detail")
            return render(
                request,
                "permits/head_of_unit_request_detail.html",
                {
                    "req": req,
                    "can_take_hou_action": can_take_hou_action,
                    "is_view_only": is_view_only,
                }
            )

    return render(
        request,
        "permits/head_of_unit_request_detail.html",
        {
            "req": req,
            "can_take_hou_action": can_take_hou_action,
            "is_view_only": is_view_only,
        }
    )


# ---------------------------------------------------------------------
# Assistant Directors  have their own Assistant Director dashboard.
# ---------------------------------------------------------------------

@login_required
@require_role(
    "ADMIN",
    "DIRECTOR",
    "ASSISTANT_DIRECTOR",
)
def director_requests(request):
    """
    Request review and processing list.

    Accessible to:
    - Director
    - Assistant Director

    Requests remain restricted to the logged-in user's
    department and, where applicable, department unit.
    """
    profile = _get_profile(request.user)

    if not _director_level_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    status = request.GET.get("status")
    now = timezone.now()
    visible_requests = _director_scope_queryset(
        request.user,
        ExternalWorkRequest.objects.exclude(status="PENDING_HOU")
    )
    admin_scope_query = ""
    if _admin_allowed(request.user) and request.GET.get("officer"):
        viewed_officer = get_object_or_404(
            User.objects.select_related(
                "profile__department", "profile__department_unit"
            ).filter(
                Q(profile__role__in=["DIRECTOR", "ASSISTANT_DIRECTOR"])
                | Q(profile__approval_role__code__in=[
                    "DIRECTOR", "ASSISTANT_DIRECTOR"
                ])
            ),
            pk=request.GET.get("officer"),
            is_active=True,
        )
        officer_profile = viewed_officer.profile
        officer_role = (
            officer_profile.approval_role.code
            if officer_profile.approval_role_id
            else officer_profile.role
        )
        admin_scope_query = f"officer={viewed_officer.pk}"
        visible_requests = visible_requests.filter(
            requester__profile__department_id=officer_profile.department_id
        )
        if (
            officer_role == "ASSISTANT_DIRECTOR"
            and officer_profile.department_unit_id
        ):
            visible_requests = visible_requests.filter(
                requester__profile__department_unit_id=(
                    officer_profile.department_unit_id
                )
            )
    elif _admin_allowed(request.user) and request.GET.get("department"):
        selected_department = get_object_or_404(
            Department, pk=request.GET.get("department"), is_active=True
        )
        visible_requests = visible_requests.filter(
            requester__profile__department=selected_department
        )
        admin_scope_query = f"department={selected_department.pk}"

    if status == "OVERDUE":
        requests = visible_requests.filter(
            end_time__lt=now
        ).exclude(
            status__in=["CLOSED"] + _rejected_statuses()
        )
    elif status in ["PENDING", "PENDING_DIRECTOR"]:
        requests = visible_requests.filter(status="PENDING_DIRECTOR")
    elif status in ["RETURNED", "RETURNED_HOU", "RETURNED_DIRECTOR"]:
        requests = visible_requests.filter(status__in=_returned_statuses())
    elif status in ["REJECTED", "REJECTED_HOU", "REJECTED_DIRECTOR"]:
        requests = visible_requests.filter(status__in=_rejected_statuses())
    elif status in ["APPROVED", "CLOSED"]:
        requests = visible_requests.filter(status=status)
    elif _is_total_status(status):
        requests = visible_requests
    else:
        requests = visible_requests.filter(status=status)

    requests = requests.order_by("-updated_at")
    requests = _attach_display_status_list(requests, context="list")

    total_requests = visible_requests.count()
    pending_director_count = visible_requests.filter(status="PENDING_DIRECTOR").count()
    returned_count = visible_requests.filter(status__in=_returned_statuses()).count()
    approved_count = visible_requests.filter(status="APPROVED").count()
    rejected_count = visible_requests.filter(status__in=_rejected_statuses()).count()
    closed_count = visible_requests.filter(status="CLOSED").count()
    overdue_count = visible_requests.filter(
        end_time__lt=now
    ).exclude(
        status__in=["CLOSED"] + _rejected_statuses()
    ).count()

    welcome_name = request.user.get_full_name().strip() or request.user.username

    return render(
        request,
        "permits/director_requests.html",
        {
            "requests": requests,
            "selected_status": status,
            "total_requests": total_requests,
            "pending_director_count": pending_director_count,
            "returned_count": returned_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "closed_count": closed_count,
            "overdue_count": overdue_count,
            "welcome_name": welcome_name,
            "admin_scope_query": admin_scope_query,
        }
    )


@login_required
@require_role(
    "DIRECTOR",
    "ASSISTANT_DIRECTOR",
)
def director_request_detail(request, pk):
    """
    Review a request assigned to a Director or Assistant Director.

    A unit Assistant Director may act only on requests from that exact
    unit. When approving a request that bypassed a missing HOU, the
    Assistant Director forwards it to the department Director; only the
    Director performs the final approval.
    """
    profile = _get_profile(request.user)
    role = _get_user_role(request.user)

    if not _director_level_allowed(request.user):
        return HttpResponseForbidden("Not allowed.")

    req = get_object_or_404(
        ExternalWorkRequest.objects.prefetch_related("members", "requester__profile"),
        pk=pk
    )

    if not _director_can_access_request(request.user, req):
        return HttpResponseForbidden("You are not allowed to access requests from another department.")

    if req.status == "PENDING_HOU":
        return HttpResponseForbidden("This request is still under Head of Unit review.")

    _attach_display_status(req, context="detail")

    is_assigned_approver = (
        req.director_id == request.user.id
    )

    can_take_director_action = (
        req.raw_status == "PENDING_DIRECTOR"
        and is_assigned_approver
    )
    is_view_only = req.raw_status in ["APPROVED", "CLOSED"]

    if request.method == "POST":
        if req.status != "PENDING_DIRECTOR":
            return HttpResponseForbidden("Only pending Director requests can be acted on.")

        if not is_assigned_approver:
            return HttpResponseForbidden(
                "This request is assigned to another approver."
            )

        posted_action = request.POST.get("directorActionField")
        if posted_action is not None:
            validated_action = _validate_director_action_value(posted_action)
        else:
            validated_action = None

        form = DirectorDecisionForm(request.POST, instance=req)

        if form.is_valid():
            req = form.save(commit=False)

            if validated_action == "approve" and req.status != "APPROVED":
                raise PermissionDenied("Invalid action attempted.")
            if validated_action == "reject" and req.status != "REJECTED_DIRECTOR":
                raise PermissionDenied("Invalid action attempted.")
            if validated_action == "return" and req.status != "RETURNED_DIRECTOR":
                raise PermissionDenied("Invalid action attempted.")

            if (
                role == "ASSISTANT_DIRECTOR"
                and req.status == "APPROVED"
            ):
                department_director = get_director_user(
                    department=profile.department
                )

                if not department_director:
                    form.add_error(
                        None,
                        "No active Director is assigned to your department."
                    )
                    _attach_display_status(req, context="detail")
                    return render(
                        request,
                        "permits/director_request_detail.html",
                        {
                            "req": req,
                            "form": form,
                            "can_take_director_action": (
                                can_take_director_action
                            ),
                            "is_view_only": is_view_only,
                        }
                    )

                # Reuse the existing intermediate-approval fields so
                # no model or migration change is required. The stored
                # approver's standardized role still identifies this as
                # an Assistant Director approval in exports/permits.
                assistant_director_comment = (
                    req.director_comment or ""
                ).strip()

                req.hou_comment = assistant_director_comment
                req.hou_approved_by = request.user
                req.hou_approved_at = timezone.now()

                # The Director must receive a fresh decision field.
                # Keeping the Assistant Director's text here would
                # prefill the Director's form and mix the two decisions.
                req.director_comment = ""
                req.director = department_director
                req.status = "PENDING_DIRECTOR"
                req.save()

                notify_director(req)
                notify_requester(
                    req,
                    "approved by the Assistant Director and forwarded "
                    "to the Director"
                )
                log_action(
                    user=request.user,
                    action="APPROVE",
                    module="PERMIT",
                    reference_no=req.reference_no,
                    description=(
                        "Permit approved by Assistant Director and "
                        "forwarded to Department Director."
                    ),
                    request=request,
                )

                messages.success(
                    request,
                    "Request approved and forwarded to the Director."
                )
                return redirect("director_requests")

            if req.status == "RETURNED_DIRECTOR":
                req.returned_at = timezone.now()

                if not req.director_comment.strip():
                    form.add_error("director_comment", "Please provide a reason for return.")
                    _attach_display_status(req, context="detail")
                    return render(
                        request,
                        "permits/director_request_detail.html",
                        {
                            "req": req,
                            "form": form,
                            "can_take_director_action": can_take_director_action,
                            "is_view_only": is_view_only,
                        }
                    )

                req.save()
                notify_requester(req, "returned by Director for correction")
                messages.success(request, "Request returned to requester.")
                return redirect("director_requests")

            if req.status == "APPROVED":
                req.director_approved_by = request.user
                req.director_approved_at = timezone.now()
                req.save()

                notify_requester(req, "approved by Director")
                messages.success(request, "Request approved successfully.")
                return redirect("director_requests")

            if req.status == "REJECTED_DIRECTOR":
                if not (req.director_comment or "").strip():
                    form.add_error("director_comment", "Please provide a rejection reason.")
                    _attach_display_status(req, context="detail")
                    return render(
                        request,
                        "permits/director_request_detail.html",
                        {
                            "req": req,
                            "form": form,
                            "can_take_director_action": can_take_director_action,
                            "is_view_only": is_view_only,
                        }
                    )

                req.rejected_by = request.user
                req.rejected_by_role = profile.role
                req.rejected_at = timezone.now()
                req.save()

                notify_requester(req, "rejected by Director")
                messages.success(request, "Request rejected.")
                return redirect("director_requests")

    else:
        form = DirectorDecisionForm(instance=req)

    return render(
        request,
        "permits/director_request_detail.html",
        {
            "req": req,
            "form": form,
            "can_take_director_action": can_take_director_action,
            "is_view_only": is_view_only,
        }
    )

def _get_report_base_queryset(user):
    """
    Return Permit reports according to the user's organizational scope.

    - ADMIN: all departments
    - DIRECTOR / ASSISTANT_DIRECTOR: own department
    - HEAD_OF_UNIT: own unit or assigned requests
    """
    profile = _get_profile(user)
    role = _get_user_role(user)

    qs = ExternalWorkRequest.objects.select_related(
        "requester",
        "requester__profile",
        "requester__profile__department",
        "requester__profile__department_unit",
        "head_of_unit",
        "director",
        "hou_approved_by",
        "director_approved_by",
    ).all()

    if role == "ADMIN":
        return qs

    if role in [
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]:
        if not profile.department_id:
            return qs.none()

        return qs.filter(
            requester__profile__department_id=(
                profile.department_id
            )
        )

    if role == "HEAD_OF_UNIT":
        if profile.department_unit_id:
            return qs.filter(
                Q(
                    requester__profile__department_unit_id=(
                        profile.department_unit_id
                    )
                )
                | Q(head_of_unit=user)
            ).distinct()

        if profile.unit_name:
            return qs.filter(
                Q(
                    requester__profile__unit_name=(
                        profile.unit_name
                    )
                )
                | Q(head_of_unit=user)
            ).distinct()

        return qs.filter(
            head_of_unit=user
        )

    return qs.none()


def _apply_admin_report_scope(user, request, queryset):
    """Apply the department/unit selected from the Administration Centre."""
    if not _admin_allowed(user):
        return queryset, None, None, ""

    department = None
    department_unit = None
    scope_query = ""
    officer_id = request.GET.get("officer", "").strip()
    department_id = request.GET.get("department", "").strip()
    if officer_id:
        officer = get_object_or_404(
            User.objects.select_related(
                "profile__department", "profile__department_unit",
                "profile__approval_role",
            ).filter(
                Q(profile__role__in=["DIRECTOR", "ASSISTANT_DIRECTOR"])
                | Q(profile__approval_role__code__in=[
                    "DIRECTOR", "ASSISTANT_DIRECTOR"
                ])
            ),
            pk=officer_id,
            is_active=True,
        )
        officer_profile = officer.profile
        officer_role = (
            officer_profile.approval_role.code
            if officer_profile.approval_role_id
            else officer_profile.role
        )
        department = officer_profile.department
        if officer_role == "ASSISTANT_DIRECTOR":
            department_unit = officer_profile.department_unit
        scope_query = f"officer={officer.pk}"
    elif department_id:
        department = get_object_or_404(
            Department, pk=department_id, is_active=True
        )
        scope_query = f"department={department.pk}"

    if department:
        queryset = queryset.filter(
            requester__profile__department_id=department.pk
        )
    if department_unit:
        queryset = queryset.filter(
            requester__profile__department_unit_id=department_unit.pk
        )
    return queryset, department, department_unit, scope_query

@login_required
@require_role(
    "DIRECTOR",
    "ASSISTANT_DIRECTOR",
    "ADMIN",
    "HEAD_OF_UNIT",
)
def permit_reports(request):
    role = _get_user_role(request.user)
    profile = _get_profile(request.user)

    if role not in [
        "ADMIN",
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
        "HEAD_OF_UNIT",
    ]:
        return HttpResponseForbidden("Not allowed.")

    now = timezone.now()

    base_qs = _get_report_base_queryset(request.user)
    base_qs, scoped_department, scoped_unit, admin_scope_query = (
        _apply_admin_report_scope(request.user, request, base_qs)
    )

    base_qs = _apply_permit_report_filters(base_qs, request)

    total_requests = base_qs.count()
    pending_hou = base_qs.filter(status="PENDING_HOU").count()
    pending_director = base_qs.filter(status="PENDING_DIRECTOR").count()
    approved = base_qs.filter(status="APPROVED").count()
    closed = base_qs.filter(status="CLOSED").count()
    rejected = base_qs.filter(status__in=_rejected_statuses()).count()
    returned = base_qs.filter(status__in=_returned_statuses()).count()

    overdue_qs = base_qs.filter(
        end_time__lt=now
    ).exclude(
        status__in=["CLOSED"] + _rejected_statuses()
    )

    approved_not_closed_qs = base_qs.filter(status="APPROVED")

    approved_expired_not_closed_qs = approved_not_closed_qs.filter(
        end_time__lt=now
    )

    completed_approval_qs = base_qs.filter(
        hou_approved_at__isnull=False,
        director_approved_at__isnull=False
    ).annotate(
        hou_turnaround=ExpressionWrapper(
            F("hou_approved_at") - F("created_at"),
            output_field=DurationField()
        ),
        director_turnaround=ExpressionWrapper(
            F("director_approved_at") - F("hou_approved_at"),
            output_field=DurationField()
        ),
        total_turnaround=ExpressionWrapper(
            F("director_approved_at") - F("created_at"),
            output_field=DurationField()
        )
    )

    avg_data = completed_approval_qs.aggregate(
        avg_hou=Avg("hou_turnaround"),
        avg_director=Avg("director_turnaround"),
        avg_total=Avg("total_turnaround"),
    )

    turnaround_rows = []
    for r in completed_approval_qs.order_by("-director_approved_at")[:100]:
        turnaround_rows.append({
            "reference_no": r.reference_no,
            "requester_name": r.requester_name,
            "destination": r.destination,
            "created_at": r.created_at,
            "hou_approved_at": r.hou_approved_at,
            "director_approved_at": r.director_approved_at,
            "hou_turnaround": _format_duration(r.hou_turnaround),
            "director_turnaround": _format_duration(r.director_turnaround),
            "total_turnaround": _format_duration(r.total_turnaround),
        })

    overdue_rows = []
    for r in overdue_qs.order_by("end_time")[:100]:
        days_overdue = (now.date() - r.end_time.date()).days if r.end_time else 0
        overdue_rows.append({
            "reference_no": r.reference_no,
            "requester_name": r.requester_name,
            "destination": r.destination,
            "status": _resolve_display_status(r, context="list"),
            "end_time": r.end_time,
            "days_overdue": days_overdue,
            "responsible": (
                "Head of Unit" if r.status == "PENDING_HOU"
                else "Director" if r.status == "PENDING_DIRECTOR"
                else "Requester / Closure Action"
            ),
        })

    compliance_rows = []
    for r in approved_not_closed_qs.order_by("end_time")[:100]:
        is_expired = r.end_time and r.end_time < now
        compliance_rows.append({
            "reference_no": r.reference_no,
            "requester_name": r.requester_name,
            "destination": r.destination,
            "end_time": r.end_time,
            "report_uploaded": "Yes" if r.report_file else "No",
            "risk": "Expired but not closed" if is_expired else "Approved and active",
        })

    workload_by_unit = base_qs.values(
        "requester__profile__unit_name"
    ).annotate(
        total=Count("id"),
        approved=Count("id", filter=Q(status="APPROVED")),
        closed=Count("id", filter=Q(status="CLOSED")),
        pending_hou=Count("id", filter=Q(status="PENDING_HOU")),
        pending_director=Count("id", filter=Q(status="PENDING_DIRECTOR")),
        rejected=Count("id", filter=Q(status__in=_rejected_statuses())),
        returned=Count("id", filter=Q(status__in=_returned_statuses())),
    ).order_by("-total")

    workload_by_hou = base_qs.values(
        "head_of_unit__first_name",
        "head_of_unit__last_name",
        "head_of_unit__username",
    ).annotate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="PENDING_HOU")),
        forwarded=Count("id", filter=Q(status="PENDING_DIRECTOR")),
        approved=Count("id", filter=Q(status="APPROVED")),
        closed=Count("id", filter=Q(status="CLOSED")),
    ).order_by("-total")

    role = _get_user_role(request.user)

    is_director_level = role in [
        "ADMIN",
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]

    unit_profiles = (
        UserProfile.objects
        .exclude(unit_name__isnull=True)
        .exclude(unit_name="")
    )

    requester_options = User.objects.filter(
        work_requests__isnull=False
    )

    if role == "ADMIN" and scoped_department:
        unit_profiles = unit_profiles.filter(department=scoped_department)
        requester_options = requester_options.filter(
            profile__department=scoped_department
        )
        if scoped_unit:
            unit_profiles = unit_profiles.filter(department_unit=scoped_unit)
            requester_options = requester_options.filter(
                profile__department_unit=scoped_unit
            )

    if role in [
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]:
        if profile.department_id:
            unit_profiles = unit_profiles.filter(
                department_id=profile.department_id
            )
            requester_options = requester_options.filter(
                profile__department_id=profile.department_id
            )
        else:
            unit_profiles = unit_profiles.none()
            requester_options = requester_options.none()

    elif role == "HEAD_OF_UNIT":
        if profile.department_unit_id:
            unit_profiles = unit_profiles.filter(
                department_unit_id=profile.department_unit_id
            )
            requester_options = requester_options.filter(
                profile__department_unit_id=profile.department_unit_id
            )
        elif profile.unit_name:
            unit_profiles = unit_profiles.filter(
                unit_name=profile.unit_name
            )
            requester_options = requester_options.filter(
                profile__unit_name=profile.unit_name
            )
        else:
            unit_profiles = unit_profiles.none()
            requester_options = requester_options.none()

    unit_options = (
        unit_profiles
        .values_list("unit_name", flat=True)
        .distinct()
        .order_by("unit_name")
    )

    requester_options = (
        requester_options
        .distinct()
        .order_by("first_name", "last_name", "username")
    )

    status_options = [
        ("PENDING_HOU", "Pending HOU"),
        ("PENDING_DIRECTOR", "Pending Director"),
        ("APPROVED", "Approved"),
        ("CLOSED", "Closed"),
        ("RETURNED_HOU", "Returned by HOU"),
        ("RETURNED_DIRECTOR", "Returned by Director"),
        ("REJECTED_HOU", "Rejected by HOU"),
        ("REJECTED_DIRECTOR", "Rejected by Director"),
    ]




    context = {
        "total_requests": total_requests,
        "pending_hou": pending_hou,
        "pending_director": pending_director,
        "approved": approved,
        "closed": closed,
        "rejected": rejected,
        "returned": returned,
        "overdue_count": overdue_qs.count(),
        "approved_not_closed_count": approved_not_closed_qs.count(),
        "approved_expired_not_closed_count": approved_expired_not_closed_qs.count(),

        "approval_rate": _percent(approved + closed, total_requests),
        "rejection_rate": _percent(rejected, total_requests),
        "return_rate": _percent(returned, total_requests),

        "avg_hou": _format_duration(avg_data["avg_hou"]),
        "avg_director": _format_duration(avg_data["avg_director"]),
        "avg_total": _format_duration(avg_data["avg_total"]),

        "turnaround_rows": turnaround_rows,
        "overdue_rows": overdue_rows,
        "compliance_rows": compliance_rows,
        "workload_by_unit": workload_by_unit,
        "workload_by_hou": workload_by_hou,

        "is_director_level": is_director_level,
        "unit_options": unit_options,
        "requester_options": requester_options,
        "status_options": status_options,
        
        "selected_start_date": request.GET.get("start_date", ""),
        "selected_end_date": request.GET.get("end_date", ""),
        "selected_status": request.GET.get("status", ""),
        "selected_unit": request.GET.get("unit", ""),
        "selected_requester": request.GET.get("requester", ""),
        "admin_scope_query": admin_scope_query,
        "scoped_department": scoped_department,
        "scoped_unit": scoped_unit,
    }

    return render(request, "permits/permit_reports.html", context)

@login_required
@require_role(
    "DIRECTOR",
    "ASSISTANT_DIRECTOR",
    "ADMIN",
    "HEAD_OF_UNIT",
)
def export_permit_reports_excel(request):
    """
    Export Permit reports with every datetime converted explicitly
    to Tanzania time and displayed using the 24-hour clock.
    """
    report_type = request.GET.get(
        "report",
        "performance",
    )

    now = timezone.now()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Permit Reports"

    ws.append([
        "Permit Decision-Making Report"
    ])

    ws.append([
        "Report Type",
        report_type,
    ])

    ws.append([
        "Generated At",
        _format_local_datetime(now),
    ])

    ws.append([])

    qs = _get_report_base_queryset(
        request.user
    )
    qs, _scoped_department, _scoped_unit, _scope_query = (
        _apply_admin_report_scope(request.user, request, qs)
    )

    qs = _apply_permit_report_filters(
        qs,
        request,
    )

    if report_type == "turnaround":
        ws.append([
            "Reference No",
            "Requester",
            "Created/Submitted At",
            "HOU Approved At",
            "Director Approved At",
            "Status",
        ])

        data = qs.filter(
            director_approved_at__isnull=False
        )

        for permit_request in data:
            ws.append([
                permit_request.reference_no,
                permit_request.requester_name,
                _format_local_datetime(
                    permit_request.created_at
                ),
                _format_local_datetime(
                    permit_request.hou_approved_at
                ),
                _format_local_datetime(
                    permit_request.director_approved_at
                ),
                permit_request.status,
            ])

    elif report_type == "overdue":
        ws.append([
            "Reference No",
            "Requester",
            "Destination",
            "End Time",
            "Status",
        ])

        data = qs.filter(
            end_time__lt=now
        ).exclude(
            status__in=[
                "CLOSED",
            ] + _rejected_statuses()
        )

        for permit_request in data:
            ws.append([
                permit_request.reference_no,
                permit_request.requester_name,
                permit_request.destination,
                _format_local_datetime(
                    permit_request.end_time
                ),
                permit_request.status,
            ])

    elif report_type == "compliance":
        ws.append([
            "Reference No",
            "Requester",
            "Destination",
            "End Time",
            "Report Uploaded",
            "Status",
        ])

        data = qs.filter(
            status="APPROVED",
            end_time__lt=now,
        )

        for permit_request in data:
            ws.append([
                permit_request.reference_no,
                permit_request.requester_name,
                permit_request.destination,
                _format_local_datetime(
                    permit_request.end_time
                ),
                (
                    "Yes"
                    if permit_request.report_file
                    else "No"
                ),
                permit_request.status,
            ])

    elif report_type == "workload":
        ws.append([
            "Unit",
            "Total",
            "Approved/Closed",
            "Pending",
            "Returned",
            "Rejected",
        ])

        data = (
            qs.values(
                "unit_name"
            )
            .annotate(
                total=Count("id"),
                approved=Count(
                    "id",
                    filter=Q(
                        status__in=[
                            "APPROVED",
                            "CLOSED",
                        ]
                    ),
                ),
                pending=Count(
                    "id",
                    filter=Q(
                        status__in=[
                            "PENDING_HOU",
                            "PENDING_DIRECTOR",
                        ]
                    ),
                ),
                returned=Count(
                    "id",
                    filter=Q(
                        status__in=(
                            _returned_statuses()
                        )
                    ),
                ),
                rejected=Count(
                    "id",
                    filter=Q(
                        status__in=(
                            _rejected_statuses()
                        )
                    ),
                ),
            )
            .order_by("-total")
        )

        for row in data:
            ws.append([
                row["unit_name"]
                or "Not Assigned",
                row["total"],
                row["approved"],
                row["pending"],
                row["returned"],
                row["rejected"],
            ])

    else:
        ws.append([
            "Metric",
            "Value",
        ])

        ws.append([
            "Total Requests",
            qs.count(),
        ])

        ws.append([
            "Approved",
            qs.filter(
                status="APPROVED"
            ).count(),
        ])

        ws.append([
            "Closed",
            qs.filter(
                status="CLOSED"
            ).count(),
        ])

        ws.append([
            "Pending HOU",
            qs.filter(
                status="PENDING_HOU"
            ).count(),
        ])

        ws.append([
            "Pending Director",
            qs.filter(
                status="PENDING_DIRECTOR"
            ).count(),
        ])

        ws.append([
            "Returned",
            qs.filter(
                status__in=_returned_statuses()
            ).count(),
        ])

        ws.append([
            "Rejected",
            qs.filter(
                status__in=_rejected_statuses()
            ).count(),
        ])

    for column_cells in ws.columns:
        maximum_length = max(
            (
                len(str(cell.value))
                if cell.value is not None
                else 0
            )
            for cell in column_cells
        )

        ws.column_dimensions[
            column_cells[0].column_letter
        ].width = min(
            maximum_length + 3,
            50,
        )

    response = HttpResponse(
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )

    response["Content-Disposition"] = (
        f'attachment; filename="permit_{report_type}_report.xlsx"'
    )

    wb.save(response)

    return response


@login_required
@require_role(
    "DIRECTOR",
    "ASSISTANT_DIRECTOR",
    "ADMIN",
    "HEAD_OF_UNIT",
)
def export_permit_reports_pdf(request):
    report_type = request.GET.get("report", "performance")
    now = timezone.now()

    qs = _get_report_base_queryset(request.user)
    qs, scoped_department, scoped_unit, _scope_query = (
        _apply_admin_report_scope(request.user, request, qs)
    )
    qs = _apply_permit_report_filters(qs, request)

    profile = _get_profile(request.user)
    role = _get_user_role(request.user)

    if role == "ADMIN":
        if scoped_unit:
            report_scope = f"Unit: {scoped_unit.name}"
        elif scoped_department:
            report_scope = f"Department: {scoped_department.name}"
        else:
            report_scope = "All Departments"
    elif role in [
        "DIRECTOR",
        "ASSISTANT_DIRECTOR",
    ]:
        department_name = (
            profile.department.name
            if profile.department
            else "Not Assigned"
        )
        report_scope = f"Department: {department_name}"
    elif role == "HEAD_OF_UNIT":
        if profile.department_unit:
            report_scope = f"Unit: {profile.department_unit.name}"
        else:
            report_scope = f"Unit: {profile.unit_name or 'Not Assigned'}"
    else:
        report_scope = "Restricted"

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="permit_{report_type}_report.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=25,
        leftMargin=25,
        topMargin=30,
        bottomMargin=30
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#084298"),
        spaceAfter=8,
    )

    normal_style = ParagraphStyle(
        "NormalSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        alignment=TA_LEFT,
    )

    note_style = ParagraphStyle(
        "NoteStyle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#374151"),
        spaceAfter=8,
    )

    elements = []

    elements.append(Paragraph("Permit Decision-Making Report", title_style))
    elements.append(Paragraph(f"<b>Report Type:</b> {report_type.title()}", normal_style))
    elements.append(Paragraph(f"<b>Generated At:</b> {_format_local_datetime(now)}", normal_style))
    elements.append(Paragraph(f"<b>Generated By:</b> {request.user.get_full_name() or request.user.username}", normal_style))
    elements.append(Paragraph(f"<b>Report Scope:</b> {report_scope}", normal_style))
    elements.append(Spacer(1, 10))

    if report_type == "turnaround":
        elements.append(Paragraph(
            "This report shows the time taken from submission to Head of Unit approval and final Director-level approval.",
            note_style
        ))

        data = [[
            "Reference No", "Requester", "Destination", "Created At",
            "HOU Approved", "Director Approved", "HOU Time", "Director Time", "Total Time"
        ]]

        records = qs.filter(
            hou_approved_at__isnull=False,
            director_approved_at__isnull=False
        ).annotate(
            hou_turnaround=ExpressionWrapper(
                F("hou_approved_at") - F("created_at"),
                output_field=DurationField()
            ),
            director_turnaround=ExpressionWrapper(
                F("director_approved_at") - F("hou_approved_at"),
                output_field=DurationField()
            ),
            total_turnaround=ExpressionWrapper(
                F("director_approved_at") - F("created_at"),
                output_field=DurationField()
            )
        ).order_by("-director_approved_at")

        for r in records:
            data.append([
                r.reference_no or "",
                r.requester_name or "",
                r.destination or "",
                _format_local_datetime(r.created_at),
                _format_local_datetime(r.hou_approved_at, empty_value="N/A"),
                _format_local_datetime(r.director_approved_at, empty_value="N/A"),
                _format_duration(r.hou_turnaround),
                _format_duration(r.director_turnaround),
                _format_duration(r.total_turnaround),
            ])

    elif report_type == "overdue":
        elements.append(Paragraph(
            "This report identifies permits whose end time has passed but are not yet closed or rejected.",
            note_style
        ))

        data = [[
            "Reference No", "Requester", "Destination", "End Time",
            "Days Overdue", "Responsible", "Status"
        ]]

        records = qs.filter(
            end_time__lt=now
        ).exclude(
            status__in=["CLOSED"] + _rejected_statuses()
        ).order_by("end_time")

        for r in records:
            days_overdue = (now.date() - r.end_time.date()).days if r.end_time else 0
            responsible = (
                "Head of Unit" if r.status == "PENDING_HOU"
                else "Director" if r.status == "PENDING_DIRECTOR"
                else "Requester / Closure Action"
            )

            data.append([
                r.reference_no or "",
                r.requester_name or "",
                r.destination or "",
                _format_local_datetime(r.end_time),
                days_overdue,
                responsible,
                _resolve_display_status(r, context="list"),
            ])

    elif report_type == "compliance":
        elements.append(Paragraph(
            "This report shows approved permits that are still not closed and helps follow up report submission and closure.",
            note_style
        ))

        data = [[
            "Reference No", "Requester", "Destination", "End Time",
            "Report Uploaded", "Risk"
        ]]

        records = qs.filter(status="APPROVED").order_by("end_time")

        for r in records:
            is_expired = r.end_time and r.end_time < now

            data.append([
                r.reference_no or "",
                r.requester_name or "",
                r.destination or "",
                _format_local_datetime(r.end_time),
                "Yes" if r.report_file else "No",
                "Expired but not closed" if is_expired else "Approved and active",
            ])

    elif report_type == "workload":
        elements.append(Paragraph(
            "This report shows workload distribution by unit and approval status.",
            note_style
        ))

        data = [[
            "Unit", "Total", "Approved", "Closed",
            "Pending HOU", "Pending Director", "Returned", "Rejected"
        ]]

        records = qs.values(
            "requester__profile__unit_name"
        ).annotate(
            total=Count("id"),
            approved=Count("id", filter=Q(status="APPROVED")),
            closed=Count("id", filter=Q(status="CLOSED")),
            pending_hou=Count("id", filter=Q(status="PENDING_HOU")),
            pending_director=Count("id", filter=Q(status="PENDING_DIRECTOR")),
            returned=Count("id", filter=Q(status__in=_returned_statuses())),
            rejected=Count("id", filter=Q(status__in=_rejected_statuses())),
        ).order_by("-total")

        for r in records:
            data.append([
                r["requester__profile__unit_name"] or "Not Assigned",
                r["total"],
                r["approved"],
                r["closed"],
                r["pending_hou"],
                r["pending_director"],
                r["returned"],
                r["rejected"],
            ])

    else:
        total_requests = qs.count()
        approved = qs.filter(status="APPROVED").count()
        closed = qs.filter(status="CLOSED").count()
        pending_hou = qs.filter(status="PENDING_HOU").count()
        pending_director = qs.filter(status="PENDING_DIRECTOR").count()
        returned = qs.filter(status__in=_returned_statuses()).count()
        rejected = qs.filter(status__in=_rejected_statuses()).count()

        elements.append(Paragraph(
            "This summary shows the overall permit processing performance for decision-making.",
            note_style
        ))

        data = [
            ["Indicator", "Value"],
            ["Total Requests", total_requests],
            ["Approved", approved],
            ["Closed", closed],
            ["Pending HOU", pending_hou],
            ["Pending Director", pending_director],
            ["Returned", returned],
            ["Rejected", rejected],
            ["Approval Rate", f"{_percent(approved + closed, total_requests)}%"],
            ["Rejection Rate", f"{_percent(rejected, total_requests)}%"],
            ["Return Rate", f"{_percent(returned, total_requests)}%"],
        ]

    if len(data) == 1:
        data.append(["No records found"] + [""] * (len(data[0]) - 1))

    table_data = []
    for row in data:
        table_data.append([
            Paragraph(str(cell), normal_style) for cell in row
        ])

    table = Table(table_data, repeatRows=1, hAlign="LEFT")

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b5ed7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),

        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),

        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),

        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    elements.append(table)

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        page_text = f"Page {doc.page}"
        canvas.drawRightString(landscape(A4)[0] - 25, 18, page_text)
        canvas.drawString(25, 18, "Permit Decision-Making Report")
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)

    return response
