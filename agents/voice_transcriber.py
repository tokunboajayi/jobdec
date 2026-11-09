"""
Voice memo transcriber for Telegram audio control.
Converts Telegram voice notes (.ogg) into clean text commands.
"""
import os
import pathlib
import subprocess
import tempfile
from typing import Optional
import speech_recognition as sr
import imageio_ffmpeg

HERE = pathlib.Path(__file__).resolve().parent.parent


def transcribe_voice_bytes(voice_bytes: bytes) -> Optional[str]:
    """Converts .ogg bytes to .wav and transcribes to text via speech_recognition."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    if not ffmpeg_exe or not pathlib.Path(ffmpeg_exe).exists():
        return None

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_f:
        ogg_f.write(voice_bytes)
        ogg_path = ogg_f.name

    wav_path = ogg_path.replace(".ogg", ".wav")

    try:
        # Convert OGG (Opus) to WAV (PCM 16-bit 16kHz)
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", ogg_path,
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            wav_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        if res.returncode != 0 or not pathlib.Path(wav_path).exists():
            return None

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
            return text.strip()
    except Exception as e:
        print(f"[Voice Transcriber Error] {e}", flush=True)
        return None
    finally:
        for p in [ogg_path, wav_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

