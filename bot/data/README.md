# Bot Data Directory

This directory stores persistent data for the assistant bot.

## Files

### memories.json

Long-term memory storage for the assistant bot. Contains user information extracted from conversations.

**Format:**
```json
{
  "version": "1.0",
  "memories": [
    {
      "id": "user_123_1234567890",
      "user_id": 123,
      "content": "用户名叫张三，是一名软件工程师",
      "category": "personal",
      "created_at": "2026-03-06T10:00:00",
      "updated_at": "2026-03-06T10:00:00",
      "tags": ["姓名", "职业"]
    }
  ]
}
```

**Categories:**
- `personal`: Personal information
- `preference`: User preferences
- `work`: Work-related information
- `fact`: Important facts
- `other`: Other information

**Manual Editing:**
This file can be manually edited. Changes take effect immediately without restart.

See `memories.example.json` for a complete example.

## Privacy

All data in this directory is stored locally and never uploaded to the cloud. Each user's data is isolated by `user_id`.

## Backup

It's recommended to backup this directory regularly:

```bash
# Backup
cp -r bot/data bot/data.backup

# Restore
cp -r bot/data.backup/* bot/data/
```

## Documentation

- Quick Start: `docs/MEMORY_QUICKSTART.md`
- Technical Details: `docs/ASSISTANT_PHASE2.md`
