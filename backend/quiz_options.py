"""独立处理选择题选项排列，消除模型倾向把正确答案放在A的偏差。"""
import re
from secrets import SystemRandom

LETTERS = "ABCD"
RANDOM = SystemRandom()


def balanced_targets(count, existing=None):
    # 优先填补缺少的位置；修复旧题时把不可变的已作答位置计入分布。
    counts = {letter: (existing or {}).get(letter, 0) for letter in LETTERS}
    targets = []
    for _ in range(count):
        minimum = min(counts.values())
        letter = RANDOM.choice([x for x in LETTERS if counts[x] == minimum])
        targets.append(letter)
        counts[letter] += 1
    RANDOM.shuffle(targets)
    return targets


def shuffle_choice(quiz, target):
    options, answer = quiz.get("options", []), quiz.get("answer", "")
    if len(options) != 4 or len(set(options)) != 4 or answer not in LETTERS or len(answer) != 1 or target not in LETTERS or len(target) != 1:
        raise ValueError("选择题选项或标准答案无效")
    correct = LETTERS.index(answer)
    others = [i for i in range(4) if i != correct]
    RANDOM.shuffle(others)
    order = others[:]
    order.insert(LETTERS.index(target), correct)
    mapping = {LETTERS[old]: LETTERS[new] for new, old in enumerate(order)}

    def remap(text):
        # 同步替换解析中的选项字母，保留Java标识符、行内代码和代码块。
        parts = re.split(r"(```.*?```|`[^`]*`)", text, flags=re.S)
        return "".join(part if i % 2 else re.sub(r"(?<![A-Za-z0-9_])[ABCD](?![A-Za-z0-9_])",
                    lambda match: mapping[match.group()], part) for i, part in enumerate(parts))

    return {**quiz, "options": [options[i] for i in order], "answer": target,
            "analysis": remap(quiz.get("analysis", "")),
            "accepted_answers": [], "option_order_version": 1}
