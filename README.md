# FAB - Firewall Access Bot

A Telegram bot for managing firewall access with web interface and RabbitMQ integration.

## Features

- **Telegram Bot Interface**: Interactive bot with "Add Access" button
- **Authorization System**: Admins via environment variable + user whitelist
- **User Management**: Add/remove users directly through Telegram bot
- **Dynamic Link Generation**: Creates secure temporary access links
- **Web Interface**: User-friendly access management portal
- **Time-based Access Control**: Configure access duration
- **SQLite Database**: Persistent storage for sessions, requests, and users
- **Nginx Configuration**: Pre-configured nginx.conf for production deployment with rate limiting
- **RabbitMQ Integration**: Real-time messaging for access events
- **IP Address Tracking**: Monitor and log access requests

## Architecture

### Components

1. **Telegram Bot**
   - Multiple interactive buttons
   - Main functionality: "Add Access" button
   - Generates dynamic links for users
   - Configurable site URL via environment variables

2. **HTTP Server** (embedded in bot)
   - Listens on configurable HTTP port
   - Handles requests from dynamic links
   - Uniform response time for all requests
   - Redirects to main page with access status

3. **Web Interface**
   - Time selection for access duration
   - Manual access closure option
   - Real-time access status display

4. **RabbitMQ Integration** (Optional)
   - JSON message generation for access events
   - Can be enabled/disabled via `RABBITMQ_ENABLED` environment variable
   - When disabled, all RabbitMQ configuration variables are ignored
   - **Advanced Configuration**:
     - Support for custom exchanges (direct/fanout/topic/headers)
     - Configurable routing keys and queue bindings
     - Virtual host (vhost) support with auto-validation
     - Both classic and quorum queue types
     - Enterprise authentication support
   - All access events are always logged to stdout as backup
   - Message contains:
     - Access status (open/closed)
     - User IP address
     - Access duration

5. **SQLite Database**
   - Persistent storage for all data
   - Automatic schema creation on first startup
   - Tables: whitelist users, sessions, access requests
   - State preservation across container restarts

### Authorization System

**Admins**:
- Configured via `ADMIN_TELEGRAM_IDS` environment variable
- Support for multiple admins (comma-separated)
- Always have access to the bot
- Can manage user whitelist

**Whitelist**:
- Stored in SQLite database
- Managed by admins through Telegram interface
- Regular users must be added to whitelist

**Admin Commands** (available only to admins):
- 👥 **Manage Users** - main management menu
- ➕ **Add User** - add to whitelist
- 📋 **List Users** - view whitelist
- 🗑 **Remove User** - remove from whitelist

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd FAB

# Create virtual environment (for development only)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Docker

### Build and run with Docker

```bash
# Build Docker image
docker build -t fab-bot .

# Start application (replace values with your actual configuration)
docker run -d --name fab-container \
  -e TELEGRAM_BOT_TOKEN=your_bot_token_here \
  -e SITE_URL=http://your-domain.com:8080 \
  -e SECRET_KEY=your_secret_key_here \
  -p 8080:8080 \
  fab-bot

# View logs
docker logs fab-container

# Follow logs in real-time
docker logs -f fab-container

# Stop application
docker stop fab-container
docker rm fab-container
```

### Environment Configuration

The application uses a `.env` file for configuration. This file is ignored by git for security.

```bash
# Create .env from template
cp .env.example .env

# Edit .env with your real credentials
nano .env

# Check Docker container status
docker ps | grep fab-container
```

## Configuration

The application automatically loads configuration from `.env` file if present. If the file doesn't exist, it uses environment variables or defaults.

Create a `.env` file with the following variables:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Admin Configuration (comma-separated IDs)
ADMIN_TELEGRAM_IDS=123456789,987654321

# Web Server Configuration
HTTP_PORT=8080
SITE_URL=https://yourdomain.com

# Database
DATABASE_PATH=data/fab.db

# Security Configuration
SECRET_KEY=your_secret_key_here
ACCESS_TOKEN_EXPIRY=3600

# Proxy Configuration
# Set to true when running behind nginx proxy, false for direct access
NGINX_ENABLED=false

