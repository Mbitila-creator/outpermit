from django.contrib import admin

from .models import (
    LearningAssessment, LearningAssessmentResult, LearningAttendance,
    LearningEnrollment, LearningEventProfile, LearningFacilitator, LearningSession,
    SeminarQuestion, WorkshopActivity, WorkshopActivitySubmission,
)


@admin.register(LearningEventProfile)
class LearningEventProfileAdmin(admin.ModelAdmin):
    list_display = ("event", "minimum_attendance_percentage", "post_assessment_pass_percentage")
    list_filter = ("event__category",)
    search_fields = ("event__code", "event__title_en", "event__title_sw")


@admin.register(LearningEnrollment)
class LearningEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("full_name", "profile", "status", "attendance_percentage", "post_assessment_percentage", "certificate_eligible")
    list_filter = ("profile__event", "status", "certificate_approved")
    search_fields = ("full_name", "institution", "email", "phone", "profile__event__code")


admin.site.register(LearningFacilitator)
admin.site.register(LearningSession)
admin.site.register(LearningAttendance)
admin.site.register(LearningAssessment)
admin.site.register(LearningAssessmentResult)
admin.site.register(WorkshopActivity)
admin.site.register(WorkshopActivitySubmission)
admin.site.register(SeminarQuestion)
