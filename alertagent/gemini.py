"""A small Gemini REST client (generateContent) with the standard library only.

- The key is read at run time from GEMINI_API_KEY, or from the GEMINI_API_KEY line of an
  env file given by --env-file or GEMINI_ENV_FILE. It is sent in a header, never in the URL,
  and it is never printed or saved.
- Per-minute limits (429) and server errors (500/503/504) are retried, waiting as long as
  Google asks ("retry in 23s") or with backoff. A daily limit stops the run cleanly.
"""

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"  # same default as payer-call-agent (free tier, tool calling)
RETRY_STATUS = (429, 500, 503, 504)


class DailyLimitError(Exception):
    """The key's daily quota for this model is used up; retrying today will not help."""


class GeminiError(Exception):
    pass


def load_api_key(env_file=None, environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("GEMINI_API_KEY"):
        return environ["GEMINI_API_KEY"].strip()
    path = env_file or environ.get("GEMINI_ENV_FILE")
    if not path:
        raise GeminiError("No key. Set GEMINI_API_KEY, or pass --env-file PATH (or GEMINI_ENV_FILE) to a file with a GEMINI_API_KEY= line.")
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise GeminiError("Env file not found: %s" % path)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise GeminiError("No GEMINI_API_KEY line with a value in %s" % path)


def thinking_config(model, effort="low"):
    """Gemini 2.x takes a thinking budget in tokens; newer models take a thinking level; Gemma takes neither."""
    if model.startswith("gemma"):
        return None
    if re.search(r"gemini-2\.", model):
        return {"thinkingBudget": {"low": 512, "medium": 2048, "high": 8192}[effort]}
    return {"thinkingLevel": effort.upper()}


def _retry_seconds(text):
    m = re.search(r"retry in ([\d.]+)s", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', text)
    if m:
        return float(m.group(1))
    return 0.0


def _short(text, limit=300):
    try:
        msg = json.loads(text).get("error", {}).get("message", text)
    except (ValueError, AttributeError):
        msg = text
    msg = " ".join(str(msg).split())
    return msg[:limit]


class GeminiClient:
    def __init__(self, api_key, timeout=90, max_attempts=6, sleep=time.sleep, opener=urllib.request.urlopen, log=None):
        self._key = api_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.opener = opener
        self.log = log or (lambda msg: None)
        self.requests = 0

    def _scrub(self, text):
        return text.replace(self._key, "***") if self._key else text

    def generate(self, model, body):
        url = API_URL % model
        data = json.dumps(body).encode("utf-8")
        for attempt in range(1, self.max_attempts + 1):
            req = urllib.request.Request(url, data=data, method="POST", headers={
                "Content-Type": "application/json", "x-goog-api-key": self._key})
            try:
                self.requests += 1
                with self.opener(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                text = self._scrub(e.read().decode("utf-8", errors="replace"))
                if e.code == 429 and re.search(r"per ?day", text, re.I):
                    limit = re.search(r"limit: \d+", text)
                    raise DailyLimitError("Daily free-tier limit reached for %s. %s" % (model, limit.group(0) if limit else ""))
                if attempt >= self.max_attempts or e.code not in RETRY_STATUS:
                    raise GeminiError("HTTP %d: %s" % (e.code, _short(text)))
                wait = _retry_seconds(text)
                wait = wait + 0.5 if wait else min(60.0, 2.0 * 2 ** attempt)
                self.log("HTTP %d, waiting %.0fs (attempt %d)" % (e.code, wait, attempt))
                self.sleep(wait)
            except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
                if attempt >= self.max_attempts:
                    raise GeminiError("Network error: %s" % self._scrub(str(e)))
                wait = min(60.0, 2.0 * 2 ** attempt)
                self.log("network error, waiting %.0fs (attempt %d)" % (wait, attempt))
                self.sleep(wait)
        raise GeminiError("gave up")
