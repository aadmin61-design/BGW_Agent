"""模拟模型检查抽取约束，不读取密钥或调用云服务。"""
import json
from types import SimpleNamespace
from backend import ai


def test_json_mode_prompt_contains_actual_validation_constraints(monkeypatch):
    captured = {}
    class Model:
        def with_structured_output(self, schema, **kwargs):
            captured['schema'] = schema
            return self
        def invoke(self, messages):
            captured['prompt'] = messages[0].content
            return SimpleNamespace(concepts=[])
    monkeypatch.setattr(ai, 'extraction_llm', lambda: Model())
    assert ai.extract_concepts('资料中的文字', []) == []
    schema = json.loads(captured['prompt'].split('严格遵守以下JSON Schema，不添加额外解释：', 1)[1])
    assert schema['properties']['concepts']['maxItems'] == 5
    definition = schema['$defs']['ExtractedConcept']['properties']
    assert definition['depth']['type'] == 'integer'
    assert definition['depth']['maximum'] == 5
    assert definition['prerequisite_titles']['maxItems'] == 8
    assert definition['title']['maxLength'] == 180
