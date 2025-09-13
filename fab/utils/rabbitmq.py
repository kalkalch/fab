"""
RabbitMQ integration module for FAB.

Handles persistent connection and message publishing to RabbitMQ queue 
for firewall access events with automatic reconnection and keep-alive.
"""

import json
import logging
import threading
import time
from typing import Optional, Dict, Any

try:
    import pika
    from pika import BlockingConnection, ConnectionParameters, PlainCredentials
    from pika.exceptions import AMQPConnectionError, AMQPChannelError, ConnectionClosed
    PIKA_AVAILABLE = True
except ImportError:
    PIKA_AVAILABLE = False

from ..config import config


logger = logging.getLogger(__name__)


class RabbitMQPublisher:
    """
    Persistent RabbitMQ publisher with automatic reconnection and keep-alive.
    
    Features:
    - Persistent connection with heartbeat monitoring
    - Automatic reconnection on connection loss
    - Thread-safe operations with connection locking
    - Background keep-alive thread
    """
    
    def __init__(self) -> None:
        """Initialize RabbitMQ publisher."""
        self._connection: Optional[BlockingConnection] = None
        self._channel = None
        self._connection_lock = threading.RLock()
        self._keep_alive_thread: Optional[threading.Thread] = None
        self._keep_alive_running = False
        self._last_heartbeat = 0.0
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_delay = 5.0  # seconds
        
    def connect(self) -> bool:
        """Establish persistent connection to RabbitMQ with keep-alive."""
        if not PIKA_AVAILABLE:
            logger.error("pika library not available, RabbitMQ functionality disabled")
            return False
        
        with self._connection_lock:
            # Close existing connection if any
            self._close_connection_internal()
            
            try:
                credentials = PlainCredentials(
                    config.rabbitmq_username, 
                    config.rabbitmq_password
                )
                parameters = ConnectionParameters(
                    host=config.rabbitmq_host,
                    port=config.rabbitmq_port,
                    virtual_host=config.rabbitmq_vhost,
                    credentials=credentials,
                    heartbeat=30,  # Shorter heartbeat for faster detection
                    blocked_connection_timeout=300,
                    connection_attempts=3,
                    retry_delay=2.0,
                    socket_timeout=10.0,
                )
                
                self._connection = BlockingConnection(parameters)
                self._channel = self._connection.channel()
                
                # Declare exchange if specified (create if doesn't exist)
                if config.rabbitmq_exchange:
                    self._channel.exchange_declare(
                        exchange=config.rabbitmq_exchange,
                        exchange_type=config.rabbitmq_exchange_type,
                        durable=True
                    )
                
                # Declare queue (create if doesn't exist)
                queue_arguments = {}
                if config.rabbitmq_queue_type == "quorum":
                    queue_arguments["x-queue-type"] = "quorum"
                    # Quorum queues are always durable
                    durable = True
                else:
                    # Classic queue
                    durable = True
                
                self._channel.queue_declare(
                    queue=config.rabbitmq_queue,
                    durable=durable,
                    arguments=queue_arguments
                )
                
                # Bind queue to exchange if exchange is specified
                if config.rabbitmq_exchange:
                    # Use routing key, or queue name as fallback for direct exchange
                    binding_key = config.rabbitmq_routing_key
                    if not binding_key and config.rabbitmq_exchange_type == "direct":
                        binding_key = config.rabbitmq_queue
                    
                    self._channel.queue_bind(
                        exchange=config.rabbitmq_exchange,
                        queue=config.rabbitmq_queue,
                        routing_key=binding_key or ""  # Empty for fanout
                    )
                
                # Reset reconnection attempts on successful connection
                self._reconnect_attempts = 0
                self._last_heartbeat = time.time()
                
                # Start keep-alive thread
                self._start_keep_alive()
                
                logger.info(f"Connected to RabbitMQ at {config.rabbitmq_host}:{config.rabbitmq_port}{config.rabbitmq_vhost}")
                logger.debug(f"Using {config.rabbitmq_queue_type} queue: {config.rabbitmq_queue}")
                if config.rabbitmq_exchange:
                    logger.debug(f"Using {config.rabbitmq_exchange_type} exchange: {config.rabbitmq_exchange}")
                    if config.rabbitmq_routing_key:
                        logger.debug(f"Routing key: {config.rabbitmq_routing_key}")
                else:
                    logger.debug("Using default exchange (direct routing to queue)")
                return True
                
            except AMQPConnectionError as e:
                logger.error(f"Failed to connect to RabbitMQ: {e}")
                self._reconnect_attempts += 1
                return False
            except Exception as e:
                logger.error(f"Unexpected error connecting to RabbitMQ: {e}")
                self._reconnect_attempts += 1
                return False
    
    def disconnect(self) -> None:
        """Close RabbitMQ connection and stop keep-alive thread."""
        with self._connection_lock:
            self._stop_keep_alive()
            self._close_connection_internal()
    
    def _close_connection_internal(self) -> None:
        """Internal method to close connection (must be called with lock held)."""
        try:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
                logger.info("Disconnected from RabbitMQ")
        except Exception as e:
            logger.error(f"Error disconnecting from RabbitMQ: {e}")
        finally:
            self._connection = None
            self._channel = None
    
    def _start_keep_alive(self) -> None:
        """Start background keep-alive thread."""
        if self._keep_alive_thread and self._keep_alive_thread.is_alive():
            return
        
        self._keep_alive_running = True
        self._keep_alive_thread = threading.Thread(
            target=self._keep_alive_worker,
            name="RabbitMQ-KeepAlive",
            daemon=True
        )
        self._keep_alive_thread.start()
        logger.debug("Started RabbitMQ keep-alive thread")
    
    def _stop_keep_alive(self) -> None:
        """Stop background keep-alive thread."""
        self._keep_alive_running = False
        if self._keep_alive_thread and self._keep_alive_thread.is_alive():
            self._keep_alive_thread.join(timeout=5.0)
            logger.debug("Stopped RabbitMQ keep-alive thread")
    
    def _keep_alive_worker(self) -> None:
        """Background worker to maintain connection health."""
        while self._keep_alive_running:
            try:
                time.sleep(15.0)  # Check every 15 seconds
                
                if not self._keep_alive_running:
                    break
                
                with self._connection_lock:
                    if self._is_connected_internal():
                        # Send heartbeat to keep connection alive
                        try:
                            self._connection.process_data_events(time_limit=0.1)
                            self._last_heartbeat = time.time()
                        except Exception as e:
                            logger.warning(f"Heartbeat failed: {e}")
                            self._handle_connection_loss()
                    else:
                        logger.warning("Connection lost, attempting to reconnect...")
                        self._handle_connection_loss()
                        
            except Exception as e:
                logger.error(f"Keep-alive worker error: {e}")
                time.sleep(5.0)
    
    def _handle_connection_loss(self) -> None:
        """Handle connection loss with exponential backoff reconnection."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error(f"Max reconnection attempts ({self._max_reconnect_attempts}) reached")
            return
        
        delay = min(self._reconnect_delay * (2 ** self._reconnect_attempts), 60.0)
        logger.info(f"Reconnecting in {delay:.1f}s (attempt {self._reconnect_attempts + 1}/{self._max_reconnect_attempts})")
        
        time.sleep(delay)
        
        if self.connect():
            logger.info("Successfully reconnected to RabbitMQ")
        else:
            logger.error("Failed to reconnect to RabbitMQ")
    
    def publish_message(self, message: str) -> bool:
        """
        Publish message to RabbitMQ queue with automatic reconnection.
        
        Args:
            message: JSON string message to publish
            
        Returns:
            bool: True if message was published successfully
        """
        with self._connection_lock:
            # Ensure we have a valid connection
            if not self._is_connected_internal():
                logger.debug("Connection not available, attempting to connect...")
                if not self.connect():
                    return False
            
            try:
                # Determine exchange and routing key based on configuration
                exchange = config.rabbitmq_exchange
                
                if exchange:
                    # Using custom exchange
                    routing_key = config.rabbitmq_routing_key
                    # For fanout exchange, routing key is ignored
                    if config.rabbitmq_exchange_type == "fanout":
                        routing_key = ""
                    # For direct exchange without routing key, use queue name
                    elif not routing_key and config.rabbitmq_exchange_type == "direct":
                        routing_key = config.rabbitmq_queue
                else:
                    # Using default exchange - routing key is the queue name
                    routing_key = config.rabbitmq_queue
                
                self._channel.basic_publish(
                    exchange=exchange,
                    routing_key=routing_key,
                    body=message,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Make message persistent
                        content_type="application/json"
                    )
                )
                
                if exchange:
                    if config.rabbitmq_exchange_type == "fanout":
                        logger.info(f"Published message to fanout exchange '{exchange}' (all bound queues)")
                    else:
                        logger.info(f"Published message to {config.rabbitmq_exchange_type} exchange '{exchange}' with routing key '{routing_key}'")
                else:
                    logger.info(f"Published message to queue '{routing_key}' (default exchange)")
                logger.debug(f"Message content: {message}")
                return True
                
            except (AMQPChannelError, ConnectionClosed) as e:
                logger.error(f"Connection/channel error publishing message: {e}")
                self._handle_connection_loss()
                return False
            except Exception as e:
                logger.error(f"Unexpected error publishing message: {e}")
                return False
    
    def _is_connected_internal(self) -> bool:
        """Check if connection is active (internal, assumes lock is held)."""
        return (
            self._connection is not None 
            and not self._connection.is_closed 
            and self._channel is not None
            and not self._channel.is_closed
        )
    
    def is_connected(self) -> bool:
        """Check if connection is active (thread-safe public method)."""
        with self._connection_lock:
            return self._is_connected_internal()
    
    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection status information for monitoring."""
        with self._connection_lock:
            return {
                "connected": self._is_connected_internal(),
                "reconnect_attempts": self._reconnect_attempts,
                "max_reconnect_attempts": self._max_reconnect_attempts,
                "last_heartbeat": self._last_heartbeat,
                "keep_alive_running": self._keep_alive_running,
                "host": config.rabbitmq_host,
                "port": config.rabbitmq_port,
                "vhost": config.rabbitmq_vhost,
                "queue": config.rabbitmq_queue,
                "exchange": config.rabbitmq_exchange or "default"
            }
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


