"""Four useful callable factories from Python's operator module."""

from dataclasses import dataclass
from operator import attrgetter, itemgetter

# 1. Sort objects by an attribute
@dataclass
class User:
    name: str
    score: int


users = [User("Ada", 98), User("Linus", 91)]
leaders = sorted(users, key=attrgetter("score"), reverse=True)
# attrgetter("score") → user.score


# 2. Sort dictionaries by two fields
tasks = [
    {"id": "A", "priority": 2, "created_at": "09:00"},
    {"id": "B", "priority": 1, "created_at": "11:00"},
    {"id": "C", "priority": 1, "created_at": "08:00"},
]
ordered = sorted(tasks, key=itemgetter("priority", "created_at"))
# Order: C, B, A — priority first, then created_at


# 3. Pick and unpack fields from a dictionary
payload = {"id": 42, "email": "ada@example.com", "role": "admin"}
get_identity = itemgetter("id", "email")
user_id, email = get_identity(payload)
# → (42, "ada@example.com")


# 4. Reach a nested attribute without a lambda
@dataclass
class Department:
    name: str


@dataclass
class Employee:
    name: str
    department: Department


staff = [
    Employee("Linus", Department("Infra")),
    Employee("Ada", Department("Platform")),
]
by_team = sorted(staff, key=attrgetter("department.name"))
# attrgetter("department.name") → employee.department.name
# Order: Infra (Linus), Platform (Ada)
