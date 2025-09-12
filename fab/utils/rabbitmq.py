"""
RabbitMQ integration module for FAB.

Handles message publishing to RabbitMQ queue for firewall access events.
"""

import json
import logging

try:
    import pika
    from pika import BlockingConnection, ConnectionParameters, PlainCredentials
    from pika.exceptions import AMQPConnectionError, AMQPChannelError
    PIKA_AVAILABLE = True
except ImportError:
    PIKA_AVAILABLE = False

from ..config import config


logger = logging.getLogger(__name__)


class RabbitMQPublisher:
    """RabbitMQ publisher for access events."""
    
    def __init__(self) -> None:
        """Initialize RabbitMQ publisher."""
        self._connection: BlockingConnection | None = None
        self._channel = None
        
    def connect(self) -> bool:
        """Establish connection to RabbitMQ."""
        if not PIKA_AVAILABLE:
            logger.error("pika library not available, RabbitMQ functionality disabled")
            return False
            
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
                heartbeat=600,
                blocked_connection_timeout=300,
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
            return False
        except Exception as e:
            logger.error(f"Unexpected error connecting to RabbitMQ: {e}")
            return False
    
    def disconnect(self) -> None:
        """Close RabbitMQ connection."""
        try:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
                logger.info("Disconnected from RabbitMQ")
        except Exception as e:
            logger.error(f"Error disconnecting from RabbitMQ: {e}")
        finally:
            self._connection = None
            self._channel = None
    
    def publish_message(self, message: str) -> bool:
        """
        Publish message to RabbitMQ queue.
        
        Args:
            message: JSON string message to publish
            
        Returns:
            bool: True if message was published successfully
        """
        if not self._is_connected():
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
            
        except AMQPChannelError as e:
            logger.error(f"Channel error publishing message: {e}")
            self.disconnect()
            return False
        except Exception as e:
            logger.error(f"Unexpected error publishing message: {e}")
            return False
    
    def _is_connected(self) -> bool:
        """Check if connection is active."""
        return (
            self._connection is not None 
            and not self._connection.is_closed 
            and self._channel is not None
        )
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


class RabbitMQService:
    """Service for managing RabbitMQ operations."""
    
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
        """Stop RabbitMQ service."""
        if self.enabled:
            logger.info("Stopping RabbitMQ service...")
            self.publisher.disconnect()
        else:
            logger.debug("RabbitMQ was disabled, nothing to stop")


# Global RabbitMQ service instance
rabbitmq_service = RabbitMQService()