# RabbitMQ Configuration (optional)
RABBITMQ_ENABLED=false
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USERNAME=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_QUEUE=firewall_access
RABBITMQ_VHOST=/
RABBITMQ_EXCHANGE=
RABBITMQ_EXCHANGE_TYPE=direct
RABBITMQ_ROUTING_KEY=firewall.access
RABBITMQ_QUEUE_TYPE=classic
```

### Environment Variables

| Variable | Description | Default Value | Required |
|----------|-------------|---------------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather | - | ✅ |
| `ADMIN_TELEGRAM_IDS` | Admin IDs comma-separated (e.g.: 123456789,987654321) | - | ✅ |
| `SITE_URL` | Base URL for dynamic links | - | ✅ |
| `DATABASE_PATH` | Path to SQLite database file | `data/fab.db` | ❌ |
| `SECRET_KEY` | Flask secret key (generate with `openssl rand -base64 32`) | Auto-generated | ❌ |
| `HTTP_PORT` | HTTP port for web server | `8080` | ❌ |
| `HOST` | Bind address for web server | `0.0.0.0` | ❌ |
| `ACCESS_TOKEN_EXPIRY` | Session token expiry in seconds | `3600` | ❌ |
| `NGINX_ENABLED` | Enable nginx proxy mode for IP detection | `false` | ❌ |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | `INFO` | ❌ |
| `RABBITMQ_ENABLED` | Enable RabbitMQ message publishing | `false` | ❌ |
| `RABBITMQ_HOST` | RabbitMQ server hostname | `localhost` | Only if enabled |
| `RABBITMQ_PORT` | RabbitMQ server port | `5672` | Only if enabled |
| `RABBITMQ_USERNAME` | RabbitMQ username | `guest` | Only if enabled |
| `RABBITMQ_PASSWORD` | RabbitMQ password | `guest` | Only if enabled |
| `RABBITMQ_QUEUE` | RabbitMQ queue name | `firewall_access` | Only if enabled |
| `RABBITMQ_VHOST` | RabbitMQ virtual host (must start with `/`) | `/` | Only if enabled |
| `RABBITMQ_EXCHANGE` | RabbitMQ exchange name (empty = default) | `` | Only if enabled |
| `RABBITMQ_EXCHANGE_TYPE` | Exchange type (direct/fanout/topic/headers) | `direct` | Only if enabled |
| `RABBITMQ_ROUTING_KEY` | RabbitMQ routing key | `firewall.access` | Only if enabled |
| `RABBITMQ_QUEUE_TYPE` | Queue type (classic/quorum) | `classic` | Only if enabled |

## Usage

### Initial Setup

1. **Get your Telegram ID**:
   - Find @userinfobot in Telegram
   - Send `/start` command
   - Note your ID (number like 123456789)

2. **Start bot with admin privileges**:
   ```bash
   # Build and start with Docker (replace YOUR_TELEGRAM_ID with your ID)
   docker build -t fab-bot .
   docker run -d --name fab-container \
     -v fab-data:/app/data \
     -e TELEGRAM_BOT_TOKEN=your_bot_token_here \
     -e ADMIN_TELEGRAM_IDS=YOUR_TELEGRAM_ID \
     -e SITE_URL=http://your-domain.com:8080 \
     -e SECRET_KEY=your_secret_key_here \
     -p 8080:8080 \
     fab-bot
   ```

### User Management (Admin Only)

3. **Add users to whitelist**:
   - Open Telegram and find your bot
   - Send `/start` command
   - Click "👥 Manage Users" button
   - Select "➕ Add User"
   - Send user's Telegram ID

4. **View whitelist**:
   - In user management menu, select "📋 List Users"
   - Remove users with "🗑 Remove" button

### Regular Usage

5. **Create access** (for authorized users):
   - Open Telegram and find the bot
   - Send `/start` command
   - Click "🔓 Add Access" button
   - Follow the dynamic link
   - Select access duration on web interface
   - Monitor access status in real-time

**Note**: The application works without RabbitMQ - set `RABBITMQ_ENABLED=false` to run without message queue. All access events will still be logged to stdout.

### RabbitMQ Queue Types

FAB supports two types of RabbitMQ queues:

#### Classic Queues (default)
- **When to use**: Standard deployments, single-node setups, development
- **Requirements**: None special
- **Performance**: Good for most use cases
- **Configuration**: `RABBITMQ_QUEUE_TYPE=classic`

#### Quorum Queues  
- **When to use**: High-availability production deployments with clustering
- **Requirements**: 
  - RabbitMQ 3.8.0+ 
  - **Minimum 3-node cluster**
  - More RAM and CPU resources
- **Benefits**: Enhanced durability, automatic leader election, better replication
- **Configuration**: `RABBITMQ_QUEUE_TYPE=quorum`

**⚠️ Important**: Quorum queues require a RabbitMQ cluster with at least 3 nodes. For single-node deployments, use classic queues.

### RabbitMQ Configuration Examples

#### Scenario 1: Simple Setup (Recommended for most users)
```env
RABBITMQ_ENABLED=true
RABBITMQ_HOST=localhost
RABBITMQ_QUEUE=firewall_access
# Other variables use defaults
```
- Uses default exchange with direct routing to queue
- Messages go directly to `firewall_access` queue
- Simple and reliable

#### Scenario 2: Custom Exchange with Routing
```env
RABBITMQ_ENABLED=true
RABBITMQ_HOST=rabbitmq.example.com
RABBITMQ_EXCHANGE=security_events
RABBITMQ_EXCHANGE_TYPE=direct
RABBITMQ_ROUTING_KEY=firewall.access.granted
RABBITMQ_QUEUE=firewall_notifications
```
- Uses custom exchange for organizing different event types
- Allows multiple consumers for different routing keys

#### Scenario 3: Fanout for Multiple Consumers
```env
RABBITMQ_ENABLED=true
RABBITMQ_HOST=rabbitmq.example.com
RABBITMQ_EXCHANGE=broadcast_events
RABBITMQ_EXCHANGE_TYPE=fanout
RABBITMQ_QUEUE=firewall_logger
# RABBITMQ_ROUTING_KEY is ignored for fanout
```
- All messages sent to all queues bound to the exchange
- Good for monitoring, logging, and alerting systems

#### Scenario 4: Enterprise with Authentication
```env
RABBITMQ_ENABLED=true
RABBITMQ_HOST=rabbitmq-cluster.corp.com
RABBITMQ_PORT=5672
RABBITMQ_USERNAME=fab_service
RABBITMQ_PASSWORD=secure_password
RABBITMQ_VHOST=/production
RABBITMQ_QUEUE_TYPE=quorum
RABBITMQ_EXCHANGE=security_hub
RABBITMQ_ROUTING_KEY=firewall.events
```
- Production setup with authentication
- Custom vhost for isolation
- Quorum queues for high availability

#### Scenario 5: Disabled RabbitMQ (Development)
```env
RABBITMQ_ENABLED=false
# All other RABBITMQ_* variables are ignored
```
- All events logged to stdout only
- No external dependencies

### RabbitMQ Troubleshooting

#### Connection Issues
- **Error**: `Failed to connect to RabbitMQ`
- **Solutions**:
  - Check `RABBITMQ_HOST` and `RABBITMQ_PORT`
  - Verify RabbitMQ server is running
  - Check network connectivity and firewall rules
  - Validate credentials (`RABBITMQ_USERNAME`, `RABBITMQ_PASSWORD`)

#### Authentication Errors
- **Error**: `ACCESS_REFUSED` 
- **Solutions**:
  - Verify username/password are correct
  - Check if user has permissions on the vhost
  - Ensure vhost exists: `rabbitmqctl list_vhosts`

#### Queue Declaration Failures
- **Error**: `PRECONDITION_FAILED` for queue type
- **Solutions**:
  - Cannot change queue type from classic to quorum on existing queue
  - Delete existing queue or use different queue name
  - For quorum queues: ensure 3+ node cluster

#### Exchange/Routing Issues
- **Error**: Messages not reaching consumers
- **Solutions**:
  - Check exchange type matches routing strategy
  - Verify routing key bindings: `rabbitmqctl list_bindings`
  - For fanout: routing key is ignored
  - For direct: routing key must match exactly

#### Performance Considerations
- **Classic queues**: Better for single-node, development
- **Quorum queues**: Better for clusters, production
- **Fanout exchanges**: Higher resource usage
- **Direct exchanges**: Most efficient for point-to-point

## Production Deployment with nginx

For production deployment, use the included `nginx.conf` configuration file:

```bash
# Features:
- Rate limiting (3 req/min for tokens, 10 req/min for API, 60 req/min for static)  
- IP-based bruteforce protection
- Stealth mode (returns "OK" instead of error codes)
- Proper proxy headers for real IP detection
- Security headers and connection limits

