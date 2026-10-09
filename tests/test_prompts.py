"""v0.9.0 Room 15 — the Wise Fire: prompt playlists, keyless."""

from hearth.models import Track
from hearth.prompts import MOOD_WORDS, PromptPlan, assemble, interpret


def track(prefix, i=0):
    return Track(video_id=prefix, title=f"T{i}", artist="A")


def track_factory(prefix):
    def make(query):
        # Deterministic ids per query so round-robin blending is checkable.
        n = abs(hash(query)) % 50
        return [Track(video_id=f"{prefix}{n}-{i}", title=f"T{i}", artist="A")
                for i in range(8)]
    return make


# --- interpretation ---


def test_rainy_midnight_study_maps_three_moods():
    plan = interpret("rainy midnight study")
    assert "rain" in plan.tags
    assert "night" in plan.tags
    assert "study" in plan.tags
    assert plan.queries  # always something searchable


def test_prompt_queries_come_from_mood_table():
    plan = interpret("gym energy")
    expected = MOOD_WORDS["gym"] + MOOD_WORDS["energy"]
    assert all(q in plan.queries for q in expected)


def test_stop_words_never_become_queries():
    plan = interpret("give me some chill vibes for my playlist please")
    assert plan.tags == ["chill"]
    assert all("give" not in q and "vibes" not in q for q in plan.queries)


def test_unknown_words_fall_back_to_raw_text():
    plan = interpret("xylophone breakfast")
    assert plan.tags == []
    assert plan.queries == ["xylophone breakfast"]


def test_empty_prompt_is_an_empty_plan():
    plan = interpret("")
    assert plan.tags == [] and plan.queries == []
    assert plan.display_name


def test_display_name_uses_matched_tags():
    assert interpret("rainy study").display_name == "Study Rain mix"
    assert interpret("xylophone").display_name == '"xylophone" mix'


# --- assembly ---


def test_assemble_round_robins_across_queries():
    plan = PromptPlan(text="x", queries=["q1", "q2"])
    buckets = {
        "q1": [track(f"a{i}") for i in range(3)],
        "q2": [track(f"b{i}") for i in range(3)],
    }
    out = assemble(plan, lambda q: buckets[q], limit=6)
    assert [t.video_id for t in out] == ["a0", "b0", "a1", "b1", "a2", "b2"]


def test_assemble_dedupes_across_queries():
    shared = track("same")
    plan = PromptPlan(text="x", queries=["q1", "q2"])
    out = assemble(plan, lambda q: [shared], limit=10)
    assert [t.video_id for t in out] == ["same"]


def test_assemble_skips_failing_queries():
    def search(query):
        if query == "dead":
            raise RuntimeError("search is down")
        return [track(f"{query}-{i}") for i in range(2)]
    plan = PromptPlan(text="x", queries=["dead", "alive"])
    out = assemble(plan, search, limit=10)
    assert [t.video_id for t in out] == ["alive-0", "alive-1"]


def test_assemble_respects_limit():
    plan = PromptPlan(text="x", queries=["q"])
    out = assemble(plan, lambda q: [track(f"v{i}") for i in range(30)], limit=5)
    assert len(out) == 5


def test_assemble_empty_plan_and_zero_limit():
    assert assemble(PromptPlan(text=""), lambda q: []) == []
    plan = PromptPlan(text="x", queries=["q"])
    assert assemble(plan, lambda q: [track("v")], limit=0) == []
