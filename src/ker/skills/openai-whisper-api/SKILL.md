---
name: openai-whisper-api
description: Transcribe audio via OpenAI Audio Transcriptions API (Whisper).
homepage: https://platform.openai.com/docs/guides/speech-to-text
metadata:
  {
    "openclaw":
      {
        "emoji": "☁️",
        "requires": { "bins": ["curl"], "env": ["OPENAI_API_KEY"] },
        "primaryEnv": "OPENAI_API_KEY",
      },
  }
---

# OpenAI Whisper API (curl)

Transcribe an audio file via OpenAI’s `/v1/audio/transcriptions` endpoint.

## Quick start

```bash
src/ker/skills/openai-whisper-api/scripts/transcribe.sh /path/to/audio.m4a
```

Defaults:

- Model: `whisper-1`
- Output: `<input>.txt`

## Useful flags

```bash
src/ker/skills/openai-whisper-api/scripts/transcribe.sh /path/to/audio.ogg --model whisper-1 --out /tmp/transcript.txt
src/ker/skills/openai-whisper-api/scripts/transcribe.sh /path/to/audio.m4a --language en
src/ker/skills/openai-whisper-api/scripts/transcribe.sh /path/to/audio.m4a --prompt "Speaker names: Peter, Daniel"
src/ker/skills/openai-whisper-api/scripts/transcribe.sh /path/to/audio.m4a --json --out /tmp/transcript.json
```

## API key

Set `OPENAI_API_KEY` environment variable.

## Windows Notes

The transcribe.sh script runs via Git Bash on Windows. Alternatively, use curl directly:

```bash
curl -sS https://api.openai.com/v1/audio/transcriptions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -F "file=@/path/to/audio.m4a" \
  -F "model=whisper-1" \
  -F "response_format=text"
```
