import json
import subprocess
from datetime import UTC, datetime

import pytest

from brief.config import LlmConfig
from brief.llm import SYSTEM_PROMPT, CodexCliEditorialProcessor, EditorialError, OpenAIEditorialProcessor
from brief.models import Article


def article(identifier: str, title: str, url: str) -> Article:
    return Article(
        id=identifier,
        source_id="fixture",
        title=title,
        url=url,
        fetched_at=datetime.now(UTC),
        content_text="A source report with concrete facts and enough context for editorial review.",
        image_url=f"{url}/image.jpg",
    )


def completed_response(output: dict) -> dict:
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(output)}],
            }
        ],
    }


def test_structured_editorial_pass_deduplicates_and_preserves_trusted_urls(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    first = article("first", "First report", "https://example.test/first")
    duplicate = article("duplicate", "Same event", "https://example.test/duplicate")
    captured = {}

    def transport(payload, api_key, timeout):
        captured.update({"payload": payload, "api_key": api_key, "timeout": timeout})
        return completed_response(
            {
                "articles": [
                    {
                        "id": "first",
                        "image": first.image_url,
                        "heading": "Officials publish the first report",
                        "text_summary": (
                            "Officials published the report with the figures and context supplied by the source."
                        ),
                        "source_url": first.url,
                        "genre": "Politics & Policy",
                        "watchouts": ["The figures have not been independently verified."],
                        "important_points": ["The report contains newly published figures."],
                    }
                ]
            }
        )

    result = OpenAIEditorialProcessor(LlmConfig(), transport=transport).process([first, duplicate], 10)

    assert len(result) == 1
    assert result[0].id == "first"
    assert result[0].url == first.url
    assert result[0].image_url == first.image_url
    assert result[0].category == "Politics & Policy"
    assert result[0].llm_curated is True
    assert captured["api_key"] == "test-key"
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert captured["payload"]["text"]["format"]["schema"]["additionalProperties"] is False
    assert "senior editor" in SYSTEM_PROMPT
    assert "untrusted quoted source material" in SYSTEM_PROMPT


def test_editorial_pass_rejects_altered_source_url(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    original = article("first", "First report", "https://example.test/first")

    def transport(payload, api_key, timeout):
        return completed_response(
            {
                "articles": [
                    {
                        "id": "first",
                        "image": original.image_url,
                        "heading": "First report",
                        "text_summary": "Summary",
                        "source_url": "https://invented.test/story",
                        "genre": "World",
                        "watchouts": [],
                        "important_points": [],
                    }
                ]
            }
        )

    with pytest.raises(EditorialError, match="altered a trusted URL"):
        OpenAIEditorialProcessor(LlmConfig(), transport=transport).process([original], 10)


def test_editorial_pass_requires_environment_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EditorialError, match="missing OpenAI API key"):
        OpenAIEditorialProcessor(LlmConfig()).process([], 10)


def test_editorial_pass_handles_refusal(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def transport(payload, api_key, timeout):
        return {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
        }

    with pytest.raises(EditorialError, match="refused"):
        OpenAIEditorialProcessor(LlmConfig(), transport=transport).process([], 10)


def test_codex_cli_uses_read_only_structured_exec(monkeypatch) -> None:
    original = article("first", "First report", "https://example.test/first")
    captured = {}

    def run(command, **kwargs):
        captured.update({"command": command, **kwargs})
        answer_path = command[command.index("--output-last-message") + 1]
        with open(answer_path, "w", encoding="utf-8") as answer:
            json.dump(
                {
                    "articles": [
                        {
                            "id": "first",
                            "image": original.image_url,
                            "heading": "First report",
                            "text_summary": "A concise account based on the supplied source report.",
                            "source_url": original.url,
                            "genre": "World",
                            "watchouts": [],
                            "important_points": ["The source provides the reported facts."],
                        }
                    ]
                },
                answer,
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    result = CodexCliEditorialProcessor(LlmConfig(backend="codex-cli")).process([original], 5)

    assert result[0].llm_curated is True
    assert captured["command"][:2] == ["codex", "exec"]
    assert "--output-schema" in captured["command"]
    assert captured["command"][2:4] == ["--sandbox", "read-only"]
    assert captured["command"][-1] == "-"
    assert "Editorial input JSON" in captured["input"]
