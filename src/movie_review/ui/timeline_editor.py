"""Visual Timeline Editor (T094, optional Phase 11).

Interactive editor for the visual timeline, allowing drag-and-drop
clip manipulation, timing adjustments, and real-time preview.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.ui.safe_json import json_for_script


@dataclass(frozen=True)
class TimelineClip:
    """A clip in the visual timeline editor."""

    id: str
    paragraph_id: str
    scene_id: str
    clip_start: float
    clip_end: float
    timeline_start: float
    timeline_end: float
    priority: int
    reason: str
    selected: bool = False


@dataclass(frozen=True)
class TimelineTrack:
    """A track in the timeline (e.g., video, audio, subtitles)."""

    id: str
    name: str
    type: str  # video, audio, subtitle
    clips: list[TimelineClip]


class VisualTimelineEditor:
    """Visual timeline editor for movie review clips."""

    def __init__(self, jobs_dir: str | Path, job_id: str):
        self.jobs_dir = Path(jobs_dir)
        self.job_id = job_id

    def load(self) -> dict[str, Any]:
        """Load timeline data from job artifacts."""
        manifest_path = self.jobs_dir / self.job_id / "render" / "render-manifest.json"

        if not manifest_path.is_file():
            return self._empty_timeline()

        document = artifacts.read_json(manifest_path)
        return self._build_from_manifest(document)

    def _build_from_manifest(self, document: dict[str, Any]) -> dict[str, Any]:
        """Build editor data from render manifest."""
        # The manifest file holds the manifest itself, not the cache payload's
        # `{"manifest": ...}` envelope. Reading the envelope here is why the
        # editor rendered zero clips against a real manifest.
        nested = document.get("manifest")
        manifest_data = (
            nested if isinstance(nested, dict) and "segments" not in document else document
        )
        segments = manifest_data.get("segments", [])

        clips = []
        for segment in segments:
            clips.append(
                TimelineClip(
                    id=segment.get("paragraph_id", ""),
                    paragraph_id=segment.get("paragraph_id", ""),
                    scene_id=segment.get("scene_id", ""),
                    clip_start=segment.get("clip_start", 0.0),
                    clip_end=segment.get("clip_end", 0.0),
                    timeline_start=segment.get("start", 0.0),
                    timeline_end=segment.get("start", 0.0) + segment.get("duration", 0.0),
                    priority=1,
                    reason="looped" if segment.get("loop_clip", False) else "direct",
                )
            )

        # Sort by timeline start
        clips.sort(key=lambda c: c.timeline_start)

        # Group into tracks
        video_track = TimelineTrack(
            id="video",
            name="Video",
            type="video",
            clips=clips,
        )

        # Create audio track from narration segments
        audio_clips = []
        for clip in clips:
            audio_clips.append(
                TimelineClip(
                    id=f"audio_{clip.id}",
                    paragraph_id=clip.paragraph_id,
                    scene_id="",
                    clip_start=0.0,
                    clip_end=clip.timeline_end - clip.timeline_start,
                    timeline_start=clip.timeline_start,
                    timeline_end=clip.timeline_end,
                    priority=1,
                    reason="narration",
                )
            )

        audio_track = TimelineTrack(
            id="audio",
            name="Narration",
            type="audio",
            clips=audio_clips,
        )

        # Subtitle track
        subtitle_clips = []
        for clip in clips:
            subtitle_clips.append(
                TimelineClip(
                    id=f"subtitle_{clip.id}",
                    paragraph_id=clip.paragraph_id,
                    scene_id="",
                    clip_start=0.0,
                    clip_end=clip.timeline_end - clip.timeline_start,
                    timeline_start=clip.timeline_start,
                    timeline_end=clip.timeline_end,
                    priority=1,
                    reason="subtitle",
                )
            )

        subtitle_track = TimelineTrack(
            id="subtitles",
            name="Subtitles",
            type="subtitle",
            clips=subtitle_clips,
        )

        total_duration = max((c.timeline_end for c in clips), default=0.0)

        return {
            "job_id": self.job_id,
            "tracks": [
                self._track_to_dict(video_track),
                self._track_to_dict(audio_track),
                self._track_to_dict(subtitle_track),
            ],
            "total_duration": total_duration,
            "clip_count": len(clips),
        }

    def _empty_timeline(self) -> dict[str, Any]:
        """Return empty timeline structure."""
        return {
            "job_id": self.job_id,
            "tracks": [
                {"id": "video", "name": "Video", "type": "video", "clips": []},
                {"id": "audio", "name": "Narration", "type": "audio", "clips": []},
                {"id": "subtitles", "name": "Subtitles", "type": "subtitle", "clips": []},
            ],
            "total_duration": 0.0,
            "clip_count": 0,
        }

    def _track_to_dict(self, track: TimelineTrack) -> dict[str, Any]:
        return {
            "id": track.id,
            "name": track.name,
            "type": track.type,
            "clips": [self._clip_to_dict(c) for c in track.clips],
        }

    def _clip_to_dict(self, clip: TimelineClip) -> dict[str, Any]:
        return {
            "id": clip.id,
            "paragraph_id": clip.paragraph_id,
            "scene_id": clip.scene_id,
            "clip_start": clip.clip_start,
            "clip_end": clip.clip_end,
            "timeline_start": clip.timeline_start,
            "timeline_end": clip.timeline_end,
            "duration": clip.timeline_end - clip.timeline_start,
            "priority": clip.priority,
            "reason": clip.reason,
            "selected": clip.selected,
        }

    def to_json(self) -> str:
        """Export timeline as JSON."""
        return json.dumps(self.load(), indent=2)

    def to_html(self) -> str:
        """Generate standalone HTML visual timeline editor."""
        data = self.load()
        return self._html_template(data)

    def _html_template(self, data: dict[str, Any]) -> str:
        """Generate HTML with interactive visual timeline editor."""
        json_data = json_for_script(data)
        # Pre-render the tracks HTML in Python
        tracks_html = self._render_tracks(data["tracks"])
        return (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '    <meta charset="UTF-8">\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f"    <title>Visual Timeline Editor - Job {data['job_id']}</title>\n"
            "    <style>\n"
            "        * { box-sizing: border-box; margin: 0; padding: 0; }\n"
            "        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fafafa; }\n"
            "        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }\n"
            "        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }\n"
            "        h1 { color: #333; }\n"
            "        .meta { color: #666; margin-top: 8px; }\n"
            "        .stats { display: flex; gap: 16px; margin-bottom: 20px; }\n"
            "        .stat { background: white; padding: 12px 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }\n"
            "        .stat .value { font-size: 24px; font-weight: bold; color: #333; }\n"
            "        .stat .label { font-size: 12px; color: #666; }\n"
            "        .toolbar { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }\n"
            "        .btn { padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }\n"
            "        .btn:hover { background: #0056b3; }\n"
            "        .btn-secondary { background: #6c757d; }\n"
            "        .btn-secondary:hover { background: #5a6268; }\n"
            "        .btn-success { background: #28a745; }\n"
            "        .btn-success:hover { background: #218838; }\n"
            "        .btn-danger { background: #dc3545; }\n"
            "        .btn-danger:hover { background: #c82333; }\n"
            "        .timeline-editor { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }\n"
            "        .track { border-bottom: 1px solid #eee; }\n"
            "        .track:last-child { border-bottom: none; }\n"
            "        .track-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #f8f9fa; }\n"
            "        .track-name { font-weight: 600; color: #333; }\n"
            "        .track-type { background: #007bff; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }\n"
            "        .track-clips { height: 80px; position: relative; background: #fff; }\n"
            "        .clip { position: absolute; height: 40px; top: 20px; border-radius: 4px; cursor: move; display: flex; align-items: center; padding: 0 8px; font-size: 11px; color: white; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }\n"
            "        .clip.selected { outline: 2px solid #007bff; outline-offset: -2px; }\n"
            "        .clip:hover { opacity: 0.9; }\n"
            "        .clip-handle { width: 6px; height: 100%; cursor: ew-resize; opacity: 0.5; }\n"
            "        .clip-handle:hover { opacity: 1; background: rgba(255,255,255,0.2); }\n"
            "        .clip-handle.left { border-radius: 4px 0 0 4px; }\n"
            "        .clip-handle.right { border-radius: 0 4px 4px 0; }\n"
            "        .time-ruler { height: 30px; background: #f8f9fa; border-bottom: 1px solid #eee; display: flex; }\n"
            "        .time-marker { flex: 1; text-align: center; font-size: 10px; color: #666; padding-top: 8px; border-right: 1px dashed #ddd; position: relative; }\n"
            "        .tooltip { position: fixed; background: #333; color: white; padding: 12px; border-radius: 6px; font-size: 12px; pointer-events: none; z-index: 1000; max-width: 300px; display: none; }\n"
            "        .tooltip.show { display: block; }\n"
            "        .legend { display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }\n"
            "        .legend-item { display: flex; align-items: center; gap: 6px; font-size: 13px; }\n"
            "        .legend-color { width: 16px; height: 16px; border-radius: 4px; }\n"
            "        .clip-type-video { background: #007bff; }\n"
            "        .clip-type-audio { background: #28a745; }\n"
            "        .clip-type-subtitle { background: #fd7e14; }\n"
            "        .track-video { background: linear-gradient(90deg, #e7f3ff, #fff); }\n"
            "        .track-audio { background: linear-gradient(90deg, #e7ffe7, #fff); }\n"
            "        .track-subtitle { background: linear-gradient(90deg, #fff3e7, #fff); }\n"
            "        .empty-state { text-align: center; padding: 48px; color: #999; }\n"
            "        @media (max-width: 768px) {\n"
            "            .track-header { flex-direction: column; align-items: flex-start; gap: 8px; }\n"
            "        }\n"
            "    </style>\n"
            "</head>\n"
            "<body>\n"
            '    <div class="container">\n'
            "        <header>\n"
            "            <h1>Visual Timeline Editor</h1>\n"
            f'            <div class="meta">Job: {data["job_id"]}</div>\n'
            "        </header>\n"
            "\n"
            '        <div class="stats">\n'
            f'            <div class="stat"><div class="value">{data["clip_count"]}</div><div class="label">Clips</div></div>\n'
            f'            <div class="stat"><div class="value">{data["total_duration"]:.1f}s</div><div class="label">Duration</div></div>\n'
            f'            <div class="stat"><div class="value">{len(data["tracks"])}</div><div class="label">Tracks</div></div>\n'
            "        </div>\n"
            "\n"
            '        <div class="toolbar">\n'
            '            <button class="btn btn-success" onclick="saveTimeline()">Save Timeline</button>\n'
            '            <button class="btn btn-secondary" onclick="exportTimeline()">Export JSON</button>\n'
            '            <button class="btn btn-secondary" onclick="addClip()">Add Clip</button>\n'
            '            <button class="btn btn-danger" onclick="deleteSelected()">Delete Selected</button>\n'
            '            <div style="flex: 1;"></div>\n'
            '            <label>Zoom: <input type="range" id="zoomInput" min="0.5" max="5" step="0.1" value="1" style="width: 150px;"></label>\n'
            '            <span id="zoomValue">1.0x</span>\n'
            "        </div>\n"
            "\n"
            '        <div class="legend">\n'
            '            <div class="legend-item"><div class="legend-color clip-type-video"></div>Video</div>\n'
            '            <div class="legend-item"><div class="legend-color clip-type-audio"></div>Audio</div>\n'
            '            <div class="legend-item"><div class="legend-color clip-type-subtitle"></div>Subtitles</div>\n'
            "        </div>\n"
            "\n"
            '        <div class="timeline-editor" id="timeline">\n'
            '            <div class="time-ruler" id="timeRuler"></div>\n'
            f"            {tracks_html}\n"
            "        </div>\n"
            '        <div class="tooltip" id="tooltip"></div>\n'
            "    </div>\n"
            "\n"
            "    <script>\n"
            f"        const data = {json_data};\n"
            "        let selectedClipId = null;\n"
            "        let draggedClip = null;\n"
            "        let dragOffsetX = 0;\n"
            "        let zoom = 1;\n"
            "        const duration = data.total_duration || 1;\n"
            "\n"
            "        const timeline = document.getElementById('timeline');\n"
            "        const tooltip = document.getElementById('tooltip');\n"
            "        const timeRuler = document.getElementById('timeRuler');\n"
            "\n"
            "        // Initialize time ruler\n"
            "        function initTimeRuler() {\n"
            "            const numMarkers = Math.max(10, Math.ceil(duration / 30));\n"
            "            for (let i = 0; i <= numMarkers; i++) {\n"
            "                const t = (i / numMarkers) * duration;\n"
            "                const marker = document.createElement('div');\n"
            "                marker.className = 'time-marker';\n"
            "                marker.textContent = formatTime(t);\n"
            "                marker.style.flex = '1';\n"
            "                marker.style.left = `${(i / numMarkers) * 100}%`;\n"
            "                timeRuler.appendChild(marker);\n"
            "            }\n"
            "        }\n"
            "\n"
            "        function formatTime(seconds) {\n"
            "            const mins = Math.floor(seconds / 60);\n"
            "            const secs = Math.floor(seconds % 60);\n"
            "            return mins + ':' + secs.toString().padStart(2, '0');\n"
            "        }\n"
            "\n"
            "        // Initialize\n"
            "        function init() {\n"
            "            initTimeRuler();\n"
            "            setupEventListeners();\n"
            "        }\n"
            "\n"
            "        function setupEventListeners() {\n"
            "            // Clip click selection\n"
            "            document.querySelectorAll('.clip').forEach(clip => {\n"
            "                clip.addEventListener('click', (e) => {\n"
            "                    e.stopPropagation();\n"
            "                    selectClip(clip.dataset.clipId, clip.dataset.trackId);\n"
            "                });\n"
            "\n"
            "                // Drag and drop\n"
            "                clip.addEventListener('dragstart', (e) => {\n"
            "                    draggedClip = clip;\n"
            "                    dragOffsetX = e.offsetX;\n"
            "                    clip.classList.add('selected');\n"
            "                    e.dataTransfer.effectAllowed = 'move';\n"
            "                });\n"
            "\n"
            "                clip.addEventListener('dragend', () => {\n"
            "                    draggedClip = null;\n"
            "                });\n"
            "\n"
            "                // Resize handles\n"
            "                clip.querySelectorAll('.clip-handle').forEach(handle => {\n"
            "                    handle.addEventListener('mousedown', (e) => {\n"
            "                        e.stopPropagation();\n"
            "                        startResize(clip.dataset.clipId, clip.dataset.trackId, handle.classList.contains('left'));\n"
            "                    });\n"
            "                });\n"
            "            });\n"
            "\n"
            "            // Track drop zones\n"
            "            document.querySelectorAll('.track-clips').forEach(track => {\n"
            "                track.addEventListener('dragover', (e) => {\n"
            "                    e.preventDefault();\n"
            "                    e.dataTransfer.dropEffect = 'move';\n"
            "                });\n"
            "\n"
            "                track.addEventListener('drop', (e) => {\n"
            "                    e.preventDefault();\n"
            "                    if (draggedClip) {\n"
            "                        const trackId = track.dataset.trackId;\n"
            "                        const rect = track.getBoundingClientRect();\n"
            "                        const x = e.clientX - rect.left;\n"
            "                        const percent = (x / rect.width) * 100;\n"
            "                        moveClip(draggedClip.dataset.clipId, draggedClip.dataset.trackId, trackId, percent);\n"
            "                    }\n"
            "                });\n"
            "            });\n"
            "\n"
            "            // Deselect on background click\n"
            "            document.addEventListener('click', () => {\n"
            "                deselectAll();\n"
            "            });\n"
            "\n"
            "            // Zoom control\n"
            "            document.getElementById('zoomInput').addEventListener('input', (e) => {\n"
            "                zoom = parseFloat(e.target.value);\n"
            "                document.getElementById('zoomValue').textContent = zoom.toFixed(1) + 'x';\n"
            "                updateZoom();\n"
            "            });\n"
            "        }\n"
            "\n"
            "        function selectClip(clipId, trackId) {\n"
            "            document.querySelectorAll('.clip').forEach(c => c.classList.remove('selected'));\n"
            '            const clip = document.querySelector(`[data-clip-id="${clipId}"][data-track-id="${trackId}"]`);\n'
            "            if (clip) {\n"
            "                clip.classList.add('selected');\n"
            "                selectedClipId = clipId;\n"
            "                showTooltip(clip);\n"
            "            }\n"
            "        }\n"
            "\n"
            "        function deselectAll() {\n"
            "            document.querySelectorAll('.clip').forEach(c => c.classList.remove('selected'));\n"
            "            selectedClipId = null;\n"
            "            tooltip.classList.remove('show');\n"
            "        }\n"
            "\n"
            "        function showTooltip(clip) {\n"
            "            const clipData = findClipData(clip.dataset.clipId, clip.dataset.trackId);\n"
            "            if (!clipData) return;\n"
            "\n"
            "            tooltip.innerHTML = `\n"
            "                <strong>${clipData.paragraph_id || clipData.id}</strong><br>\n"
            "                Track: ${clipData.track_id}<br>\n"
            "                Start: ${formatTime(clipData.timeline_start)}<br>\n"
            "                End: ${formatTime(clipData.timeline_end)}<br>\n"
            "                Duration: ${formatTime(clipData.duration)}<br>\n"
            "                Scene: ${clipData.scene_id || 'N/A'}<br>\n"
            "                Reason: ${clipData.reason}\n"
            "            `;\n"
            "            tooltip.classList.add('show');\n"
            "            positionTooltip(clip);\n"
            "        }\n"
            "\n"
            "        function positionTooltip(clip) {\n"
            "            const rect = clip.getBoundingClientRect();\n"
            "            tooltip.style.left = (rect.right + 10) + 'px';\n"
            "            tooltip.style.top = (rect.top - 40) + 'px';\n"
            "        }\n"
            "\n"
            "        function findClipData(clipId, trackId) {\n"
            "            for (const track of data.tracks) {\n"
            "                if (track.id === trackId) {\n"
            "                    for (const clip of track.clips) {\n"
            "                        if (clip.id === clipId) return {...clip, track_id: trackId};\n"
            "                    }\n"
            "                }\n"
            "            }\n"
            "            return null;\n"
            "        }\n"
            "\n"
            "        function moveClip(clipId, fromTrackId, toTrackId, percent) {\n"
            "            if (fromTrackId === toTrackId) return;\n"
            "\n"
            "            // Find and move clip\n"
            "            let clipData = null;\n"
            "            const fromTrack = data.tracks.find(t => t.id === fromTrackId);\n"
            "            const toTrack = data.tracks.find(t => t.id === toTrackId);\n"
            "\n"
            "            if (!fromTrack || !toTrack) return;\n"
            "\n"
            "            const clipIndex = fromTrack.clips.findIndex(c => c.id === clipId);\n"
            "            if (clipIndex === -1) return;\n"
            "\n"
            "            clipData = fromTrack.clips[clipIndex];\n"
            "            fromTrack.clips.splice(clipIndex, 1);\n"
            "\n"
            "            // Update clip track\n"
            "            clipData.track_id = toTrackId;\n"
            "            clipData.id = `${toTrackId}_${clipData.paragraph_id || clipData.id}`;\n"
            "\n"
            "            // Insert at position based on percent\n"
            "            const insertIndex = Math.round(toTrack.clips.length * percent / 100);\n"
            "            toTrack.clips.splice(insertIndex, 0, clipData);\n"
            "\n"
            "            refreshTimeline();\n"
            "        }\n"
            "\n"
            "        function startResize(clipId, trackId, isLeft) {\n"
            "            // Implementation for resizing clips\n"
            "            console.log('Resize', clipId, trackId, isLeft);\n"
            "        }\n"
            "\n"
            "        function deleteSelected() {\n"
            "            if (!selectedClipId) return;\n"
            "\n"
            "            data.tracks.forEach(track => {\n"
            "                track.clips = track.clips.filter(c => c.id !== selectedClipId);\n"
            "            });\n"
            "            deselectAll();\n"
            "            refreshTimeline();\n"
            "        }\n"
            "\n"
            "        function addClip() {\n"
            "            const trackId = prompt('Enter track ID (video/audio/subtitles):', 'video');\n"
            "            const track = data.tracks.find(t => t.id === trackId);\n"
            "            if (!track) return;\n"
            "\n"
            "            const paragraphId = prompt('Enter paragraph ID:', `p${track.clips.length + 1}`);\n"
            "            const startTime = prompt('Enter start time (seconds):', '0');\n"
            "            const clipDuration = prompt('Enter duration (seconds):', '10');\n"
            "\n"
            "            const newClip = {\n"
            "                id: `${trackId}_${paragraphId}`,\n"
            "                paragraph_id: paragraphId,\n"
            "                scene_id: '',\n"
            "                clip_start: 0,\n"
            "                clip_end: parseFloat(clipDuration),\n"
            "                timeline_start: parseFloat(startTime),\n"
            "                timeline_end: parseFloat(startTime) + parseFloat(clipDuration),\n"
            "                duration: parseFloat(clipDuration),\n"
            "                priority: 1,\n"
            "                reason: 'manual',\n"
            "                selected: false,\n"
            "            };\n"
            "\n"
            "            track.clips.push(newClip);\n"
            "            refreshTimeline();\n"
            "        }\n"
            "\n"
            "        function saveTimeline() {\n"
            "            // In production, would POST to server\n"
            "            localStorage.setItem('timeline_' + data.job_id, JSON.stringify(data));\n"
            "            alert('Timeline saved to localStorage. In production, this would POST to the server.');\n"
            "        }\n"
            "\n"
            "        function exportTimeline() {\n"
            "            const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});\n"
            "            const url = URL.createObjectURL(blob);\n"
            "            const a = document.createElement('a');\n"
            "            a.href = url;\n"
            "            a.download = 'timeline.json';\n"
            "            a.click();\n"
            "            URL.revokeObjectURL(url);\n"
            "        }\n"
            "\n"
            "        function refreshTimeline() {\n"
            "            const container = document.querySelector('#timeline .track-clips, #timeline');\n"
            "            container.innerHTML = data.tracks.map(track => renderTrack(track)).join('');\n"
            "            setupEventListeners();\n"
            "        }\n"
            "\n"
            "        function renderTrack(track) {\n"
            "            const clips = track.clips.map(clip => `\n"
            '                <div class="clip clip-type-${track.type}" \n'
            '                     data-clip-id="${clip.id}" \n'
            '                     data-track-id="${track.id}"\n'
            '                     style="left: ${(clip.timeline_start / duration * 100)}%; \n'
            '                              width: ${Math.max(1, (clip.timeline_end - clip.timeline_start) / duration * 100)}%;"\n'
            '                     draggable="true">\n'
            '                        <div class="clip-handle left"></div>\n'
            "                        <span>${clip.paragraph_id || clip.id}</span>\n"
            '                        <div class="clip-handle right"></div>\n'
            "                    </div>\n"
            "            `).join('');\n"
            "\n"
            "            return `\n"
            '                <div class="track track-${track.type}" data-track-id="${track.id}">\n'
            '                    <div class="track-header">\n'
            '                        <span class="track-name">${track.name}</span>\n'
            '                        <span class="track-type">${track.type}</span>\n'
            "                    </div>\n"
            '                    <div class="track-clips" data-track-id="${track.id}">\n'
            "                        ${clips}\n"
            "                    </div>\n"
            "                </div>\n"
            "            `;\n"
            "        }\n"
            "\n"
            "        function updateZoom() {\n"
            "            // Apply zoom via CSS transform\n"
            "            document.querySelectorAll('.track-clips').forEach(el => {\n"
            "                el.style.transform = `scaleX(${zoom})`;\n"
            "                el.style.transformOrigin = 'left';\n"
            "            });\n"
            "        }\n"
            "\n"
            "        init();\n"
            "    </script>\n"
            "</body>\n"
            "</html>"
        )

    def _render_tracks(self, tracks: list[dict[str, Any]]) -> str:
        """Generate HTML for timeline tracks (Python side)."""
        if not tracks:
            return '<div class="empty-state">No tracks found</div>'

        def escape_html(text: str) -> str:
            return (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;")
            )

        tracks_html = []
        for track in tracks:
            clips_html = []
            for clip in track.get("clips", []):
                clip_class = "clip clip-type-" + track["type"]
                left = clip["timeline_start"]
                width = max(1.0, clip["timeline_end"] - clip["timeline_start"])
                label = escape_html(clip.get("paragraph_id", "") or clip["id"])
                clip_html = (
                    '<div class="' + clip_class + '" '
                    'data-clip-id="' + escape_html(clip["id"]) + '" '
                    'data-track-id="' + escape_html(track["id"]) + '" '
                    'style="left: ' + str(left) + "%; "
                    "width: " + str(width) + '%;" '
                    'draggable="true">'
                    '<div class="clip-handle left"></div>'
                    "<span>" + label + "</span>"
                    '<div class="clip-handle right"></div>'
                    "</div>"
                )
                clips_html.append(clip_html)

            track_html = (
                '<div class="track track-'
                + track["type"]
                + '" data-track-id="'
                + escape_html(track["id"])
                + '">'
                '<div class="track-header">'
                '<span class="track-name">' + escape_html(track["name"]) + "</span>"
                '<span class="track-type">' + escape_html(track["type"]) + "</span>"
                "</div>"
                '<div class="track-clips" data-track-id="'
                + escape_html(track["id"])
                + '">'
                + "".join(clips_html)
                + "</div>"
                "</div>"
            )
            tracks_html.append(track_html)

        return "".join(tracks_html)
