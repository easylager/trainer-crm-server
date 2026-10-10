"""Short shared cache for anonymous JSON lists under /api/public.

HTML that records a view (/p/, /c/, /ice/{city}/today) and anything that depends
on the visitor or initData stays uncached. A single card that writes a view
(trainer profile) stays uncached too.
"""

from fastapi import Response

# max-age is inside the 60–300s budget from TASK-197. stale-while-revalidate lets
# a cache serve the previous list for one more minute while it refreshes.
PUBLIC_JSON_LIST_CACHE = "public, max-age=120, stale-while-revalidate=120"


def set_public_json_list_cache(response: Response) -> None:
    response.headers["Cache-Control"] = PUBLIC_JSON_LIST_CACHE
