"""Screenshot 2 of 6 — crop everything below the STUBS banner."""

from contextlib import ExitStack

# ── 2. stack.callback + pop_all — register the undo where the risk is ───────


def provision(api, name: str) -> str:
    with ExitStack() as stack:
        bucket = api.create_bucket(name)
        stack.callback(api.delete_bucket, bucket)  # undo, armed on the next line

        api.attach_policy(bucket)  # may raise
        stack.callback(api.detach_policy, bucket)

        stack.pop_all()  # happy path: disarm both undos and keep the bucket
        return bucket


# Anything that raises before pop_all() unwinds the callbacks in reverse —
# policy detached, bucket deleted — and the original traceback still surfaces.
# Compensating transactions in three lines, with no saga framework in sight.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":

    class Api:
        def __init__(self, *, policy_fails: bool) -> None:
            self.policy_fails = policy_fails
            self.log: list[str] = []

        def create_bucket(self, name: str) -> str:
            self.log.append(f"create {name}")
            return name

        def delete_bucket(self, bucket: str) -> None:
            self.log.append(f"delete {bucket}")

        def attach_policy(self, bucket: str) -> None:
            if self.policy_fails:
                raise RuntimeError("policy service unavailable")
            self.log.append(f"attach {bucket}")

        def detach_policy(self, bucket: str) -> None:
            self.log.append(f"detach {bucket}")

    happy = Api(policy_fails=False)
    print(provision(happy, "reports"), happy.log)
    # → reports ['create reports', 'attach reports']

    unhappy = Api(policy_fails=True)
    try:
        provision(unhappy, "reports")
    except RuntimeError as exc:
        print(exc, unhappy.log)
        # → policy service unavailable ['create reports', 'delete reports']
