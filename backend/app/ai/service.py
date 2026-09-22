"""Process-local circuit breaker with cooldown and one half-open recovery probe."""
import asyncio
import time
from app.core.config import get_settings
from app.ai.fallback import rule_based_summary

class AnalysisService:
    def __init__(self):
        self.failures = 0
        self.opened_at = None
        self.probing = False
        self.lock = asyncio.Lock()

    async def analyze(self, provider, prompt, context):
        fallback = rule_based_summary(context)
        if provider is None:
            return fallback
        settings = get_settings()
        probe = False
        async with self.lock:
            if self.opened_at is not None:
                if self.probing or time.monotonic() - self.opened_at < settings.LLM_CIRCUIT_BREAKER_COOLDOWN_SEC:
                    return fallback
                self.probing = probe = True
        try:
            analysis = await asyncio.wait_for(provider.generate(prompt, context), settings.LLM_TIMEOUT_SEC)
            # Facts come from computed aggregates; model-generated prose is advisory.
            analysis = analysis.model_copy(update={"facts": fallback.facts, "source": "llm"})
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self.lock:
                self.failures += 1
                if probe or self.failures >= settings.LLM_CIRCUIT_BREAKER_THRESHOLD:
                    self.opened_at = time.monotonic()
            return fallback
        else:
            async with self.lock:
                # An in-flight success must not override a newer open circuit.
                if probe or self.opened_at is None:
                    self.failures = 0
                    self.opened_at = None
            return analysis
        finally:
            if probe:
                async with self.lock:
                    self.probing = False
