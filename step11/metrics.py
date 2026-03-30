"""
step11/metrics.py — Prometheus Metrics Registry + Pushgateway

HOW IT WORKS:
─────────────
1. Defines all RepoMind metrics using prometheus_client (Counters, Histograms, Gauges)
2. Each pipeline step increments/observes the relevant metric in-process
3. At the end of the pipeline, push_metrics() sends ALL metrics to Pushgateway
4. Prometheus scrapes Pushgateway → Grafana displays dashboards

WHY PUSHGATEWAY:
    Lambda functions are ephemeral — they can't expose a /metrics endpoint.
    Instead, we PUSH metrics to Pushgateway via HTTP POST at pipeline end.
    Prometheus then SCRAPES Pushgateway every 15s.

FLOW:
    Lambda runs pipeline → records metrics in-memory → push_metrics() → Pushgateway
    Pushgateway ←── Prometheus scrapes ──→ Grafana dashboards

USAGE:
    from step11.metrics import metrics, push_metrics

    # Record a metric
    metrics.events_total.labels(repo="user/repo", status="completed").inc()
    metrics.pipeline_duration.labels(repo="user/repo", step="triage").observe(1.5)

    # Push all metrics at end of pipeline
    push_metrics(job="repomind-worker")

COMMUNICATION:
─────────────
Worker (step2) imports and uses metrics throughout the pipeline.
push_metrics() is called once in _finalize() — non-blocking, fire-and-forget.

SAFETY:
    - If Pushgateway is unreachable → log warning, continue (non-fatal)
    - If METRICS_ENABLED=false → all operations are no-ops
    - Thread-safe (prometheus_client handles this)
"""

from typing import Optional
from shared.config import settings
from shared.logger import get_logger

logger = get_logger("step11.metrics")

# ──────────────────────────────────────────────
# Try to import prometheus_client
# Falls back to no-op if not installed
# ──────────────────────────────────────────────
try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Histogram,
        Gauge,
        push_to_gateway,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client_not_installed", msg="Metrics will be no-ops")


class MetricsRegistry:
    """
    Central registry for all RepoMind Prometheus metrics.

    All metrics are registered to a CUSTOM registry (not the default global one).
    This avoids conflicts with other libraries and makes testing clean.
    """

    def __init__(self):
        self._enabled = (
            getattr(settings, "METRICS_ENABLED", "false").lower() == "true"
            and PROMETHEUS_AVAILABLE
        )

        if self._enabled:
            self._registry = CollectorRegistry()
            self._init_metrics()
        else:
            self._registry = None
            self._init_noop_metrics()

    def _init_metrics(self):
        """Initialize real Prometheus metrics."""

        # ── Counters ──
        self.events_total = Counter(
            "repomind_events_total",
            "Total pipeline events processed",
            labelnames=["repo", "status"],
            registry=self._registry,
        )

        self.policy_decisions_total = Counter(
            "repomind_policy_decisions_total",
            "Total policy decisions",
            labelnames=["repo", "decision"],
            registry=self._registry,
        )

        self.quality_checks_total = Counter(
            "repomind_quality_checks_total",
            "Total code quality check results",
            labelnames=["repo", "result"],
            registry=self._registry,
        )

        self.prs_created_total = Counter(
            "repomind_prs_created_total",
            "Total pull requests created",
            labelnames=["repo"],
            registry=self._registry,
        )

        self.verification_total = Counter(
            "repomind_verification_total",
            "Total verification results",
            labelnames=["repo", "result"],
            registry=self._registry,
        )

        self.rollbacks_total = Counter(
            "repomind_rollbacks_total",
            "Total rollbacks performed",
            labelnames=["repo", "reason"],
            registry=self._registry,
        )

        self.errors_total = Counter(
            "repomind_errors_total",
            "Total pipeline errors",
            labelnames=["repo", "step"],
            registry=self._registry,
        )

        # ── Histograms ──
        self.pipeline_duration = Histogram(
            "repomind_pipeline_duration_seconds",
            "Pipeline step duration in seconds",
            labelnames=["repo", "step"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
            registry=self._registry,
        )

        # ── Gauges ──
        self.triage_confidence = Gauge(
            "repomind_triage_confidence",
            "Last triage confidence score",
            labelnames=["repo", "failure_type"],
            registry=self._registry,
        )

        self.kill_switch_state = Gauge(
            "repomind_kill_switch_state",
            "Kill switch state (0=off, 1=on)",
            registry=self._registry,
        )

    def _init_noop_metrics(self):
        """Initialize no-op metrics when Prometheus is unavailable or disabled."""
        noop = _NoOpMetric()
        self.events_total = noop
        self.policy_decisions_total = noop
        self.quality_checks_total = noop
        self.prs_created_total = noop
        self.verification_total = noop
        self.rollbacks_total = noop
        self.errors_total = noop
        self.pipeline_duration = noop
        self.triage_confidence = noop
        self.kill_switch_state = noop

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def registry(self) -> Optional[object]:
        return self._registry


class _NoOpMetric:
    """
    No-op metric that silently accepts any operation.
    Used when prometheus_client is not installed or metrics are disabled.
    """
    def labels(self, **kwargs):
        return self

    def inc(self, amount=1):
        pass

    def dec(self, amount=1):
        pass

    def set(self, value):
        pass

    def observe(self, amount):
        pass


# ──────────────────────────────────────────────
# Singleton metrics registry
# ──────────────────────────────────────────────
metrics = MetricsRegistry()


def push_metrics(job: str = "repomind-worker") -> bool:
    """
    Push all collected metrics to Pushgateway.

    Called once at the end of each pipeline execution.
    Non-blocking: if Pushgateway is down, logs a warning and continues.

    Args:
        job: The Prometheus job name (identifies the source)

    Returns:
        True if pushed successfully, False otherwise
    """
    if not metrics.enabled:
        logger.debug("metrics_push_skipped", reason="metrics disabled")
        return False

    pushgateway_url = getattr(settings, "PUSHGATEWAY_URL", "")
    if not pushgateway_url:
        logger.debug("metrics_push_skipped", reason="PUSHGATEWAY_URL not set")
        return False

    try:
        push_to_gateway(
            gateway=pushgateway_url,
            job=job,
            registry=metrics.registry,
        )
        logger.info("metrics_pushed", gateway=pushgateway_url, job=job)
        return True
    except Exception as e:
        logger.warning(
            "metrics_push_failed",
            gateway=pushgateway_url,
            error=str(e),
        )
        return False
