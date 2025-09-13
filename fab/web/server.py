"""
Web server module for FAB.

Flask-based HTTP server for handling web interface requests,
access management, and dynamic link processing.
"""

import logging
import time
import re
import uuid
import ipaddress
from typing import Optional, Union
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from werkzeug.serving import make_server
import threading

from ..config import config
from ..models import access as access_module
from ..utils.rabbitmq import rabbitmq_service
from ..utils.ip_utils import is_local_ip
from ..utils.i18n import i18n


logger = logging.getLogger(__name__)

# Security validation constants
ALLOWED_DURATIONS = [3600, 10800, 28800, 43200]  # 1, 3, 8, 12 hours in seconds
MAX_DURATION = 43200  # 12 hours
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


def get_web_user_language() -> str:
    """Get user's preferred language for web interface (from session or auto-detect)."""
    # First check if user has explicitly set a language in session
    if 'language' in session:
        return session['language']
    
    # Otherwise auto-detect from Accept-Language header
    accept_language = request.headers.get('Accept-Language')
    return i18n.detect_language_from_header(accept_language)


def set_web_user_language(language_code: str) -> None:
    """Save user's language preference in session."""
    session['language'] = language_code
    i18n.set_language(language_code)


def _validate_token(token: str) -> bool:
    """Validate UUID token format to prevent injection attacks."""
    if not token or len(token) != 36:
        logger.warning(f"Invalid token format: length={len(token) if token else 0}")
        return False
    
    if not UUID_PATTERN.match(token.lower()):
        logger.warning(f"Invalid token format: {token[:8]}...")
        return False
    
    return True


def _validate_duration(duration: any) -> Optional[int]:
    """Validate duration value with strict security checks."""
    try:
        # Convert to integer
        duration_int = int(duration)
        
        # Check if it's in allowed list (prevents arbitrary values)
        if duration_int not in ALLOWED_DURATIONS:
            logger.warning(f"Duration not in allowed list: {duration_int}")
            return None
            
        # Double check against max duration
        if duration_int <= 0 or duration_int > MAX_DURATION:
            logger.warning(f"Duration out of range: {duration_int}")
            return None
            
        return duration_int
        
    except (ValueError, TypeError, OverflowError):
        logger.warning(f"Invalid duration type: {type(duration).__name__} = {duration}")
        return None


def _validate_json_data(data: any) -> Optional[dict]:
    """Validate JSON data structure."""
    if not isinstance(data, dict):
        logger.warning(f"Invalid JSON data type: {type(data).__name__}")
        return None
        
    if len(data) > 10:  # Limit number of keys
        logger.warning(f"Too many JSON keys: {len(data)}")
        return None
        
    # Check for suspicious keys that might indicate injection attempts
    suspicious_keys = ['__proto__', 'constructor', 'prototype', 'eval', 'function']
    for key in data.keys():
        if not isinstance(key, str) or key.lower() in suspicious_keys:
            logger.warning(f"Suspicious JSON key detected: {key}")
            return None
            
    return data


def _validate_ip_headers(request) -> bool:
    """Validate IP-related headers for tampering attempts."""
    # Headers that are always suspicious
    always_dangerous = [
        'x-cluster-client-ip', 'x-forwarded', 'forwarded-for',
        'x-forwarded-proto-version', 'x-real-port'
    ]
    
    # Headers that are legitimate when NGINX_ENABLED=true, suspicious otherwise
    nginx_headers = [
        'x-forwarded-host', 'x-forwarded-server', 'x-forwarded-ssl', 
        'x-forwarded-scheme', 'x-forwarded-proto'
    ]
    
    # Check for suspicious IP-related headers
    for header_name in request.headers.keys():
        header_lower = header_name.lower()
        
        # Debug logging for troubleshooting
        if header_lower in ['x-forwarded-host', 'x-forwarded-server', 'x-forwarded-ssl']:
            logger.debug(f"Processing header: {header_name} -> {header_lower}")
            logger.debug(f"nginx_enabled: {config.nginx_enabled}")
            logger.debug(f"in always_dangerous: {header_lower in always_dangerous}")
            logger.debug(f"in nginx_headers: {header_lower in nginx_headers}")
        
        if header_lower in always_dangerous:
            logger.warning(f"Suspicious IP header detected: {header_name}")
        elif header_lower in nginx_headers and not config.nginx_enabled:
            logger.warning(f"Unexpected proxy header (nginx disabled): {header_name}")
        elif header_lower in nginx_headers and config.nginx_enabled:
            logger.debug(f"Legitimate nginx header: {header_name}")
            # This is expected and legitimate - no warning needed
            
        # Check for multiple X-Forwarded-For or X-Real-IP headers (header injection)
        if header_lower in ['x-forwarded-for', 'x-real-ip']:
            header_value = request.headers.get(header_name, '')
            if ',' in header_value:
                # Multiple IPs in one header is normal for X-Forwarded-For
                if header_lower == 'x-forwarded-for':
                    # Check for reasonable number of IPs (max 5 proxies)
                    ips = [ip.strip() for ip in header_value.split(',')]
                    if len(ips) > 5:
                        logger.warning(f"Too many IPs in X-Forwarded-For: {len(ips)}")
                        return False
                else:
                    # X-Real-IP should contain only one IP
                    logger.warning(f"Multiple IPs in X-Real-IP header: {header_value}")
                    return False
    
    return True


