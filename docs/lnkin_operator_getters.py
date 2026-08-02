"""Four small callable factories from Python's operator module."""

from operator import attrgetter, itemgetter, methodcaller


# 1. Sort objects by one attribute
# attrgetter makes the key explicit: read created_at.
newest_users = sorted(
    users,
    key=attrgetter("created_at"),
    reverse=True,
)


# 2. Sort dictionaries by multiple fields
# Tuple ordering means priority first, created_at second.
rows.sort(
    key=itemgetter("priority", "created_at"),
)


# 3. Reach through nested objects
# Dotted paths traverse attributes — not dictionary keys.
employees.sort(
    key=attrgetter("department.name", "last_name"),
)


# 4. Turn a method call into a reusable callable
# strip(line) now means line.strip().
strip = methodcaller("strip")
cleaned_lines = list(map(strip, lines))
