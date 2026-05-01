# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Development Setup
```
pip install -r requirements.txt
export DASHSCOPE_API_KEY="your_api_key_here"
```

### Running Applications
- CLI:
  ```
  python main.py
  ```
- Web UI:
  ```
  python web_app.py
  ```
  Access at http://localhost:8000

### Web API Endpoints
- `GET /api/sessions` - List all sessions
- `POST /api/sessions` - Create new session
- `GET /api/sessions/{id}` - Get session details
- `POST /api/chat` - Send message to session

### Data Storage
- Conversation history stored in `.data/conversations` (configurable via `CONVERSATION_DIR`)

## Architecture Overview

### Layered Structure
- **config/**: Configuration management (`settings.py`, `.env.example`)
- **core/**: Business logic (`orchestrator.py`, `conversation.py`, `context.py`)
- **skills/**: Plugin-based skills system (auto-registered from `.md` and `.skill` files)
- **handlers/**: Responsibility chain pattern for response processing
- **services/**: Core services (`llm_client.py`, `executor.py`, `conversation_store.py`)

### Key Design Patterns
- **Plugin System**: Skills automatically discovered in `skills/` directory
- **Responsibility Chain**: Processors in `handlers/` handle different response types
- **Dependency Injection**: For testability and separation of concerns
- **Security Controls**: Command blacklist, timeout protection, interactive command blocking

### Workflow
1. User input parsed by `utils/parser.py`
2. Processed through handler chain (`command.py`, `skill.py`, `completion.py`)
3. Skills executed via `registry.py`
4. Conversations persisted to JSON files in `.data/conversations`

## Important Files
- `main.py`: CLI entry point
- `web_app.py`: Web server entry point
- `services/llm_client.py`: Handles LLM API interactions
- `services/executor.py`: Manages command execution with safety checks

## Environment Variables
- `DASHSCOPE_API_KEY`: Required for LLM services
- `CONVERSATION_DIR`: Custom path for conversation storage
