# Bot Data Directory

This directory stores local runtime data used by assistant mode.

## Files

### `memories.json`

Primary long-term memory store for assistant mode.

- created and updated locally
- keyed by `user_id`
- safe to inspect manually
- should remain valid JSON if edited by hand

Example shape:

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

Supported categories:

- `personal`
- `preference`
- `work`
- `fact`
- `other`

### `memories.example.json`

Reference example for the same structure.

## Privacy

Data in this directory stays local to the machine. The assistant code isolates memory records by `user_id`.

## Backup

PowerShell examples:

```powershell
# Backup
Copy-Item bot/data bot/data.backup -Recurse -Force

# Restore
Copy-Item bot/data.backup/* bot/data/ -Recurse -Force
```

## Notes

- There is no additional generated documentation under `docs/` for this directory right now.
- If you change the schema in code, update this file and `memories.example.json` together.
