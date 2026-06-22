"""Детерминированные фейковые клиенты моделей для тестов."""

from __future__ import annotations

from nanotasks.llm.base import LLMClient, LLMError, LLMResponse


class EchoPrompt(LLMClient):
    """Постановщик: ответ отражает, что было во входе (проверка инъекции)."""

    name = "pb"
    model = "fake-pb"

    def complete(self, messages, temperature=None):
        user = messages[-1].content
        marker = (
            f"NANO fb={'Замечания' in user} "
            f"cur={'Текущая версия кода' in user} "
            f"dep={'Контракты зависимостей' in user}"
        )
        return LLMResponse(content=marker, model=self.model)


class MarkerCoder(LLMClient):
    """Кодер: 'fixed' если в промпте fb=True, иначе 'v1'. Может обернуть в fence."""

    name = "coder"
    model = "fake-coder"

    def __init__(self, fence: bool = False):
        self.fence = fence

    def complete(self, messages, temperature=None):
        body = "fixed" if "fb=True" in messages[-1].content else "v1"
        code = f"def f():\n    return '{body}'\n"
        if self.fence:
            code = f"```python\n{code}```"
        return LLMResponse(content=code, model=self.model)


class ScriptedClient(LLMClient):
    """Возвращает заранее заданные ответы по очереди (последний — повторно)."""

    name = "scripted"
    model = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, messages, temperature=None):
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return LLMResponse(content=self.responses[idx], model=self.model)


class FlakyClient(LLMClient):
    """Падает первые fail_times вызовов, затем отдаёт content."""

    name = "flaky"
    model = "fake"

    def __init__(self, content: str, fail_times: int = 1):
        self.content = content
        self.fail_times = fail_times
        self.calls = 0

    def complete(self, messages, temperature=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise LLMError("временная ошибка")
        return LLMResponse(content=self.content, model=self.model)