class RabbitMQService:
    """
    Service for managing RabbitMQ operations with persistent connections.
    
    Features:
    - Persistent connection management
    - Automatic reconnection with exponential backoff
    - Connection health monitoring
    - Thread-safe operations
    """
    
    def __init__(self) -> None:
        """Initialize RabbitMQ service."""
        self.publisher = RabbitMQPublisher()
        self.enabled = config.rabbitmq_enabled
    
    def publish_access_event(self, message: str) -> bool:
        """
        Publish access event message.
        
        Args:
            message: JSON string containing access event data
            
        Returns:
            bool: True if published successfully (or RabbitMQ disabled)
        """
        try:
            # Validate JSON format
            parsed_message = json.loads(message)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON message: {e}")
            return False
        
        # Always log the message to stdout
        logger.info(f"ACCESS_EVENT: {message}")
        
        # Publish to RabbitMQ only if enabled
        if not self.enabled:
            logger.debug("RabbitMQ disabled, message logged only")
            return True
        
        success = self.publisher.publish_message(message)
        if success:
            logger.debug("Message published to RabbitMQ successfully")
        else:
            logger.warning("Failed to publish message to RabbitMQ, but logged to stdout")
        
        return success
    
    def start(self) -> bool:
        """Start RabbitMQ service."""
        if not self.enabled:
            logger.info("RabbitMQ is disabled, skipping connection")
            return True
        
        logger.info("Starting RabbitMQ service...")
        return self.publisher.connect()
    
    def stop(self) -> None:
        """Stop RabbitMQ service and close persistent connections."""
        if self.enabled:
            logger.info("Stopping RabbitMQ service...")
            self.publisher.disconnect()
        else:
            logger.debug("RabbitMQ was disabled, nothing to stop")
    
    def get_status(self) -> Dict[str, Any]:
        """Get detailed RabbitMQ service status for monitoring."""
        status = {
            "enabled": self.enabled,
            "service_running": True
        }
        
        if self.enabled:
            status.update(self.publisher.get_connection_info())
        
        return status
    
    def health_check(self) -> bool:
        """Perform health check on RabbitMQ connection."""
        if not self.enabled:
            return True
        
        return self.publisher.is_connected()


# Global RabbitMQ service instance
rabbitmq_service = RabbitMQService()
