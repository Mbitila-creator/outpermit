from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404

from core.models import SystemModule
from permits.models import Department, DepartmentApprovalWorkflow, ApprovalRole


def _is_admin(user):
    if user.is_superuser:
        return True

    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "ADMIN")


def _validate_workflow_health(department_id, module_code):
    steps = DepartmentApprovalWorkflow.objects.filter(
        department_id=department_id,
        module=module_code,
    ).select_related("approval_role").order_by("step_order")

    if not steps.exists():
        return False, "This workflow has no steps."

    first_step = steps.first()

    if first_step.step_order != 1 or first_step.approval_role.code != "REQUESTER":
        return False, "Workflow must start with Step 1 as Requester."

    active_approver_count = steps.exclude(
        approval_role__code="REQUESTER"
    ).filter(
        is_active=True
    ).count()

    if active_approver_count < 1:
        return False, "Workflow must have at least one active approver after Requester."

    expected_step = 1
    for step in steps:
        if step.step_order != expected_step:
            return False, "Workflow step numbers are not sequential."
        expected_step += 1

    return True, "Workflow is valid."


@login_required
def workflow_list(request):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Not allowed.")

    department_id = request.GET.get("department", "")
    module_code = request.GET.get("module", "")

    workflows = DepartmentApprovalWorkflow.objects.select_related(
        "department"
    ).values(
        "department_id",
        "department__code",
        "department__name",
        "module",
    ).annotate(
        step_count=Count("id")
    ).order_by("department__code", "module")

    if department_id:
        workflows = workflows.filter(department_id=department_id)

    if module_code:
        workflows = workflows.filter(module=module_code)

    return render(request, "workflow/workflow_configuration_list.html", {
        "workflows": workflows,
        "departments": Department.objects.filter(is_active=True).order_by("code"),
        "modules": SystemModule.objects.filter(is_active=True).order_by("code"),
        "selected_department": department_id,
        "selected_module": module_code,
    })


@login_required
def workflow_details(request, department_id, module_code):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Not allowed.")

    department = get_object_or_404(Department, pk=department_id)

    workflows = DepartmentApprovalWorkflow.objects.filter(
        department=department,
        module=module_code,
    ).select_related("approval_role").order_by("step_order")

    workflow_is_valid, workflow_validation_message = _validate_workflow_health(
        department.id,
        module_code,
    )

    return render(request, "workflow/workflow_details.html", {
        "department": department,
        "module_code": module_code,
        "workflows": workflows,
        "workflow_is_valid": workflow_is_valid,
        "workflow_validation_message": workflow_validation_message,
    })


@login_required
def workflow_add_step(request, department_id, module_code):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Not allowed.")

    department = get_object_or_404(Department, pk=department_id)

    if request.method == "POST":
        step_order = request.POST.get("step_order")
        approval_role_id = request.POST.get("approval_role")
        is_required = request.POST.get("is_required") == "on"
        is_active = request.POST.get("is_active") == "on"

        duplicate_step = DepartmentApprovalWorkflow.objects.filter(
            department=department,
            module=module_code,
            step_order=step_order,
        ).exists()

        if duplicate_step:
            messages.error(request, f"Step {step_order} already exists for this workflow.")
            return redirect("workflow_details", department_id=department.id, module_code=module_code)

        requester_role = ApprovalRole.objects.get(code="REQUESTER")

        if str(step_order) == "1" and int(approval_role_id) != requester_role.id:
            messages.error(request, "Step 1 must always be assigned to the Requester role.")
            return redirect("workflow_details", department_id=department.id, module_code=module_code)

        DepartmentApprovalWorkflow.objects.create(
            department=department,
            module=module_code,
            step_order=step_order,
            approval_role_id=approval_role_id,
            is_required=is_required,
            is_active=is_active,
        )

        messages.success(request, "Workflow step added successfully.")
        return redirect("workflow_details", department_id=department.id, module_code=module_code)

    next_step = (
        DepartmentApprovalWorkflow.objects.filter(
            department=department,
            module=module_code,
        ).count() + 1
    )

    return render(request, "workflow/workflow_add_step.html", {
        "department": department,
        "module_code": module_code,
        "next_step": next_step,
        "approval_roles": ApprovalRole.objects.filter(is_active=True).order_by("code"),
    })


@login_required
def workflow_edit(request, workflow_id):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Not allowed.")

    workflow = get_object_or_404(DepartmentApprovalWorkflow, pk=workflow_id)

    if request.method == "POST":
        step_order = request.POST.get("step_order")
        approval_role_id = request.POST.get("approval_role")

        duplicate_step = DepartmentApprovalWorkflow.objects.filter(
            department=workflow.department,
            module=workflow.module,
            step_order=step_order,
        ).exclude(pk=workflow.pk).exists()

        if duplicate_step:
            messages.error(request, f"Step {step_order} already exists for this workflow.")
            return redirect(
                "workflow_details",
                department_id=workflow.department_id,
                module_code=workflow.module
            )

        requester_role = ApprovalRole.objects.get(code="REQUESTER")

        if str(step_order) == "1" and int(approval_role_id) != requester_role.id:
            messages.error(request, "Step 1 must always be assigned to the Requester role.")
            return redirect(
                "workflow_details",
                department_id=workflow.department_id,
                module_code=workflow.module
            )

        workflow.step_order = step_order
        workflow.approval_role_id = approval_role_id
        workflow.is_required = request.POST.get("is_required") == "on"
        workflow.is_active = request.POST.get("is_active") == "on"
        workflow.save()

        messages.success(request, "Workflow step updated successfully.")
        return redirect("workflow_details", department_id=workflow.department_id, module_code=workflow.module)

    return render(request, "workflow/workflow_edit.html", {
        "workflow": workflow,
        "approval_roles": ApprovalRole.objects.filter(is_active=True).order_by("code"),
    })


@login_required
def workflow_delete(request, workflow_id):
    if not _is_admin(request.user):
        return HttpResponseForbidden("Not allowed.")

    workflow = get_object_or_404(DepartmentApprovalWorkflow, pk=workflow_id)
    department_id = workflow.department_id
    module_code = workflow.module

    if request.method == "POST":
        step_count = DepartmentApprovalWorkflow.objects.filter(
            department_id=department_id,
            module=module_code,
        ).count()

        if step_count <= 1:
            messages.error(request, "A workflow must contain at least one approval step.")
            return redirect(
                "workflow_details",
                department_id=department_id,
                module_code=module_code
            )

        workflow.delete()

        remaining_steps = DepartmentApprovalWorkflow.objects.filter(
            department_id=department_id,
            module=module_code,
        ).order_by("step_order", "id")

        for index, step in enumerate(remaining_steps, start=1):
            if step.step_order != index:
                step.step_order = index
                step.save(update_fields=["step_order"])

        messages.success(request, "Workflow step deleted and remaining steps renumbered successfully.")
        return redirect("workflow_details", department_id=department_id, module_code=module_code)

    return render(request, "workflow/workflow_delete.html", {
        "workflow": workflow,
    })