from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import transaction
from django.utils import timezone

from permits.models import DepartmentApprovalWorkflow, UserProfile


FINANCE_MODULE_CODE = "FINANCE"

CENTRAL_APPROVAL_ROLES = {
    "DIVISION_BUDGET_OFFICER",
    "ACCOUNTANT",
    "SYSTEM_ADMIN",
}


def get_user_profile(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None

    for attribute in ("profile", "userprofile"):
        try:
            profile = getattr(user, attribute)
        except (AttributeError, ObjectDoesNotExist):
            profile = None

        if profile:
            return profile

    return None


def get_user_approval_role_code(user):
    if not user:
        return None

    if getattr(user, "is_superuser", False):
        return "SYSTEM_ADMIN"

    profile = get_user_profile(user)

    if not profile or not profile.approval_role:
        return None

    return (profile.approval_role.code or "").strip().upper() or None


def get_department_workflow(department, module_code):
    if not department or not module_code:
        return DepartmentApprovalWorkflow.objects.none()

    return (
        DepartmentApprovalWorkflow.objects.filter(
            department=department,
            module=module_code,
            is_active=True,
            is_required=True,
        )
        .select_related("approval_role", "department")
        .order_by("step_order", "id")
    )


def get_first_approval_step_after_requester(department, module_code):
    for step in get_department_workflow(department, module_code):
        if step.approval_role.code != "REQUESTER":
            return step

    return None


def find_approver(
    department,
    department_unit,
    approval_role_code,
    exclude_user=None,
):
    if not approval_role_code:
        return None

    role_code = approval_role_code.strip().upper()

    base_qs = (
        UserProfile.objects.filter(
            approval_role__code=role_code,
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

    if exclude_user:
        base_qs = base_qs.exclude(
            user=exclude_user
        )

    # Head of Unit must belong to the exact department unit.
    if role_code == "HEAD_OF_UNIT":
        if not department or not department_unit:
            return None

        unit_profile = base_qs.filter(
            department=department,
            department_unit=department_unit,
        ).first()

        return (
            unit_profile.user
            if unit_profile
            else None
        )

    # Assistant Director is first searched within the exact unit.
    if role_code == "ASSISTANT_DIRECTOR":
        if department and department_unit:
            unit_profile = base_qs.filter(
                department=department,
                department_unit=department_unit,
            ).first()

            if unit_profile:
                return unit_profile.user

        # Fallback: use any Assistant Director in the same department.
        if department:
            department_profile = base_qs.filter(
                department=department,
            ).first()

            if department_profile:
                return department_profile.user

        return None

    # Director and other department-level roles are selected
    # from the same department.
    if department:
        department_profile = base_qs.filter(
            department=department,
        ).first()

        if department_profile:
            return department_profile.user

    # Central roles may be selected organization-wide.
    if role_code in CENTRAL_APPROVAL_ROLES:
        central_profile = base_qs.first()

        return (
            central_profile.user
            if central_profile
            else None
        )

    return None


def get_first_approver_for_requester(user, module_code):
    profile = get_user_profile(user)

    if not profile or not profile.department:
        return None, None

    next_step = get_first_approval_step_after_requester(
        profile.department,
        module_code,
    )

    if not next_step:
        return None, None

    approver = find_approver(
        department=profile.department,
        department_unit=profile.department_unit,
        approval_role_code=next_step.approval_role.code,
        exclude_user=user,
    )

    return next_step, approver


def get_director_for_department(department, exclude_user=None):
    return find_approver(
        department=department,
        department_unit=None,
        approval_role_code="DIRECTOR",
        exclude_user=exclude_user,
    )


def get_finance_workflow(finance_request):
    if not finance_request or not finance_request.department:
        return DepartmentApprovalWorkflow.objects.none()

    return get_department_workflow(
        finance_request.department,
        FINANCE_MODULE_CODE,
    )


@transaction.atomic
def initialize_finance_approval_steps(finance_request, reset=False):
    from finance.models import ApprovalStep

    if not finance_request:
        raise ValueError("A Finance Request is required.")

    if not finance_request.department:
        raise ValueError(
            "The Finance Request must have a department before workflow "
            "steps can be created."
        )

    workflow = list(get_finance_workflow(finance_request))

    if not workflow:
        raise ValueError(
            "No active Finance approval workflow is configured for "
            f"{finance_request.department}."
        )

    if reset:
        finance_request.approval_steps.all().delete()
    elif finance_request.approval_steps.exists():
        return finance_request.approval_steps.order_by("sequence_no")

    sequence_no = 1
    created_steps = []

    allowed_role_codes = {
        "HEAD_OF_UNIT",
        "ASSISTANT_DIRECTOR",
        "DIRECTOR",
    }

    for workflow_step in workflow:
        role_code = workflow_step.approval_role.code

        if role_code == "REQUESTER":
            continue

        # Budget Officer and Accountant are intentionally bypassed for now.
        if role_code not in allowed_role_codes:
            continue

        # A department without a unit does not require Head of Unit review.
        if role_code == "HEAD_OF_UNIT" and not finance_request.department_unit_id:
            continue

        approver = find_approver(
            department=finance_request.department,
            department_unit=finance_request.department_unit,
            approval_role_code=role_code,
            exclude_user=finance_request.submitted_by,
        )

        # If HOU or Assistant Director is not assigned, skip to the next
        # configured approver. Director remains compulsory.
        if not approver and role_code in {
            "HEAD_OF_UNIT",
            "ASSISTANT_DIRECTOR",
        }:
            continue

        if not approver and role_code == "DIRECTOR":
            raise ValueError(
                "No active Director is assigned to the requester's department."
            )

        approval_step = ApprovalStep.objects.create(
            finance_request=finance_request,
            step_name=role_code,
            actor=approver,
            action="PENDING",
            sequence_no=sequence_no,
        )

        created_steps.append(approval_step)
        sequence_no += 1

    if not created_steps:
        raise ValueError(
            "The configured Finance workflow has no approval steps after REQUESTER."
        )

    return finance_request.approval_steps.order_by("sequence_no")


def get_current_finance_approval_step(finance_request):
    """
    Return the first pending ApprovalStep for an active Finance Request.

    Draft/returned and rejected requests must not advance to another approver.
    """
    if not finance_request:
        return None

    if finance_request.status not in [
        "SUBMITTED",
        "HOU_REVIEWED",
        "DIRECTOR_APPROVED",
    ]:
        return None

    return (
        finance_request.approval_steps.filter(action="PENDING")
        .select_related("actor")
        .order_by("sequence_no")
        .first()
    )


def get_completed_finance_approval_steps(finance_request):
    if not finance_request:
        return []

    return finance_request.approval_steps.exclude(
        action="PENDING"
    ).select_related("actor").order_by("sequence_no")


def finance_workflow_is_complete(finance_request):
    if not finance_request:
        return False

    steps = finance_request.approval_steps.all()
    return steps.exists() and not steps.filter(action="PENDING").exists()


def can_user_review_finance_request(user, finance_request):
    if not user or not finance_request:
        return False

    current_step = get_current_finance_approval_step(finance_request)

    if not current_step:
        return False

    if getattr(user, "is_superuser", False):
        return True

    return current_step.actor_id == user.id


def get_finance_review_context(user, finance_request):
    current_step = get_current_finance_approval_step(finance_request)
    can_review = can_user_review_finance_request(user, finance_request)

    return {
        "workflow_steps": finance_request.approval_steps.select_related(
            "actor"
        ).order_by("sequence_no"),
        "current_workflow_step": current_step,
        "can_review": can_review,
        "can_approve": can_review,
        "can_return": can_review,
        "can_reject": can_review,
        "workflow_complete": finance_workflow_is_complete(finance_request),
    }


def _get_locked_current_finance_step(finance_request):
    from finance.models import ApprovalStep

    return (
        ApprovalStep.objects.select_for_update()
        .filter(
            finance_request=finance_request,
            action="PENDING",
        )
        .select_related("actor")
        .order_by("sequence_no")
        .first()
    )


def _ensure_user_can_act(user, step):
    if not step:
        raise PermissionDenied(
            "There is no pending approval step for this request."
        )

    if getattr(user, "is_superuser", False):
        return

    if step.actor_id != user.id:
        raise PermissionDenied(
            "You are not the assigned approver for the current step."
        )


@transaction.atomic
def approve_current_finance_step(user, finance_request, comment=""):
    current_step = _get_locked_current_finance_step(finance_request)
    _ensure_user_can_act(user, current_step)

    current_step.action = "APPROVED"
    current_step.comment = (comment or "").strip()
    current_step.acted_at = timezone.now()

    if not current_step.actor_id:
        current_step.actor = user

    current_step.save(
        update_fields=[
            "actor",
            "action",
            "comment",
            "acted_at",
        ]
    )

    next_step = _get_locked_current_finance_step(finance_request)
    is_complete = next_step is None

    return current_step, next_step, is_complete


@transaction.atomic
def return_current_finance_step(user, finance_request, comment):
    comment = (comment or "").strip()

    if not comment:
        raise ValueError("A return reason is required.")

    current_step = _get_locked_current_finance_step(finance_request)
    _ensure_user_can_act(user, current_step)

    current_step.action = "RETURNED"
    current_step.comment = comment
    current_step.acted_at = timezone.now()

    if not current_step.actor_id:
        current_step.actor = user

    current_step.save(
        update_fields=[
            "actor",
            "action",
            "comment",
            "acted_at",
        ]
    )

    finance_request.status = "DRAFT"
    finance_request.remarks = comment
    finance_request.save(
        update_fields=[
            "status",
            "remarks",
            "updated_at",
        ]
    )

    return current_step


@transaction.atomic
def reject_current_finance_step(user, finance_request, comment):
    comment = (comment or "").strip()

    if not comment:
        raise ValueError("A rejection reason is required.")

    current_step = _get_locked_current_finance_step(finance_request)
    _ensure_user_can_act(user, current_step)

    current_step.action = "REJECTED"
    current_step.comment = comment
    current_step.acted_at = timezone.now()

    if not current_step.actor_id:
        current_step.actor = user

    current_step.save(
        update_fields=[
            "actor",
            "action",
            "comment",
            "acted_at",
        ]
    )

    finance_request.status = "REJECTED"
    finance_request.remarks = comment
    finance_request.save(
        update_fields=[
            "status",
            "remarks",
            "updated_at",
        ]
    )

    return current_step


@transaction.atomic
def reset_finance_workflow_after_return(finance_request):
    return initialize_finance_approval_steps(
        finance_request,
        reset=True,
    )