from django.urls import path
from . import views


urlpatterns = [
    # --------------------------------------------------
    # Core Pages
    # --------------------------------------------------
    path("", views.task_dashboard, name="task_dashboard"),
    path("my/", views.my_tasks, name="my_tasks"),
    path("create/", views.create_task, name="create_task"),
    path("analytics/", views.task_analytics, name="task_analytics"),

    # --------------------------------------------------
    # Dynamic Department Data
    # --------------------------------------------------
    path(
        "ajax/department-units/",
        views.load_department_units,
        name="load_department_units"
    ),

    path(
    "ajax/department-staff/",
    views.load_department_staff,
    name="load_department_staff"
    ),

    # --------------------------------------------------
    # Export
    # --------------------------------------------------
    path(
        "export/excel/",
        views.export_tasks_excel,
        name="export_tasks_excel"
    ),
    path(
        "task-analytics/export/",
        views.task_analytics_export_excel,
        name="task_analytics_export_excel"
    ),

    # --------------------------------------------------
    # Task Actions
    # --------------------------------------------------
    path(
        "task/<int:pk>/",
        views.task_detail,
        name="task_detail"
    ),
    path(
        "task/<int:pk>/delete/",
        views.delete_task,
        name="delete_task"
    ),
    path(
        "task/<int:pk>/hold/",
        views.hold_task,
        name="hold_task"
    ),
    path(
        "task/<int:pk>/resume/",
        views.resume_task,
        name="resume_task"
    ),
    path(
        "task/<int:pk>/cancel/",
        views.cancel_task,
        name="cancel_task"
    ),
    path(
        "task/<int:pk>/return/",
        views.return_task,
        name="return_task"
    ),
    path(
        "task/<int:pk>/reassign/",
        views.reassign_returned_task,
        name="reassign_returned_task"
    ),

    # --------------------------------------------------
    # Assignment Actions
    # --------------------------------------------------
    path(
        "assignment/<int:pk>/accept/",
        views.accept_task,
        name="accept_task"
    ),
    path(
        "assignment/<int:pk>/complete/",
        views.complete_task,
        name="complete_task"
    ),

    # --------------------------------------------------
    # Analytics Detail Views
    # --------------------------------------------------
    path(
        "task-analytics/overdue/<str:range_key>/",
        views.task_analytics_overdue_detail,
        name="task_analytics_overdue_detail"
    ),
    path(
        "task-analytics/unit/<str:unit_name>/",
        views.task_analytics_completion_unit_detail,
        name="task_analytics_completion_unit_detail"
    ),
    path(
        "task-analytics/unit-delay/<str:unit_name>/",
        views.task_analytics_delay_unit_detail,
        name="task_analytics_delay_unit_detail"
    ),
    path(
        "task-analytics/staff/<int:user_id>/",
        views.task_analytics_staff_detail,
        name="task_analytics_staff_detail"
    ),
    path(
        "task-analytics/due-soon/",
        views.task_analytics_due_soon_detail,
        name="task_analytics_due_soon_detail"
    ),
    path(
        "task-analytics/stalled/",
        views.task_analytics_stalled_detail,
        name="task_analytics_stalled_detail"
    ),
]