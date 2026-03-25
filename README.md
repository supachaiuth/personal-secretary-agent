# Personal Secretary Agent

AI-powered personal secretary built with FastAPI, LangGraph, and LangChain.

## Setup

1. Create and activate virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy environment variables:
   ```bash
   cp .env.example .env
   ```

4. Configure environment variables in `.env`:
   ```
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_anon_key
   LINE_CHANNEL_SECRET=your_channel_secret
   LINE_CHANNEL_ACCESS_TOKEN=your_access_token
   OPENAI_API_KEY=your_openai_key
   OPENAI_MODEL=gpt-4
   ```

5. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Environment Variables

| Variable | Description |
|----------|-------------|
| SUPABASE_URL | Supabase project URL |
| SUPABASE_KEY | Supabase anon/public key |
| LINE_CHANNEL_SECRET | LINE channel secret |
| LINE_CHANNEL_ACCESS_TOKEN | LINE access token |
| LLM_PROVIDER | LLM provider (openai) |
| OPENAI_API_KEY | OpenAI API key |
| OPENAI_MODEL | Model name (gpt-4) |

## Architecture

This is a planner-driven agent system:

```
LINE → webhook → intent_router → work_request_agent
                                    ↓
                              planner_agent (LLM)
                                    ↓
                              response to LINE
```

### Planner Agent

The planner analyzes user requests and returns structured JSON:

```json
{
  "request_type": "brainstorm",
  "needs_clarification": false,
  "clarification_question": null,
  "can_answer_directly": true,
  "confidence": 0.9,
  "reason": "clear ideation request"
}
```

### Supported Request Types

- `create_slide` - Create presentation slides
- `write_doc` - Write documents
- `research` - Research information
- `summarize` - Summarize content
- `draft_email` - Draft emails
- `brainstorm` - Brainstorm ideas
- `schedule` - Schedule meetings

## API Endpoints

- `GET /health` - Health check (app status)
- `GET /health/db` - Database health check (Supabase connection)
- `POST /webhook` - LINE webhook endpoint
- `GET /` - Root endpoint

## Testing

### Health Checks
```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/db
```

### LINE Webhook

1. Run ngrok:
   ```bash
   ngrok http 8000
   ```

2. Configure LINE Official Account:
   - Settings → Messaging API → Webhook settings
   - Enter your ngrok URL: `https://your-ngrok-id.ngrok-free.app/webhook`

3. Test with LINE messages:
   - "ช่วยคิดไอเดีย marketing" → Returns brainstorm response
   - "สร้างสไลด์" → Asks clarification question

## Limitations

- No tool execution (Phase 7+)
- No calendar integration
- No memory/persistence
- No LINE rich menu

## Development

Run tests:
```bash
pytest
```

## Render Deployment

### Quick Deploy

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Set the following:

| Setting | Value |
|---------|-------|
| Build Command | (empty) |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Python Version | 3.9+ |

### Environment Variables

Add these in Render dashboard:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
LINE_CHANNEL_SECRET=your-line-secret
LINE_CHANNEL_ACCESS_TOKEN=your-line-token
LLM_PROVIDER=azure
OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

### Health Check

- URL: `https://your-app.onrender.com/health`
- The app also has `/health/db` for database connectivity check

### LINE Webhook

After deploying, configure your LINE Official Account:
1. Go to LINE Official Account Manager
2. Settings → Messaging API → Webhook settings
3. Enter: `https://your-app.onrender.com/webhook`
