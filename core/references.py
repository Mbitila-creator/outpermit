from django.utils import timezone
from django.db.models import Max


MODULE_CODES = {
    "PERMIT": "PERMIT",
    "TASK": "TASK",
    "FINANCE": "FIN",
    "EVENT": "EVT",
}


def generate_reference(model_class, field_name, module_code, department=None):
    year = timezone.now().year
    module = MODULE_CODES.get(module_code.upper(), module_code.upper())

    if department:
        dept_code = department.code.upper()
        prefix = f"MoEST/{module}/{dept_code}/{year}/"
    else:
        prefix = f"MoEST/{module}/{year}/"

    last = (
        model_class.objects
        .filter(**{f"{field_name}__startswith": prefix})
        .aggregate(m=Max(field_name))
        .get("m")
    )

    if last:
        last_seq = int(last.split("/")[-1])
    else:
        last_seq = 0

    new_seq = last_seq + 1
    return f"{prefix}{new_seq:04d}"