"""Unified model runner: one interface, four provider adapters.

Every call records: model id + returned version, prompt SHA-256, decoding
params, latency, token counts, raw text, parse status, retry count.
Outputs are appended to JSONL files under runs/.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()


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
               before_sleep=lambda st: retries.__setitem__("n", retries["n"] + 1))
        def _call():
            return self._call(system, user, temperature, max_tokens, seed)

        try:
            text, version, tin, tout = _call()
            err = None
        except Exception as e:  # counted, never hidden
            text, version, tin, tout, err = "", "ERROR", None, None, repr(e)
        return Completion(text=text, model_id=f"{self.provider}:{self.model}",
                          model_version=version, prompt_sha256=prompt_hash,
                          latency_ms=int((time.time() - t0) * 1000),
                          tokens_in=tin, tokens_out=tout,
                          retries=retries["n"], error=err)

    def _call(self, system, user, temperature, max_tokens, seed):
        raise NotImplementedError


class OpenAIRunner(BaseRunner):
    provider = "openai"

    def _call(self, system, user, temperature, max_tokens, seed):
        from openai import OpenAI
        client = OpenAI()
        r = client.chat.completions.create(
            model=self.model, temperature=temperature, max_tokens=max_tokens,
            seed=seed,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        u = r.usage
        return (r.choices[0].message.content or "", r.model,
                u.prompt_tokens if u else None, u.completion_tokens if u else None)


class AnthropicRunner(BaseRunner):
    provider = "anthropic"

    def _call(self, system, user, temperature, max_tokens, seed):
        import anthropic
        client = anthropic.Anthropic()
        r = client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
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
        um = getattr(r, "usage_metadata", None)
        return (r.text, self.model,
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
        r = client.chat.completions.create(
            model=self.model, temperature=temperature, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        u = r.usage
        return (r.choices[0].message.content or "", r.model,
                u.prompt_tokens if u else None, u.completion_tokens if u else None)


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
