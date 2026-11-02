

def test_arena_hours_summary_accepts_catalog_formats():
    from src.application.winter_public import arena_hours_summary

    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    assert arena_hours_summary({"weekly": {d: [{"open": "10:00", "close": "22:00"}] for d in days}}) == "Ежедневно 10:00–22:00"
    assert arena_hours_summary({"weekly": {d: ["10:00-22:00"] for d in days}}) == "Ежедневно 10:00–22:00"
    assert arena_hours_summary({"weekly": {d: [["10:00", "22:00"]] for d in days}}) == "Ежедневно 10:00–22:00"
    assert arena_hours_summary({"weekly": {"mon": [{"weird": 1}]}}) is None
