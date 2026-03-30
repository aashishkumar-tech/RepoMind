"""
step11 — Observability + Kill Switch

Provides:
  - Prometheus metrics via Pushgateway (step11.metrics)
  - Global kill switch via AWS SSM Parameter Store (step11.killswitch)

COMMUNICATION:
─────────────
Worker (step2) calls:
  - is_kill_switch_enabled() at pipeline start
  - push_metrics() at pipeline end
Every step can emit metrics via the shared registry.
"""
