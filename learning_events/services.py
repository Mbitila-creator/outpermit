from .models import LearningEnrollment, normalized_category_code


def certificate_eligibility_for_submission(submission):
    """Return eligibility and an explanation for category-specific certificates."""
    event = submission.event_form.event
    if normalized_category_code(event) != "TRAINING":
        return True, ""
    enrollment = LearningEnrollment.objects.filter(
        profile__event=event,
        registration=submission,
        is_active=True,
    ).select_related("profile").first()
    if enrollment is None:
        return False, "Link this registration to the Training participant record first."
    if enrollment.post_assessment_percentage is None:
        return False, "Record the participant's post-assessment result first."
    if enrollment.post_assessment_percentage < enrollment.profile.post_assessment_pass_percentage:
        return False, "The participant has not reached the required post-assessment score."
    if enrollment.attendance_percentage < enrollment.profile.minimum_attendance_percentage:
        return False, "The participant has not reached the minimum attendance percentage."
    if enrollment.profile.certificate_requires_manual_approval and not enrollment.certificate_approved:
        return False, "The Training certificate still requires learning-workspace approval."
    return True, ""