def create_app() -> Flask:
    """Create and configure Flask application."""
    app = Flask(
        __name__,
        template_folder="../../templates",
        static_folder="../../static"
    )
    app.secret_key = config.secret_key
    
    # Configure Flask logging to not interfere with our logging
    import logging
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    @app.route("/")
    def index():
        """Return neutral response for root access."""
        return "OK", 200
    
    @app.route("/favicon.ico")
    def favicon():
        """Handle browser favicon request without hitting token route."""
        return "", 204

    @app.route("/robots.txt")
    def robots():
        """Handle robots.txt request without warnings."""
        return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.route("/health")
    def health():
        """Healthcheck endpoint for load balancers and monitors."""
        return "OK", 200
    
    @app.route("/set_language/<lang>")
    def set_language(lang: str):
        """Set user language and redirect back."""
        if lang in ['en', 'ru']:
            set_web_user_language(lang)
        
        # Redirect back to the previous page or home
        next_url = request.args.get('next', '/')
        return redirect(next_url)
    
    @app.route("/<token>")
    def access_page(token: str):
        """Access management page for valid tokens."""
        # Simulate uniform response time (security feature)
        start_time = time.time()
        
        try:
            # Security validation
            if not _validate_token(token):
                logger.warning(f"Invalid token format in access_page: {token[:8]}...")
                _wait_for_uniform_response(start_time, 0.5)
                return "OK", 200
                
            if not _validate_ip_headers(request):
                logger.warning("Invalid IP headers detected in access_page")
                _wait_for_uniform_response(start_time, 0.5)
                return "OK", 200
            
            client_ip = _get_client_ip(request)
            session = access_module.access_manager.get_session(token)
            
            if not session or session.is_expired():
                # Wait for uniform response time
                _wait_for_uniform_response(start_time, 0.5)
                return "OK", 200
            
            # Get user's preferred language (from session or auto-detect)
            language = get_web_user_language()
            i18n.set_language(language)
            
            # Set IP for session tracking (but don't mark as used yet)
            if not session.ip_address:
                session.set_ip(client_ip)
            
            # Get active requests for this user
            active_requests = access_module.access_manager.get_active_requests_for_user(session.telegram_user_id)
            
            # Wait for uniform response time
            _wait_for_uniform_response(start_time, 0.5)
            
            return render_template("access.html", 
                                 session=session,
                                 client_ip=client_ip,
                                 active_requests=active_requests,
                                 i18n=i18n)
        
        except Exception as e:
            logger.error(f"Error processing access page for token {token}: {e}")
            _wait_for_uniform_response(start_time, 0.5)
            return "OK", 200
    
    @app.route("/a/<token>", methods=["POST"])
    def open_access(token: str):
        """API endpoint to open firewall access."""
        start_time = time.time()
        
        try:
            # Security validation
            if not _validate_token(token):
                logger.warning(f"Invalid token format in open_access: {token[:8]}...")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
                
            if not _validate_ip_headers(request):
                logger.warning("Invalid IP headers detected in open_access")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            client_ip = _get_client_ip(request)
            raw_data = request.get_json()
            
            # Validate JSON structure
            data = _validate_json_data(raw_data)
            if not data or "duration" not in data:
                logger.warning(f"Invalid JSON data in open_access from IP {client_ip}")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            # Strict duration validation
            duration = _validate_duration(data["duration"])
            if duration is None:
                logger.warning(f"Invalid duration in open_access from IP {client_ip}: {data.get('duration')}")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            session = access_module.access_manager.get_session(token)
            
            if not session or session.is_expired():
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            # Check if session was already used (prevent reuse)
            if session.used:
                logger.warning(f"Attempt to reuse already used session {token[:8]}... from IP {client_ip}")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            # Mark session as used atomically
            if not session.use_atomic(client_ip):
                logger.warning(f"Failed to use session {token[:8]}... - already used by another request")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            # Ensure access_manager is initialized
            if access_module.access_manager is None:
                logger.error("Access manager not initialized during access creation")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            # Create access request
            access_request = access_module.access_manager.create_access_request(
                telegram_user_id=session.telegram_user_id,
                chat_id=session.chat_id,
                duration=duration,
                ip_address=client_ip
            )
            
            # Check if IP is local/private
            if is_local_ip(client_ip):
                logger.info(f"Access opened for user {session.telegram_user_id}, local IP: {client_ip}, duration: {duration}s - RabbitMQ message skipped")
            else:
                # Send message to RabbitMQ for external IPs only
                message = access_request.to_rabbitmq_message()
                rabbitmq_service.publish_access_event(message)
                logger.info(f"Access opened for user {session.telegram_user_id}, IP: {client_ip}, duration: {duration}s")
            
            _wait_for_uniform_response(start_time, 0.3)
            return jsonify({
                "success": True,
                "access_id": access_request.id,
                "expires_at": access_request.expires_at.isoformat() if access_request.expires_at else None
            })
        
        except ValueError:
            _wait_for_uniform_response(start_time, 0.3)
            return "OK", 200
        except Exception as e:
            logger.error(f"Error opening access: {e}")
            _wait_for_uniform_response(start_time, 0.3)
            return "OK", 200
    
    @app.route("/c/<access_id>", methods=["POST"])
    def close_access(access_id: str):
        """API endpoint to close firewall access."""
        start_time = time.time()
        
        try:
            # Validate access_id format (should be UUID)
            if not _validate_token(access_id):
                logger.warning(f"Invalid access_id format in close_access: {access_id[:8]}...")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
                
            if not _validate_ip_headers(request):
                logger.warning("Invalid IP headers detected in close_access")
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            raw_data = request.get_json()
            data = _validate_json_data(raw_data) if raw_data else None
            token = data.get("token") if data else None
            
            if token:
                # Validate token format
                if not _validate_token(token):
                    logger.warning(f"Invalid token format in close_access: {token[:8]}...")
                    _wait_for_uniform_response(start_time, 0.3)
                    return "OK", 200
                    
                session = access_module.access_manager.get_session(token)
                if not session or session.is_expired():
                    _wait_for_uniform_response(start_time, 0.3)
                    return "OK", 200
            
            # Close access request
            access_request = access_module.access_manager.close_access_request(access_id)
            
            if not access_request:
                _wait_for_uniform_response(start_time, 0.3)
                return "OK", 200
            
            # Check if IP is local/private
            if is_local_ip(access_request.ip_address):
                logger.info(f"Access closed for request {access_request.id}, local IP: {access_request.ip_address} - RabbitMQ message skipped")
            else:
                # Send message to RabbitMQ for external IPs only
                message = access_request.to_rabbitmq_message()
                rabbitmq_service.publish_access_event(message)
                logger.info(f"Access closed for request {access_request.id}")
            
            _wait_for_uniform_response(start_time, 0.3)
            return jsonify({
                "success": True,
                "closed_at": access_request.closed_at.isoformat() if access_request.closed_at else None
            })
        
        except Exception as e:
            logger.error(f"Error closing access: {e}")
            _wait_for_uniform_response(start_time, 0.3)
            return "OK", 200
    
    @app.route("/s/<access_id>")
    def access_status(access_id: str):
        """API endpoint to check access status."""
        start_time = time.time()
        
        try:
            # Validate access_id format (should be UUID)
            if not _validate_token(access_id):
                logger.warning(f"Invalid access_id format in access_status: {access_id[:8]}...")
                _wait_for_uniform_response(start_time, 0.2)
                return "OK", 200
                
            if not _validate_ip_headers(request):
                logger.warning("Invalid IP headers detected in access_status")
                _wait_for_uniform_response(start_time, 0.2)
                return "OK", 200
            
            access_request = access_module.access_manager.get_access_request(access_id)
            
            _wait_for_uniform_response(start_time, 0.2)
            
            if not access_request:
                return "OK", 200
            
            return jsonify({
                "access_id": access_request.id,
                "status": access_request.status.value,
                "ip_address": access_request.ip_address,
                "created_at": access_request.created_at.isoformat(),
                "expires_at": access_request.expires_at.isoformat() if access_request.expires_at else None,
                "closed_at": access_request.closed_at.isoformat() if access_request.closed_at else None,
                "is_expired": access_request.is_expired()
            })
        
        except Exception as e:
            logger.error(f"Error getting access status for {access_id}: {e}")
            _wait_for_uniform_response(start_time, 0.2)
            return "OK", 200
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors with neutral response."""
        return "OK", 200
    
    return app


def _validate_ip_address(ip_str: str) -> str:
    """Validate IP address format and return normalized IP."""
    try:
        # Parse and validate IP address
        ip_obj = ipaddress.ip_address(ip_str.strip())
        
        # Check for dangerous IP ranges
        if ip_obj.is_private and not ip_obj.is_loopback:
            logger.debug(f"Private IP detected: {ip_obj}")
        elif ip_obj.is_loopback:
            logger.debug(f"Loopback IP detected: {ip_obj}")
        elif ip_obj.is_multicast:
            logger.warning(f"Multicast IP rejected: {ip_obj}")
            return "127.0.0.1"
        elif ip_obj.is_reserved:
            logger.warning(f"Reserved IP rejected: {ip_obj}")
            return "127.0.0.1"
            
        return str(ip_obj)
        
    except (ipaddress.AddressValueError, ValueError) as e:
        logger.warning(f"Invalid IP address format '{ip_str}': {e}")
        return "127.0.0.1"


def _get_client_ip(request) -> str:
    """Extract client IP address from request with validation."""
    
    if config.nginx_enabled:
        # NGINX MODE: Trust but validate proxy headers from nginx
        logger.debug("NGINX mode: Using proxy headers for IP detection")
        
        # nginx sets X-Real-IP with the actual client IP
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            validated_ip = _validate_ip_address(real_ip)
            logger.debug(f"Using nginx X-Real-IP: {real_ip} -> {validated_ip}")
            return validated_ip
            
        # Fallback to X-Forwarded-For from nginx
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
            validated_ip = _validate_ip_address(client_ip)
            logger.debug(f"Using nginx X-Forwarded-For: {client_ip} -> {validated_ip}")
            return validated_ip
            
        # Should not happen with proper nginx config
        logger.warning("NGINX mode but no proxy headers found")
        return "127.0.0.1"
        
    else:
        # DIRECT MODE: FAB determines IP itself (current logic)
        logger.debug("Direct mode: FAB detecting IP with Telegram filtering")
        
        forwarded_for = request.headers.get("X-Forwarded-For")
        real_ip = request.headers.get("X-Real-IP")
        remote_addr = request.remote_addr
        
        # Skip Telegram server IPs - they are not real users
        telegram_ips = ["149.154.167.", "149.154.175.", "91.108.4.", "91.108.56.", "91.108.8."]
        
        if remote_addr:
            for telegram_ip in telegram_ips:
                if remote_addr.startswith(telegram_ip):
                    logger.debug(f"Skipping Telegram server IP: {remote_addr}")
                    return "127.0.0.1"  # Default fallback for Telegram requests
        
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
            # Check if forwarded IP is also Telegram
            for telegram_ip in telegram_ips:
                if client_ip.startswith(telegram_ip):
                    logger.debug(f"Skipping Telegram forwarded IP: {client_ip}")
                    return "127.0.0.1"
            validated_ip = _validate_ip_address(client_ip)
            logger.debug(f"Using X-Forwarded-For IP: {client_ip} -> {validated_ip}")
            return validated_ip
        elif real_ip:
            validated_ip = _validate_ip_address(real_ip)
            logger.debug(f"Using X-Real-IP: {real_ip} -> {validated_ip}")
            return validated_ip
        else:
            validated_ip = _validate_ip_address(remote_addr or "127.0.0.1")
            logger.debug(f"Using remote_addr: {remote_addr} -> {validated_ip}")
            return validated_ip


def _wait_for_uniform_response(start_time: float, target_duration: float) -> None:
    """Wait to ensure uniform response time."""
    elapsed = time.time() - start_time
    if elapsed < target_duration:
        time.sleep(target_duration - elapsed)


class WebServer:
    """Web server wrapper for threading support."""
    
    def __init__(self) -> None:
        """Initialize web server."""
        self.app = create_app()
        self.server = None
        self.thread = None
    
    def start(self) -> None:
        """Start web server in a separate thread."""
        try:
            self.server = make_server(
                config.host,
                config.http_port,
                self.app,
                threaded=True
            )
            
            self.thread = threading.Thread(target=self.server.serve_forever)
            self.thread.daemon = True
            self.thread.start()
            
            logger.info(f"Web server started on {config.host}:{config.http_port}")
            
        except Exception as e:
            logger.error(f"Failed to start web server: {e}")
            raise
    
    def stop(self) -> None:
        """Stop web server."""
        try:
            if self.server:
                self.server.shutdown()
                logger.info("Web server stopped")
        except Exception as e:
            logger.error(f"Error stopping web server: {e}")


def create_server() -> WebServer:
    """Create and return a new web server instance."""
    return WebServer()