# Deploy with docker-compose or standalone nginx:
nginx -c /path/to/fab/nginx.conf
```

**Security**: The nginx configuration provides comprehensive protection against:
- Token bruteforce attacks
- DDoS/flooding attacks  
- Bot scanning and enumeration
- Information disclosure through error pages

### IP Address Detection Modes

FAB supports two IP detection modes via the `NGINX_ENABLED` environment variable:

**Production Mode (`NGINX_ENABLED=true`):**
- Trusts `X-Real-IP` and `X-Forwarded-For` headers from nginx
- Gets real client IP addresses through proxy
- Recommended for production deployment

**Direct Mode (`NGINX_ENABLED=false`):**  
- FAB detects IP addresses directly from requests
- Filters out Telegram server IPs automatically
- Used for development and testing

```bash
# Production with nginx
NGINX_ENABLED=true

# Development/testing  
NGINX_ENABLED=false
```

## Development

This project is designed for Docker-only development. All code changes are automatically included when you rebuild the container.

### Makefile Commands

For convenient development, use Makefile commands:

```bash
# Build and start container
make start

# Stop container
make stop

# Restart container
make restart

# View logs
make logs

# Check container status
make status

# Create .env from example
make env-example
```

### Manual Development

```bash
# Make code changes, then rebuild and restart:
docker stop fab-container
docker rm fab-container  
docker build -t fab-bot .
docker run -d --name fab-container \
  -v fab-data:/app/data \
  -e TELEGRAM_BOT_TOKEN=your_bot_token_here \
  -e ADMIN_TELEGRAM_IDS=your_telegram_id \
  -e SITE_URL=http://your-domain.com:8080 \
  -e SECRET_KEY=your_secret_key_here \
  -p 8080:8080 \
  fab-bot

# View logs to see your changes
docker logs -f fab-container
```

## Message Format

Access events are always logged to stdout and optionally sent to RabbitMQ in JSON format:

```json
{
  "status": "open|closed",
  "ip_address": "192.168.1.100",
  "duration": 3600,
  "timestamp": "2024-01-01T12:00:00Z",
  "request_id": "uuid-here",
  "user_id": 12345
}
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Write tests if applicable
5. Submit a pull request

---

## Русская версия

Русская версия документации доступна в файле [README_RU.md](README_RU.md).
