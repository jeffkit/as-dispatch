# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Agent Studio Dispatch is a message forwarding service that establishes a communication channel between WeChat Work (Enterprise WeChat) bots and external Agent Studio services. It acts as a bridge, receiving messages from WeChat Work bots, forwarding them to configured endpoints, and returning responses to users.

**Core functionality:**
- Bidirectional message forwarding between WeChat Work and Agent Studio
- Multi-bot management with individual configurations
- WebSocket tunnel support for internal network penetration (via tunely)
- Access control (whitelist/blacklist) per bot
- User project management for flexible routing
- Session persistence for conversation continuity
- Admin slash commands for bot/project/tunnel management

## Development Commands

### Running the Application

```bash
# Standard startup (database mode, recommended)
USE_DATABASE=true uv run python -m forward_service.app

# With specific port
FORWARD_PORT=8084 uv run python -m forward_service.app

# With MySQL database
DATABASE_URL="mysql+pymysql://user:pass@host:port/db" uv run python -m forward_service.app

# Development mode with SQLite
DATABASE_URL="sqlite+aiosqlite:///./data/forward_service.db" uv run python -m forward_service.app
```

### Database Operations

```bash
# Run database migrations (required after schema changes)
alembic upgrade head

# Create a new migration after modifying models.py
alembic revision --autogenerate -m "description of changes"

# View current migration version
alembic current

# Rollback one migration
alembic downgrade -1

# Generate SQL for production review (offline mode)
alembic upgrade head --sql
```

### Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_callback.py

# Run with coverage report
uv run pytest --cov=forward_service --cov-report=html

# Run end-to-end tunnel tests
uv run pytest tests/test_e2e_tunnel.py -v

# Run a single test function
uv run pytest tests/test_callback.py::test_callback_handler -v
```

### Linting and Code Quality

```bash
# Run ruff linter
uv run ruff check forward_service tests

# Auto-fix issues
uv run ruff check --fix forward_service tests

# Note: E712 is ignored for SQLAlchemy (requires `== True/False` for SQL expressions)
```

## Architecture Overview

### Application Flow

```
WeChat Work Bot → POST /callback → Forward Service → Agent Studio API
                      ↓                                    ↓
                 Access Control                         Response
                      ↓                                    ↓
              Session Lookup                    Message Splitter
                      ↓                                    ↓
                 Forward Logic → Log → Reply to WeChat Work
