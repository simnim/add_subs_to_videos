from __future__ import annotations


def format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_srt_entry(index: int, start: float, end: float, text: str) -> str:
    start_ts = format_srt_timestamp(start)
    end_ts = format_srt_timestamp(end)
    return f"{index}\n{start_ts} --> {end_ts}\n{text}\n"


def segments_to_srt(segments: list[dict]) -> str:
    parts: list[str] = []
    index = 1
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        if parts:
            parts.append("\n")
        parts.append(format_srt_entry(index, seg["start"], seg["end"], text))
        index += 1
    return "".join(parts)
