from app.services import openai_fortune


def test_palm_prompt_prioritizes_past_present_future_over_technical_report():
    prompt = openai_fortune._palm_developer_instructions().lower()
    assert "past" in prompt
    assert "present turning point" in prompt
    assert "hopeful future" in prompt
    assert "not a scientific" in prompt
    assert "technical palm terminology must remain under twenty percent" in prompt


def test_generic_prompt_requires_hopeful_past_present_future_arc():
    prompt = openai_fortune._generic_fortune_developer_instructions("tarot").lower()
    assert "past trace" in prompt
    assert "present turning point" in prompt
    assert "hopeful future opening" in prompt
    assert "never sound like a scientific" in prompt
