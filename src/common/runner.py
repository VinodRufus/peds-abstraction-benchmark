"""Unified model runner: one interface, seven provider adapters.

Every call records: model id + returned version, prompt SHA-256, decoding
params, latency, token counts, raw text, parse status, retry count.
Outputs are appended to JSONL files under runs/.

Parameter policy (recorded, never silent): some current models reject a
fixed temperature or seed, and newer OpenAI models take
max_completion_tokens instead of max_tokens. Any parameter a model refuses
is dropped or renamed automatically, and the adjustment is appended to the
model_version string of that call's log record so the paper's
model-settings table can report exactly what each model ran with.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

from dotenv import load_dotenv
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

load_dotenv()

# Errors that will not change on retry: fail fast and surface the real message.
NON_RETRYABLE = {"BadRequestError", "AuthenticationError", "PermissionDeniedError",
                 "NotFoundError", "UnprocessableEntityError", "InvalidArgument"}


def _retryable(e: BaseException) -> bool:
    return type(e).__name__ not in NON_RETRYABLE


@dataclass
class Completion:
    text: str
    model_id: str
    model_version: str
    prompt_sha256: str
    latency_ms: int
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    retries: int
    error: Optional[str] = None


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class BaseRunner:
    provider = "base"

    def __init__(self, model: str):
        self.model = model

    def complete(self, system: str, user: str, *, temperature: float = 0.0,
                 max_tokens: int = 2000, seed: Optional[int] = None) -> Completion:
        prompt_hash = sha256(system + "\n---\n" + user)
        t0 = time.time()
        retries = {"n": 0}

        @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30),
               retry=retry_if_exception(_retryable),
               before_sleep=lambda st: retries.__setitem__("n", retries["n"] + 1))
        def _call():
            return self._call(system, user, temperature, max_tokens, seed)

        try:
            text, version, tin, tout = _call()
            err = None
        except Exception as e:  # counted, never hidden
            if hasattr(e, "last_attempt"):  # tenacity RetryError: unwrap the real cause
                e = e.last_attempt.exception() or e
            text, version, tin, tout, err = "", "ERROR", None, None, repr(e)
        return Completion(text=text, model_id=f"{self.provider}:{self.model}",
                          model_version=version, prompt_sha256=prompt_hash,
                          latency_ms=int((time.time() - t0) * 1000),
                          tokens_in=tin, tokens_out=tout,
                          retries=retries["n"], error=err)

    def _call(self, system, user, temperature, max_tokens, seed):
        raise NotImplementedError


def _adaptive_chat(client, kwargs):
    """chat.completions call that negotiates per-model parameter rules.

    Reasoning-class models reject a fixed temperature or seed; newer OpenAI
    models require max_completion_tokens in place of max_tokens. Whatever the
    model refuses is dropped or renamed, and every adjustment is returned so
    the caller records it in the run log.
    """
    from openai import BadRequestError
    adjusted = []
    for _ in range(4):
        try:
            return client.chat.completions.create(**kwargs), adjusted
        except BadRequestError as e:
            msg = str(e)
            if "max_tokens" in kwargs and "max_tokens" in msg:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                adjusted.append("max_tokens renamed to max_completion_tokens")
                continue
            victim = next((p for p in ("temperature", "seed")
                           if p in kwargs and p in msg), None)
            if victim is None:
                raise
            kwargs.pop(victim)
            adjusted.append(f"{victim} rejected by model; provider default used")
    raise RuntimeError("model parameter negotiation did not converge")


def _version_with(adjustments, base):
    return base + (f" [{'; '.join(adjustments)}]" if adjustments else "")


class OpenAIRunner(BaseRunner):
    provider = "openai"

    def _call(self, system, user, temperature, max_tokens, seed):
        from openai import OpenAI
        client = OpenAI()
        kwargs = {"model": self.model,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "max_completion_tokens": max_tokens,
                  "temperature": temperature,
                  "seed": seed}
        r, adjusted = _adaptive_chat(client, kwargs)
        u = r.usage
        return (r.choices[0].message.content or "",
                _version_with(adjusted, r.model),
                u.prompt_tokens if u else None,
                u.completion_tokens if u else None)


class AnthropicRunner(BaseRunner):
    provider = "anthropic"

    def _call(self, system, user, temperature, max_tokens, seed):
        import anthropic
        client = anthropic.Anthropic()
        # anthropic SDK 1.x removed the temperature parameter from
        # Messages.create; the provider default applies and is recorded in
        # the paper's model-settings table.
        r = client.messages.create(
            model=self.model, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in r.content if b.type == "text")
        return text, r.model, r.usage.input_tokens, r.usage.output_tokens


class GoogleRunner(BaseRunner):
    provider = "google"

    def _call(self, system, user, temperature, max_tokens, seed):
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        model = genai.GenerativeModel(self.model, system_instruction=system)
        r = model.generate_content(
            user, generation_config={"temperature": temperature,
                                     "max_output_tokens": max_tokens})
        # Gemini 3.x: r.text raises when no simple text part exists (e.g.
        # thinking tokens exhausted the cap), so extract parts defensively.
        text = ""
        for cand in getattr(r, "candidates", None) or []:
            parts = getattr(getattr(cand, "content", None), "parts", None) or []
            text = "".join(getattr(p, "text", "") or "" for p in parts)
            if text:
                break
        um = getattr(r, "usage_metadata", None)
        return (text, self.model,
                getattr(um, "prompt_token_count", None),
                getattr(um, "candidates_token_count", None))


class OllamaRunner(BaseRunner):
    provider = "ollama"

    def _call(self, system, user, temperature, max_tokens, seed):
        import requests
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        r = requests.post(f"{host}/api/chat", timeout=600, json={
            "model": self.model, "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens,
                        "seed": seed or 0},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]})
        r.raise_for_status()
        d = r.json()
        return (d["message"]["content"], d.get("model", self.model),
                d.get("prompt_eval_count"), d.get("eval_count"))


class OpenAICompatRunner(BaseRunner):
    """Any OpenAI-compatible endpoint (xAI, DeepSeek, Together, ...)."""
    provider = "compat"
    base_url = None
    key_env = None

    def _call(self, system, user, temperature, max_tokens, seed):
        from openai import OpenAI
        client = OpenAI(base_url=self.base_url, api_key=os.environ[self.key_env])
        kwargs = {"model": self.model,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "max_tokens": max_tokens,
                  "temperature": temperature}
        r, adjusted = _adaptive_chat(client, kwargs)
        u = r.usage
        return (r.choices[0].message.content or "",
                _version_with(adjusted, r.model),
                u.prompt_tokens if u else None,
                u.completion_tokens if u else None)


class XAIRunner(OpenAICompatRunner):
    provider = "xai"
    base_url = "https://api.x.ai/v1"
    key_env = "XAI_API_KEY"


class DeepSeekRunner(OpenAICompatRunner):
    provider = "deepseek"
    base_url = "https://api.deepseek.com"
    key_env = "DEEPSEEK_API_KEY"


class TogetherRunner(OpenAICompatRunner):
    """For hosted open-weights models (Llama, MedGemma, etc.)."""
    provider = "together"
    base_url = "https://api.together.xyz/v1"
    key_env = "TOGETHER_API_KEY"


def make_runner(model_id: str) -> BaseRunner:
    """model_id format: 'provider:model_name' e.g. 'openai:gpt-4o'."""
    provider, _, model = model_id.partition(":")
    cls = {"openai": OpenAIRunner, "anthropic": AnthropicRunner,
           "google": GoogleRunner, "ollama": OllamaRunner,
           "xai": XAIRunner, "deepseek": DeepSeekRunner,
           "together": TogetherRunner}[provider]
    return cls(model)


def parse_json_strict(text: str):
    """Strict JSON parse with one tolerated wrapper: markdown fences."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s), None
    except Exception as e:
        return None, repr(e)


def append_jsonl(path: str, record: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def completion_record(c: Completion, **extra) -> dict:
    d = asdict(c)
    d.update(extra)
    d["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return d
