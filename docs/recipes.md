# Recipes

Copy-paste examples for common workflows and automation scenarios.

## Batch Transcribe a Movie Library

```bash
add_subs_to_videos ~/Movies --model large-v3
```

Skips files that already have `.srt` files, so safe to re-run as new movies are added.

## Process Only New Files (Incremental Runs)

```bash
add_subs_to_videos ~/Movies
```

The default behavior skips existing `.srt` files, making every run incremental automatically. No special flags needed.

## Nightly Cron Job

Add to crontab (`crontab -e`):

```cron
0 2 * * * /usr/local/bin/add_subs_to_videos /mnt/videos --model medium --quiet >> /var/log/add_subs.log 2>&1
```

Runs at 2 AM daily. `--quiet` keeps the log clean; only failures and the summary are written. Check exit code in the log to detect failures.

## Cron Job with Exit Code Alerting

```bash
#!/bin/bash
add_subs_to_videos /mnt/videos --model medium --quiet
if [ $? -ne 0 ]; then
    echo "add_subs_to_videos failed at $(date)" | mail -s "Subtitle failure" you@example.com
fi
```

## Transcribe a Single File and Open the SRT

```bash
video="/path/to/talk.mp4"
add_subs_to_videos "$video" --model medium
open "${video%.mp4}.srt"   # macOS
xdg-open "${video%.mp4}.srt"  # Linux
```

## Transcribe Everything in Parallel Directories

```bash
for dir in /mnt/drive1 /mnt/drive2 /mnt/drive3; do
    add_subs_to_videos "$dir" --threads 2 --quiet &
done
wait
```

Runs three transcription processes in parallel, each limited to 2 threads so they don't saturate the CPU.

## Re-Transcribe with a Better Model

If you previously ran with `tiny` and want to upgrade to `large-v3`:

```bash
add_subs_to_videos /videos --model large-v3 --force
```

`--force` overwrites existing `.srt` files.

## Find Files Missing Subtitles

```bash
find /videos -name "*.mp4" | while read f; do
    srt="${f%.mp4}.srt"
    if [ ! -f "$srt" ]; then
        echo "Missing: $f"
    fi
done
```

## Transcribe Only Files Missing Subtitles (Shell Filter)

```bash
find /videos -name "*.mp4" | while read f; do
    srt="${f%.mp4}.srt"
    if [ ! -f "$srt" ]; then
        add_subs_to_videos "$f"
    fi
done
```

Note: `add_subs_to_videos` already does this skipping logic internally, but the above pattern is useful if you want to apply per-file logic before transcribing.

## Watch Folder with macOS launchd

Create `~/Library/LaunchAgents/com.user.add-subs-to-videos.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.add-subs-to-videos</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/add_subs_to_videos</string>
        <string>/path/to/videos</string>
        <string>--model</string>
        <string>medium</string>
        <string>--quiet</string>
    </array>
    <key>StartInterval</key>
    <integer>600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/add-subs.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/add-subs-err.log</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.user.add-subs-to-videos.plist
```

Runs every 10 minutes.

## Use the GUI Auto Re-run as a Watch Folder (No Shell Required)

1. Launch `add-subs-to-videos-gui`
2. Drop your videos folder onto the drop zone
3. Check **Auto re-run**
4. Click **Run**

The app will re-scan and re-run every 10 minutes while it's open, picking up any new files automatically.

## Generate Subtitles for a Podcast Feed

```bash
# Download episodes with yt-dlp, then transcribe
yt-dlp -x --audio-format mp3 "https://example.com/feed.rss" -o "~/Podcasts/%(title)s.%(ext)s"
add_subs_to_videos ~/Podcasts --model medium --language en
```

Note: whisper.cpp handles audio-only files (`.mp3`, `.m4a`, etc.) via its internal ffmpeg decoding — these work the same as video files.

## Batch Convert SRT to VTT (Post-Processing)

```bash
for srt in /videos/**/*.srt; do
    vtt="${srt%.srt}.vtt"
    ffmpeg -i "$srt" "$vtt" -y
done
```

Converts all generated `.srt` files to WebVTT format for web playback.
