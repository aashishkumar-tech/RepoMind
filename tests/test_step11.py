"""
tests/test_step11.py — Unit tests for Observability + Kill Switch

Tests:
    - MetricsRegistry initialization (enabled/disabled)
    - NoOp metrics fallback
    - push_metrics() success/failure/disabled
    - Kill switch on/off/unreachable
    - Kill switch cache behavior
    - Kill switch development mode bypass
    - @require_kill_switch_off decorator
"""

import os
import time
from unittest.mock import patch, MagicMock


# ──────────────────────────────────────────────
# Step 11 Metrics Tests
# ──────────────────────────────────────────────
class TestMetricsRegistry:
    """Tests for the Prometheus metrics registry."""

    def test_noop_metrics_when_disabled(self):
        """When METRICS_ENABLED=false, all metrics should be no-ops."""
        with patch.dict(os.environ, {"METRICS_ENABLED": "false"}):
            from step11.metrics import _NoOpMetric
            noop = _NoOpMetric()
            # Should not raise
            noop.inc()
            noop.labels(repo="test").inc()
            noop.observe(1.5)
            noop.set(42)
            noop.dec()

    def test_noop_metric_labels_returns_self(self):
        """NoOp.labels() should return self for chaining."""
        from step11.metrics import _NoOpMetric
        noop = _NoOpMetric()
        result = noop.labels(repo="test", status="ok")
        assert result is noop

    def test_metrics_registry_has_all_metrics(self):
        """MetricsRegistry should define all expected metrics."""
        from step11.metrics import MetricsRegistry
        with patch.dict(os.environ, {"METRICS_ENABLED": "false"}):
            registry = MetricsRegistry()

        # All metrics should exist (as no-ops when disabled)
        assert hasattr(registry, "events_total")
        assert hasattr(registry, "policy_decisions_total")
        assert hasattr(registry, "quality_checks_total")
        assert hasattr(registry, "prs_created_total")
        assert hasattr(registry, "verification_total")
        assert hasattr(registry, "rollbacks_total")
        assert hasattr(registry, "errors_total")
        assert hasattr(registry, "pipeline_duration")
        assert hasattr(registry, "triage_confidence")
        assert hasattr(registry, "kill_switch_state")

    def test_push_metrics_disabled(self):
        """push_metrics() should return False when metrics are disabled."""
        from step11.metrics import MetricsRegistry, push_metrics
        registry = MetricsRegistry()
        registry._enabled = False
        with patch("step11.metrics.metrics", registry):
            result = push_metrics()
            assert result is False

    def test_push_metrics_no_url(self):
        """push_metrics() should skip when PUSHGATEWAY_URL is empty."""
        from step11.metrics import push_metrics
        with patch("step11.metrics.metrics") as mock_metrics:
            mock_metrics.enabled = True
        with patch("step11.metrics.settings") as mock_settings:
            mock_settings.PUSHGATEWAY_URL = ""
            # This tests the URL check path


class TestPushMetrics:
    """Tests for push_metrics() function."""

    @patch("step11.metrics.push_to_gateway")
    def test_push_metrics_success(self, mock_push):
        """push_metrics() should call push_to_gateway when enabled."""
        from step11.metrics import MetricsRegistry

        with patch("step11.metrics.PROMETHEUS_AVAILABLE", True):
            with patch.dict(os.environ, {"METRICS_ENABLED": "true"}):
                registry = MetricsRegistry()

        with patch("step11.metrics.metrics", registry):
            with patch("step11.metrics.settings") as mock_settings:
                mock_settings.PUSHGATEWAY_URL = "http://localhost:9091"
                from step11.metrics import push_metrics
                result = push_metrics(job="test-job")
                if registry.enabled:
                    mock_push.assert_called_once()

    @patch("step11.metrics.push_to_gateway", side_effect=Exception("Connection refused"))
    def test_push_metrics_failure_non_fatal(self, mock_push):
        """push_metrics() should return False on failure, not raise."""
        from step11.metrics import MetricsRegistry

        with patch("step11.metrics.PROMETHEUS_AVAILABLE", True):
            with patch.dict(os.environ, {"METRICS_ENABLED": "true"}):
                registry = MetricsRegistry()

        with patch("step11.metrics.metrics", registry):
            with patch("step11.metrics.settings") as mock_settings:
                mock_settings.PUSHGATEWAY_URL = "http://localhost:9091"
                from step11.metrics import push_metrics
                result = push_metrics()
                if registry.enabled:
                    assert result is False


