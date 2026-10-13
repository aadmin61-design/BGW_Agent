from types import SimpleNamespace as Obj
from datetime import date, timedelta
from backend.scheduler import choose_lessons, review_update, resolve_dependencies, normalize_answer


def concept(id, depth=1, prerequisites=None, titles=None):
    return Obj(id=id, title=id, category="Java", depth=depth, prerequisites=prerequisites or [], prerequisite_titles=titles or [])


def test_new_lessons_follow_prerequisites_and_depth():
    a, b, c = concept("a"), concept("b", 2, ["a"]), concept("c", 3, ["b"])
    assert [x.id for x, _ in choose_lessons([c, b, a], {}, set(), date.today())] == ["a", "b", "c"]


def test_due_errors_prioritized_and_more_excludes_existing():
    day = date.today()
    progress = {"a": Obj(next_review=day, mistakes=0), "b": Obj(next_review=day, mistakes=2)}
    assert [x.id for x, _ in choose_lessons([concept("a"), concept("b"), concept("c")], progress, set(), day)] == ["b", "a", "c"]
    assert [x.id for x, _ in choose_lessons([concept("a"), concept("b"), concept("c")], progress, {"b"}, day)] == ["a", "c"]


def test_review_only_advances_once_per_day_and_error_resets():
    day = date.today()
    p = Obj(stage=0, last_reviewed=day - timedelta(days=1), mistakes=0)
    review_update(p, True, day)
    assert p.stage == 1 and p.next_review == day + timedelta(days=3)
    review_update(p, True, day)
    assert p.stage == 1
    review_update(p, False, day)
    assert p.stage == 0 and p.mistakes == 1 and p.next_review == day + timedelta(days=1)


def test_cycle_and_unknown_dependency_not_accepted():
    a, b = concept("a", titles=["b", "unknown", "a"]), concept("b", 2, titles=["a"])
    resolve_dependencies([b, a])
    assert a.prerequisites == [] and b.prerequisites == ["a"]


def test_fill_normalization_preserves_semantic_punctuation():
    assert normalize_answer(" Ｖｏｌａｔｉｌｅ ") == "volatile"
    assert normalize_answer("C++") != normalize_answer("C")
