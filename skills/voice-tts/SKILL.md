---
name: voice-tts
description: Calls the Volcengine text-to-speech API to convert Chinese narration text into voice audio files. Use when generating voiceover, narration, subtitles, Remotion videos, K12 educational videos, or MP4 dubbing.
---

# Voice TTS

## Purpose

Use this skill to generate voiceover audio for video workflows. The primary backend is Volcengine TTS. For local previews without Volcengine credentials, use the script's explicit Edge TTS fallback.

For `/workflow/video/agent`, this skill is required: convert the generated explanation text into narration audio before rendering the final MP4.

## Environment

Set these variables for Volcengine:

```bash
VOLCENGINE_TTS_APP_ID=your_app_id
VOLCENGINE_TTS_ACCESS_TOKEN=your_access_token
VOLCENGINE_TTS_CLUSTER=volcano_tts
VOLCENGINE_TTS_VOICE_TYPE=BV001_streaming
```

Optional:

```bash
VOLCENGINE_TTS_ENDPOINT=https://openspeech.bytedance.com/api/v1/tts
VOLCENGINE_TTS_ENCODING=mp3
VOLCENGINE_TTS_SPEED_RATIO=1.0
VOLCENGINE_TTS_UID=langgraph-study
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

## Generate Audio

Generate an MP3 voiceover:

```bash
python skills/voice-tts/voice_tts.py narration.txt --output out/narration.mp3
```

Generate a local preview when Volcengine credentials are missing:

```bash
python skills/voice-tts/voice_tts.py narration.txt --output out/narration.mp3 --fallback-edge-tts
```

## Video Workflow Rules

1. Build narration text from the structured source, full question, and explanation steps.
2. Generate audio with `skills/voice-tts/voice_tts.py`; the core function calls the Volcengine text-to-speech API to convert text into speech.
3. Measure the generated audio duration.
4. Synchronize Remotion scene timing to the measured audio length.
5. Render a narrated MP4 with a new filename such as `video-remotion-narrated.mp4`; do not overwrite a silent draft.
6. Keep visible video text in Simplified Chinese and render readable text in React, not inside generated images.