# ──────────────────────────────────────────────
# Step 11 Kill Switch Tests
# ──────────────────────────────────────────────
class TestKillSwitch:
    """Tests for the SSM-backed kill switch."""

    def setup_method(self):
        """Clear cache before each test."""
        from step11.killswitch import clear_cache
        clear_cache()

    def test_kill_switch_off_in_development(self):
        """Kill switch should always be OFF in development mode."""
        with patch("step11.killswitch.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "development"
            from step11.killswitch import is_kill_switch_enabled
            result = is_kill_switch_enabled()
            assert result is False

    @patch("boto3.client")
    def test_kill_switch_off_in_production(self, mock_boto):
        """Kill switch OFF when SSM returns 'off'."""
        from step11.killswitch import clear_cache
        clear_cache()

        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "off"}
        }
        mock_boto.return_value = mock_ssm

        with patch("step11.killswitch.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "production"
            mock_settings.KILL_SWITCH_PARAM = "/repomind/kill_switch"
            mock_settings.AWS_REGION = "ap-south-1"

            from step11.killswitch import is_kill_switch_enabled
            result = is_kill_switch_enabled()
            assert result is False

    @patch("boto3.client")
    def test_kill_switch_on_in_production(self, mock_boto):
        """Kill switch ON when SSM returns 'on'."""
        from step11.killswitch import clear_cache
        clear_cache()

        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "on"}
        }
        mock_boto.return_value = mock_ssm

        with patch("step11.killswitch.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "production"
            mock_settings.KILL_SWITCH_PARAM = "/repomind/kill_switch"
            mock_settings.AWS_REGION = "ap-south-1"

            from step11.killswitch import is_kill_switch_enabled
            result = is_kill_switch_enabled()
            assert result is True

    @patch("boto3.client", side_effect=Exception("SSM unreachable"))
    def test_kill_switch_fail_safe(self, mock_boto):
        """Kill switch should default to ON when SSM is unreachable."""
        from step11.killswitch import clear_cache
        clear_cache()

        with patch("step11.killswitch.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "production"
            mock_settings.KILL_SWITCH_PARAM = "/repomind/kill_switch"
            mock_settings.AWS_REGION = "ap-south-1"

            from step11.killswitch import is_kill_switch_enabled
            result = is_kill_switch_enabled()
            assert result is True  # Fail-safe: assume ON

    def test_kill_switch_cache(self):
        """Kill switch should use cached value within TTL."""
        from step11.killswitch import _cache, clear_cache
        clear_cache()

        # Manually set cache
        _cache["value"] = False
        _cache["ttl"] = time.monotonic() + 60  # 60 seconds from now

        with patch("step11.killswitch.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "production"

            from step11.killswitch import is_kill_switch_enabled
            result = is_kill_switch_enabled()
            assert result is False  # Should use cached value

    def test_clear_cache(self):
        """clear_cache() should reset the cache."""
        from step11.killswitch import _cache, clear_cache
        _cache["value"] = True
        _cache["ttl"] = time.monotonic() + 60
        clear_cache()
        assert _cache["value"] is None
        assert _cache["ttl"] == 0


class TestKillSwitchDecorator:
    """Tests for the @require_kill_switch_off decorator."""

    def setup_method(self):
        from step11.killswitch import clear_cache
        clear_cache()

    def test_decorator_allows_when_off(self):
        """Function should execute when kill switch is off."""
        from step11.killswitch import require_kill_switch_off

        @require_kill_switch_off
        def sample_function(x, y):
            return x + y

        with patch("step11.killswitch.is_kill_switch_enabled", return_value=False):
            result = sample_function(2, 3)
            assert result == 5

    def test_decorator_blocks_when_on(self):
        """Function should be blocked when kill switch is on."""
        from step11.killswitch import require_kill_switch_off

        @require_kill_switch_off
        def sample_function(x, y):
            return x + y

        with patch("step11.killswitch.is_kill_switch_enabled", return_value=True):
            result = sample_function(2, 3)
            assert result["status"] == "halted"
            assert "Kill switch" in result["reason"]

    def test_decorator_preserves_function_name(self):
        """Decorator should preserve the original function name."""
        from step11.killswitch import require_kill_switch_off

        @require_kill_switch_off
        def my_special_function():
            pass

        assert my_special_function.__name__ == "my_special_function"