```

### Key Components

1. **Webhook Handler** (`/callback` endpoint)
   - Receives messages from WeChat Work bots
   - Supports multi-bot configuration via URL parameters
   - Entry point: `forward_service/routes/callback.py`

2. **Configuration Manager** (`config.py`)
   - Database-first configuration (preferred)
   - JSON file fallback for simple setups
   - Dynamic updates without restart required
   - Manages bot configs, access control, and user projects

3. **Session Manager** (`session_manager.py`)
   - Maintains conversation state across requests
   - Stores user sessions in database for continuity
   - Supports project-based routing configuration

4. **Forward Service** (`forward.py`)
   - Routes messages to Agent Studio endpoints
   - Handles HTTP communication with external services
   - Processes responses and manages errors

5. **Message Splitter** (`sender.py`)
   - Automatically splits long messages (>2000 chars) for WeChat Work
   - Handles text and image messages
   - Implements retry logic for failed sends

6. **Tunnel Server** (`tunnel.py`)
   - Integrates tunely for WebSocket tunneling
   - Enables external access to internal network services
   - Token-based authentication for secure connections

7. **Database Layer** (`database.py`, `models.py`)
   - SQLAlchemy 2.0 ORM with async support
   - Supports both SQLite (dev) and MySQL (prod)
   - Alembic for schema migrations

### Database Models

Located in `forward_service/models.py`:

- **Chatbot**: Bot configurations (name, target_url, access_mode, enabled)
- **ChatAccessRule**: Whitelist/blacklist rules per bot
- **UserProjectConfig**: User-specific project routing configurations
- **UserSession**: Session persistence for conversation continuity
- **ForwardLog**: Request/response logging for debugging
- **ProcessingSession**: Prevents concurrent processing of same message
- **ChatInfo**: Tracks chat type (group vs single chat)
- **SystemConfig**: Global system configuration

### Route Organization

- `/` - Root health check
- `/health` - System health check
- `/callback` - WeChat Work webhook endpoint (primary message entry)
- `/admin` - Admin API for configuration management
  - `/admin/bots` - Bot CRUD operations
  - `/admin/logs` - Request logs
  - `/admin/tunnels` - Tunnel management UI
- `/ws/tunnel` - WebSocket tunnel endpoint

## Configuration Patterns

### Database Configuration (Recommended)

All configuration stored in database tables:
- Bots configured in `chatbots` table
- Access rules in `chat_access_rules` table
- User projects in `user_project_configs` table
- Supports runtime updates without service restart

### Access Control Modes

Three modes per bot:
- `allow_all`: Anyone can use the bot
- `whitelist`: Only whitelisted users can use (specify in access rules)
- `blacklist`: All users except blacklisted can use

### User Projects

Users can create projects with independent forwarding configurations:
- Projects route to different Agent Studio endpoints
- Users can switch between projects via commands
- Supports flexible testing and deployment workflows

## Slash Commands

Users can manage the system via WeChat Work messages:

### Bot Management (admin only)
```
/bots                    - List all bots
/bot create <key>        - Create a new bot
/bot delete <key>        - Delete a bot
```

### Project Management
```
/projects                - List my projects
/project create <name>   - Create a new project
/ap <project> <url>      - Add project forwarding configuration
/project delete <name>   - Delete a project
```

### Tunnel Management
```
/tunnel create <domain>  - Create a tunnel
/tunnels                 - List all tunnels
/tunnel token <domain>   - Get tunnel token for connection
/tunnel delete <domain>  - Delete a tunnel
```

## Testing Strategy

### Test Categories

- **Unit tests**: Individual component testing (models, config, utilities)
- **Integration tests**: Database and API endpoint testing
- **E2E tests**: Full workflow testing including tunnel functionality

### Test Database

Tests use in-memory SQLite for fast execution:
- Configured in `conftest.py` fixtures
- Automatically creates/destroys schema per test
- No external dependencies required

### Key Test Patterns

- Mock external HTTP calls (Agent Studio, WeChat Work APIs)
- Use pytest-asyncio for async function testing
- Database fixtures with clean state per test
- Coverage threshold checking via pytest-cov

## External Dependencies

- **fly-pigeon**: WeChat Work API integration (message sending)
- **tunely**: WebSocket tunnel framework for internal network access
- **httpx**: Async HTTP client for Agent Studio communication
- **FastAPI**: Web framework with async support
- **SQLAlchemy 2.0**: ORM with async engine support
- **Alembic**: Database migration management

## Important Implementation Notes

### Message Handling

- WeChat Work has a 2048 character limit for text messages
- Messages >2000 chars are automatically split with " (1/n)" prefixes
- Split messages maintain proper ordering and delivery confirmation
- Retry logic implements exponential backoff for failed sends

### Session Management

- Sessions persist across requests to maintain conversation context
- Each user can have one active session per bot
- Sessions are stored in database and loaded on first message
- Project configuration overrides bot default target URL

### Concurrent Request Prevention

- `ProcessingSession` model prevents duplicate processing of same message
- Uses message ID + bot key as unique identifier
- Automatic cleanup after processing completes

### Error Handling

- All forwarding errors are logged to `ForwardLog` table
- Users receive friendly error messages via WeChat Work
- Failed requests include full response details for debugging
- Tunnel errors tracked separately in tunely's logging system

### Performance Considerations

- Database connection pooling for MySQL (via SQLAlchemy)
- Async I/O throughout the stack (FastAPI, httpx, SQLAlchemy)
- Index optimization on frequently queried fields (bot_key, userid)
- In-memory caching of configuration (loaded at startup, refreshed on changes)

## Migration Notes

### Adding New Models

1. Add model to `forward_service/models.py`
2. Generate migration: `alembic revision --autogenerate -m "Add new model"`
3. Review generated SQL in `alembic/versions/`
4. Test migration on SQLite then MySQL
5. Apply: `alembic upgrade head`

### Database Support

- **Development**: SQLite with aiosqlite (default)
- **Production**: MySQL with aiomysql/pymysql
- Models are database-agnostic (works on both engines)
- Always test migrations on target database before deploying

## Package Manager

This project uses **uv** as the package manager (faster alternative to pip):

```bash
# Install dependencies
uv sync

# Run commands
uv run pytest
uv run python -m forward_service.app

# Add dependencies
uv add package-name
```

Package metadata in `pyproject.toml` uses author: jeffkit <bbmyth@gmail.com>
