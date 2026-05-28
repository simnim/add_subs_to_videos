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


def segments_to_srt(segments: list[dict]) -> str:
    lines: list[str] = []
    index = 1
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        start_ts = format_srt_timestamp(seg["start"])
        end_ts = format_srt_timestamp(seg["end"])
        speaker = seg.get("speaker")
        lines.append(str(index))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"{speaker}: {text}" if speaker else text)
        lines.append("")
        index += 1
    return "\n".join(lines)
