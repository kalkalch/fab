# FAB - Firewall Access Bot

A Telegram bot for managing firewall access with web interface and MQTT integration.

## Features

- **Telegram Bot Interface**: Interactive bot with "Add Access" button
- **Authorization System**: Admins via environment variable + user whitelist
- **User Management**: Add/remove users directly through Telegram bot
- **Dynamic Link Generation**: Creates secure temporary access links
- **Web Interface**: User-friendly access management portal
- **Time-based Access Control**: Configure access duration
- **SQLite Database**: Persistent storage for sessions, requests, and users
- **Nginx Configuration**: Pre-configured nginx.conf for production deployment with rate limiting
- **MQTT Integration**: Real-time messaging for access events
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

4. **MQTT Integration**
   - Publishes access events to MQTT broker
   - Enabled/disabled via `MQTT_ENABLED`
   - Persistent connection with auto-reconnect
   - Uses `MQTT_CLIENT_ID` for client identification
   - Topic format: `mikrotik/whitelist/ip/<ip>`
   - Payload: `{"ttl": 3600}`
   - Retained empty message is published after TTL to clear topic

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

# MQTT Configuration
MQTT_ENABLED=true
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_CLIENT_ID=fab-bot
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_KEEPALIVE=60
MQTT_QOS=1
MQTT_TOPIC_PREFIX=mikrotik/whitelist/ip
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
| `MQTT_ENABLED` | Enable MQTT publishing | `true` | ❌ |
| `MQTT_HOST` | MQTT broker host | `localhost` | Only if enabled |
| `MQTT_PORT` | MQTT broker port | `1883` | Only if enabled |
| `MQTT_CLIENT_ID` | MQTT client ID | - | ✅ |
| `MQTT_USERNAME` | MQTT username | `` | Only if enabled |
| `MQTT_PASSWORD` | MQTT password | `` | Only if enabled |
| `MQTT_KEEPALIVE` | Keepalive interval (sec) | `60` | ❌ |
| `MQTT_QOS` | Publish QoS | `1` | ❌ |
| `MQTT_TOPIC_PREFIX` | Topic prefix | `mikrotik/whitelist/ip` | ❌ |

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

**Note**: The application works without MQTT — set `MQTT_ENABLED=false` to run without a broker. All access events will still be logged to stdout.

### MQTT Connection and TTL

FAB uses a **persistent MQTT connection** with auto-reconnect:

- **Persistent Connection**: Established on startup and kept alive
- **Auto-Reconnection**: Automatic reconnect on connection loss
- **Client ID**: Configured via `MQTT_CLIENT_ID`
- **Health Monitoring**: Connection status available via `/health`
- **TTL cleanup**: Retained empty message is published after TTL expires

### MQTT Message Format

- **Topic**: `mikrotik/whitelist/ip/<ip>`
- **Payload**: `{"ttl": 3600}`

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

Access events are always logged to stdout and optionally sent to MQTT:

```text
Topic: mikrotik/whitelist/ip/198.51.100.21
Payload: {"ttl": 3600}
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


## 🧪 Testing Rules

### Mandatory Testing
- ✅ After every code change: `python3 test_suite.py`
- ✅ Before every commit: `./run_tests.sh`
- ✅ Success Rate must be ≥ 99.5%
- ✅ Update `test_suite.py` for new modules

### Testing Commands
```bash
make test        # Full test suite
make test-quick  # Quick check
make test-docker # Docker test
```

### Test Categories  
- 🔍 Syntax, 📦 Imports, 🧠 Logic, ⚙️ Config
- 🗄️ Database, 📋 JSON, 🚀 Runtime, 🏗️ Classes
