import uuid

from app.clients.student_client import StudentClient
from app.utils.security import CurrentUser, Role


def visible_student_ids(students: StudentClient, user: CurrentUser) -> list[uuid.UUID] | None:
    """None = unrestricted (admin). For a parent: the children the Student Service says they may see."""
    if user.role is Role.ADMIN:
        return None
    return [uuid.UUID(i) for i in students.list_student_ids(user.token)]
