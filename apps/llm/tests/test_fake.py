"""Deterministic LLM test double contracts."""


def test_fake_llm_is_deterministic_for_identical_messages():
    from apps.llm.tests.fakes import DeterministicFakeLLM

    provider = DeterministicFakeLLM()
    messages = [
        {"role": "system", "content": "You are a safe assistant."},
        {"role": "user", "content": "Summarize this requirement."},
    ]

    first = provider.generate(messages)
    second = provider.generate(messages)

    assert first == second
    assert first.content
    assert provider.provider_name == "fake"
    assert provider.model_name == "sha256-test-llm"


def test_fake_llm_changes_output_for_different_messages():
    from apps.llm.tests.fakes import DeterministicFakeLLM

    provider = DeterministicFakeLLM()

    first = provider.generate([{"role": "user", "content": "first"}])
    second = provider.generate([{"role": "user", "content": "second"}])

    assert first != second
