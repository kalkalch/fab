"""
MQTT integration module for FAB.

Handles persistent connection and message publishing to MQTT broker
for firewall access events with automatic reconnection and TTL cleanup.
"""

import json
import logging
import threading
import time
from typing import Optional, Dict, Any

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from ..config import config


logger = logging.getLogger(__name__)


class MqttPublisher:
    """Persistent MQTT publisher with automatic reconnection."""

    def __init__(self) -> None:
        self._client: Optional["mqtt.Client"] = None
        self._connected = False
        self._connection_lock = threading.RLock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_running = False
        self._last_connect_attempt = 0.0

    def connect(self) -> bool:
        """Establish persistent connection to MQTT broker."""
        if not MQTT_AVAILABLE:
            logger.error("paho-mqtt library not available, MQTT disabled")
            return False

        with self._connection_lock:
            if self._client is None:
                self._client = self._build_client()

            try:
                self._client.connect(
                    config.mqtt_host,
                    config.mqtt_port,
                    config.mqtt_keepalive
                )
                self._client.loop_start()
                self._start_monitor()
                return True
            except Exception as e:
                logger.error(f"Failed to connect to MQTT broker: {e}")
                return False

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        with self._connection_lock:
            self._stop_monitor()
            if self._client:
                try:
                    self._client.loop_stop()
                except Exception as e:
                    logger.warning(f"Error stopping MQTT loop: {e}")
                try:
                    self._client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting MQTT client: {e}")
            self._client = None
            self._connected = False

    def publish(self, topic: str, payload: str, retain: bool) -> bool:
        """Publish a message to MQTT with optional retain flag."""
        with self._connection_lock:
            if not self._client and not self.connect():
                return False

            if not self._connected and not self._attempt_reconnect():
                return False

            try:
                result = self._client.publish(
                    topic,
                    payload=payload,
                    qos=config.mqtt_qos,
                    retain=retain
                )
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.warning(f"MQTT publish failed: rc={result.rc}")
                    return False
                return True
            except Exception as e:
                logger.error(f"MQTT publish error: {e}")
                return False

    def is_connected(self) -> bool:
        """Check whether the MQTT client is connected."""
        with self._connection_lock:
            return self._connected

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection info for monitoring."""
        with self._connection_lock:
            return {
                "connected": self._connected,
                "last_connect_attempt": self._last_connect_attempt,
                "host": config.mqtt_host,
                "port": config.mqtt_port,
                "client_id": config.mqtt_client_id
            }

    def _build_client(self) -> "mqtt.Client":
        client = mqtt.Client(client_id=config.mqtt_client_id, clean_session=True)
        if config.mqtt_username or config.mqtt_password:
            client.username_pw_set(config.mqtt_username, config.mqtt_password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            logger.info("MQTT connected")
        else:
            self._connected = False
            logger.error(f"MQTT connection failed with rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT disconnected unexpectedly (rc={rc})")

    def _attempt_reconnect(self) -> bool:
        if not self._client:
            return False
        now = time.time()
        if now - self._last_connect_attempt < 5.0:
            return False
        self._last_connect_attempt = now
        try:
            self._client.reconnect()
            return True
        except Exception as e:
            logger.warning(f"MQTT reconnect failed: {e}")
            return False

    def _start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_worker,
            name="MQTT-Monitor",
            daemon=True
        )
        self._monitor_thread.start()

    def _stop_monitor(self) -> None:
        self._monitor_running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

    def _monitor_worker(self) -> None:
        while self._monitor_running:
            time.sleep(5.0)
            if not self._monitor_running:
                break
            with self._connection_lock:
                if not self._connected:
                    self._attempt_reconnect()


class MqttService:
    """MQTT service with TTL cleanup for whitelist topics."""

    def __init__(self) -> None:
        self.publisher = MqttPublisher()
        self.enabled = config.mqtt_enabled
        self._expiry_lock = threading.RLock()
        self._expiry_map: Dict[str, float] = {}
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_running = False

    def start(self) -> bool:
        """Start MQTT service."""
        if not self.enabled:
            logger.info("MQTT is disabled, skipping connection")
            return True

        logger.info("Starting MQTT service...")
        connected = self.publisher.connect()
        self._start_cleanup()
        return connected

    def stop(self) -> None:
        """Stop MQTT service and cleanup threads."""
        self._stop_cleanup()
        if self.enabled:
            logger.info("Stopping MQTT service...")
            self.publisher.disconnect()

    def publish_whitelist_open(self, ip_address: str, ttl: int) -> bool:
        """Publish whitelist open message with TTL."""
        message = json.dumps({"ttl": int(ttl)}, ensure_ascii=False)
        topic = f"{config.mqtt_topic_prefix}/{ip_address}"

        logger.info(f"ACCESS_EVENT: {topic} -> {message}")
        if not self.enabled:
            logger.debug("MQTT disabled, message logged only")
            return True

        if ttl <= 0:
            logger.warning(f"Invalid TTL for MQTT publish: {ttl}")
            return False

        success = self.publisher.publish(topic, message, retain=True)
        if success:
            self._schedule_expiry(topic, ttl)
        else:
            logger.warning("Failed to publish MQTT open message")
        return success

    def publish_whitelist_close(self, ip_address: str) -> bool:
        """Publish retained empty payload to remove whitelist topic."""
        topic = f"{config.mqtt_topic_prefix}/{ip_address}"
        logger.info(f"ACCESS_EVENT_CLEAR: {topic}")
        if not self.enabled:
            logger.debug("MQTT disabled, clear logged only")
            return True

        success = self.publisher.publish(topic, "", retain=True)
        with self._expiry_lock:
            self._expiry_map.pop(topic, None)
        if not success:
            logger.warning("Failed to publish MQTT clear message")
        return success

    def get_status(self) -> Dict[str, Any]:
        """Get MQTT status for health endpoint."""
        status = {
            "enabled": self.enabled,
            "service_running": True
        }
        if self.enabled:
            status.update(self.publisher.get_connection_info())
        return status

    def health_check(self) -> bool:
        """Simple health check."""
        if not self.enabled:
            return True
        return self.publisher.is_connected()

    def _schedule_expiry(self, topic: str, ttl: int) -> None:
        expire_at = time.time() + ttl
        with self._expiry_lock:
            self._expiry_map[topic] = expire_at

    def _start_cleanup(self) -> None:
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return
        self._cleanup_running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_worker,
            name="MQTT-TTL-Cleanup",
            daemon=True
        )
        self._cleanup_thread.start()

    def _stop_cleanup(self) -> None:
        self._cleanup_running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)

    def _cleanup_worker(self) -> None:
        while self._cleanup_running:
            time.sleep(5.0)
            if not self._cleanup_running:
                break
            now = time.time()
            expired = []
            with self._expiry_lock:
                for topic, expire_at in self._expiry_map.items():
                    if expire_at <= now:
                        expired.append(topic)
            for topic in expired:
                if self.publisher.publish(topic, "", retain=True):
                    with self._expiry_lock:
                        self._expiry_map.pop(topic, None)
                else:
                    with self._expiry_lock:
                        self._expiry_map[topic] = time.time() + 10.0


# Global MQTT service instance
mqtt_service = MqttService()
