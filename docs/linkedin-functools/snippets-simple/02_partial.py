"""Simple snippet 2 of 4 — crop everything below the STUBS banner."""

from functools import partial

# 2. partial — bind arguments without a lambda


# Before
def register_handler(scheduler, user):
    scheduler.on_click(lambda: notify(user, channel="email", template="welcome"))


# After
def register_handler(scheduler, user):
    scheduler.on_click(partial(notify, user, channel="email", template="welcome"))

# Same callable, readable in a debugger, and picklable where lambdas often are not.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":

    class Scheduler:
        def __init__(self):
            self.handler = None

        def on_click(self, handler):
            self.handler = handler

    def notify(user, channel, template):
        return f"{user} via {channel} ({template})"

    s = Scheduler()
    register_handler(s, "ada")
    print(s.handler())
    # → ada via email (welcome)
