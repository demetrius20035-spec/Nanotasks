"""Адаптер Яндекс-моделей: Алиса и YandexGPT 5.1 Pro.

По примеру пользователя — через официальный SDK `openai` (Responses API):

    import openai
    client = openai.OpenAI(
        api_key=API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=FOLDER,
    )
    resp = client.responses.create(
        model=f"gpt://{FOLDER}/{MODEL}",   # MODEL: aliceai-llm/latest | yandexgpt-5.1/latest
        temperature=0.3, instructions="<system>", input="<user>", max_output_tokens=500,
    )
    print(resp.output_text)

Конфиг роли:
    provider: yandex          # (или alias: alice)
    model: yandexgpt-5.1/latest
    api_key: <API-ключ>
    folder_id: <каталог>      # пойдёт в extra
    max_tokens: 2000          # пойдёт в extra (необязательно)
"""

from __future__ import annotations

from ..config import ModelConfig
from .base import LLMClient, LLMError, LLMResponse, Message

DEFAULT_URL = "https://ai.api.cloud.yandex.net/v1"


class YandexClient(LLMClient):
    def __init__(self, cfg: ModelConfig, name: str = "yandex"):
        self.name = name
        self.model = cfg.model or "yandexgpt-5.1/latest"
        self.api_key = cfg.api_key
        self.base_url = cfg.base_url or DEFAULT_URL
        self.folder_id = cfg.extra.get("folder_id")
        self.temperature = cfg.temperature
        self.max_tokens = int(cfg.extra.get("max_tokens", 2000))
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            if not self.api_key or not self.folder_id:
                raise LLMError(f"[{self.name}] нужны api_key и folder_id в секции роли.")
            try:
                import openai
            except ImportError as exc:
                raise LLMError(
                    f"[{self.name}] нужен пакет openai: pip install openai"
                ) from exc
            self._client = openai.OpenAI(
                api_key=self.api_key, base_url=self.base_url, project=self.folder_id
            )
        return self._client

    def _model_uri(self) -> str:
        if self.model.startswith("gpt://"):
            return self.model
        return f"gpt://{self.folder_id}/{self.model}"

    def complete(self, messages: list[Message], temperature: float | None = None) -> LLMResponse:
        client = self._ensure_client()
        instructions = "\n\n".join(m.content for m in messages if m.role == "system")
        user_input = "\n\n".join(m.content for m in messages if m.role != "system")
        try:
            resp = client.responses.create(
                model=self._model_uri(),
                temperature=self.temperature if temperature is None else temperature,
                instructions=instructions,
                input=user_input,
                max_output_tokens=self.max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 — оборачиваем любую ошибку SDK
            raise LLMError(f"[{self.name}] ошибка запроса: {exc}") from exc
        return LLMResponse(content=resp.output_text, model=self.model, raw=None)
