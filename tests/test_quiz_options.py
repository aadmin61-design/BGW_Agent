from collections import Counter
import pytest
from backend.quiz_options import balanced_targets, shuffle_choice


@pytest.mark.parametrize("count", [0, 1, 5, 10, 13])
def test_targets_are_balanced(count):
    targets = balanced_targets(count)
    assert len(targets) == count
    counts = Counter(targets)
    assert max([counts[x] for x in "ABCD"]) - min([counts[x] for x in "ABCD"]) <= 1


@pytest.mark.parametrize("answer", list("ABCD"))
@pytest.mark.parametrize("target", list("ABCD"))
def test_correct_content_and_analysis_survive_permutation(answer, target):
    quiz = {"options": ["自动装箱", "显式创建", "仅字符串", "全部无效"], "answer": answer,
            "analysis": f"{answer}正确。Java SE5支持自动装箱。示例：`class A {{}}`。", "accepted_answers": [answer]}
    result = shuffle_choice(quiz, target)
    assert result["options"]["ABCD".index(target)] == quiz["options"]["ABCD".index(answer)]
    assert result["analysis"] == f"{target}正确。Java SE5支持自动装箱。示例：`class A {{}}`。"
    assert sorted(result["options"]) == sorted(quiz["options"])
    assert result["accepted_answers"] == [] and result["option_order_version"] == 1
    assert quiz["answer"] == answer


def test_invalid_answer_is_rejected():
    with pytest.raises(ValueError):
        shuffle_choice({"options": ["a", "b", "c", "d"], "answer": ""}, "A")


def test_old_answer_bias_is_corrected_without_changing_fixed_items():
    fixed = Counter({"A": 3, "B": 1, "C": 1})
    distribution = fixed + Counter(balanced_targets(5, fixed))
    assert sum(distribution.values()) == 10
    assert max(distribution.values()) - min(distribution.values()) <= 1
    assert fixed == {"A": 3, "B": 1, "C": 1}
