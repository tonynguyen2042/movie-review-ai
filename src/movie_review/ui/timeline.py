"""Movie Timeline UI (T090, optional Phase 11).

Visual timeline showing scenes, events, characters, and their relationships
from the movie analysis. Can be embedded in the dashboard or viewed standalone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from movie_review.artifacts import manager as artifacts
from movie_review.config.settings import load_settings


@dataclass(frozen=True)
class TimelineScene:
    """Scene data for timeline display."""
    scene_id: str
    start: float
    end: float
    duration: float
    analysis: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class TimelineEvent:
    """Event data for timeline display."""
    id: str
    type: str
    timestamp: float
    characters: list[str]
    location: str
    description: str
    importance: float


@dataclass(frozen=True)
class TimelineCharacter:
    """Character data for timeline display."""
    id: str
    name: str
    first_seen: float
    last_seen: float
    confidence: float


class MovieTimeline:
    """Generates timeline visualization data from job artifacts."""
    
    def __init__(self, jobs_dir: str | Path, job_id: str):
        self.jobs_dir = Path(jobs_dir)
        self.job_id = job_id
    
    def load(self) -> dict[str, Any]:
        """Load all timeline data from job artifacts."""
        analysis_path = self.jobs_dir / self.job_id / "movie-analysis.json"
        
        if not analysis_path.is_file():
            # Try to build from individual artifacts
            return self._build_from_artifacts()
        
        document = artifacts.read_json(analysis_path)
        return self._build_from_analysis(document)
    
    def _build_from_analysis(self, document: dict[str, Any]) -> dict[str, Any]:
        """Build timeline from canonical movie-analysis.json."""
        scenes = []
        for scene in document.get("scenes", []):
            scenes.append(TimelineScene(
                scene_id=scene.get("scene_id", ""),
                start=scene.get("start", 0.0),
                end=scene.get("end", 0.0),
                duration=scene.get("duration", 0.0),
                analysis=scene.get("analysis"),
            ))
        
        events = []
        for event in document.get("events", []):
            events.append(TimelineEvent(
                id=event.get("id", ""),
                type=event.get("type", ""),
                timestamp=event.get("timestamp", 0.0),
                characters=event.get("characters", []),
                location=event.get("location", ""),
                description=event.get("description", ""),
                importance=event.get("importance", 0.0),
            ))
        
        characters = []
        for char in document.get("characters", []):
            characters.append(TimelineCharacter(
                id=char.get("id", ""),
                name=char.get("name", ""),
                first_seen=char.get("first_seen", 0.0),
                last_seen=char.get("last_seen", 0.0),
                confidence=char.get("confidence", 0.0),
            ))
        
        # Sort by timestamp
        scenes.sort(key=lambda s: s.start)
        events.sort(key=lambda e: e.timestamp)
        characters.sort(key=lambda c: c.first_seen)
        
        return {
            "job_id": self.job_id,
            "movie_title": document.get("movie", {}).get("title", "Unknown"),
            "duration": document.get("movie", {}).get("metadata", {}).get("duration_seconds", 0.0),
            "scenes": [self._scene_to_dict(s) for s in scenes],
            "events": [self._event_to_dict(e) for e in events],
            "characters": [self._character_to_dict(c) for c in characters],
            "locations": document.get("locations", []),
        }
    
    def _build_from_artifacts(self) -> dict[str, Any]:
        """Fallback: build timeline from individual artifact files."""
        scenes_path = self.jobs_dir / self.job_id / "scenes" / "scenes.json"
        events_path = self.jobs_dir / self.job_id / "events" / "events.json"
        chars_path = self.jobs_dir / self.job_id / "characters" / "characters.json"
        
        scenes = []
        if scenes_path.is_file():
            doc = artifacts.read_json(scenes_path)
            for scene in doc.get("scenes", []):
                scenes.append(TimelineScene(
                    scene_id=scene.get("scene_id", ""),
                    start=scene.get("start", 0.0),
                    end=scene.get("end", 0.0),
                    duration=scene.get("duration", 0.0),
                ))
        
        events = []
        if events_path.is_file():
            doc = artifacts.read_json(events_path)
            for event in doc.get("events", []):
                events.append(TimelineEvent(
                    id=event.get("id", ""),
                    type=event.get("type", ""),
                    timestamp=event.get("timestamp", 0.0),
                    characters=event.get("characters", []),
                    location=event.get("location", ""),
                    description=event.get("description", ""),
                    importance=event.get("importance", 0.0),
                ))
        
        characters = []
        if chars_path.is_file():
            doc = artifacts.read_json(chars_path)
            for char in doc.get("characters", []):
                characters.append(TimelineCharacter(
                    id=char.get("id", ""),
                    name=char.get("name", ""),
                    first_seen=char.get("first_seen", 0.0),
                    last_seen=char.get("last_seen", 0.0),
                    confidence=char.get("confidence", 0.0),
                ))
        
        scenes.sort(key=lambda s: s.start)
        events.sort(key=lambda e: e.timestamp)
        characters.sort(key=lambda c: c.first_seen)
        
        return {
            "job_id": self.job_id,
            "movie_title": "Unknown",
            "duration": 0.0,
            "scenes": [self._scene_to_dict(s) for s in scenes],
            "events": [self._event_to_dict(e) for e in events],
            "characters": [self._character_to_dict(c) for c in characters],
            "locations": [],
        }
    
    def _scene_to_dict(self, scene: TimelineScene) -> dict[str, Any]:
        result = {
            "scene_id": scene.scene_id,
            "start": scene.start,
            "end": scene.end,
            "duration": scene.duration,
        }
        if scene.analysis:
            result["location"] = scene.analysis.get("location", "")
            result["characters"] = scene.analysis.get("characters", [])
            result["actions"] = scene.analysis.get("actions", [])
        return result
    
    def _event_to_dict(self, event: TimelineEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "type": event.type,
            "timestamp": event.timestamp,
            "characters": event.characters,
            "location": event.location,
            "description": event.description,
            "importance": event.importance,
        }
    
    def _character_to_dict(self, char: TimelineCharacter) -> dict[str, Any]:
        return {
            "id": char.id,
            "name": char.name,
            "first_seen": char.first_seen,
            "last_seen": char.last_seen,
            "confidence": char.confidence,
        }
    
    def to_json(self) -> str:
        """Export timeline as JSON."""
        return json.dumps(self.load(), indent=2)
    
    def to_html(self) -> str:
        """Generate standalone HTML timeline visualization."""
        data = self.load()
        return self._html_template(data)
    
    def _html_template(self, data: dict[str, Any]) -> str:
        """Generate HTML with interactive timeline using vanilla JS."""
        json_data = json.dumps(data)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Movie Timeline - {data['movie_title']}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fafafa; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        header {{ margin-bottom: 20px; }}
        h1 {{ color: #333; }}
        .meta {{ color: #666; margin-top: 8px; }}
        .timeline-wrapper {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }}
        .track {{ height: 60px; border-bottom: 1px solid #eee; position: relative; }}
        .track:last-child {{ border-bottom: none; }}
        .track-label {{ position: absolute; left: 0; top: 0; width: 120px; height: 100%; display: flex; align-items: center; padding-left: 12px; font-weight: 500; color: #333; background: #f8f9fa; border-right: 1px solid #eee; }}
        .track-content {{ margin-left: 120px; height: 100%; position: relative; }}
        .scene-block {{ position: absolute; top: 8px; height: 24px; border-radius: 4px; background: #007bff; color: white; display: flex; align-items: center; padding: 0 8px; font-size: 11px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .scene-block:hover {{ opacity: 0.8; }}
        .event-marker {{ position: absolute; top: 36px; width: 12px; height: 12px; border-radius: 50%; transform: translateX(-50%); cursor: pointer; border: 2px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }}
        .event-marker:hover {{ transform: translateX(-50%) scale(1.5); z-index: 10; }}
        .event-type-discovery {{ background: #28a745; }}
        .event-type-conflict {{ background: #dc3545; }}
        .event-type-betrayal {{ background: #6f42c1; }}
        .event-type-revelation {{ background: #fd7e14; }}
        .event-type-climax {{ background: #e83e8c; }}
        .event-type-resolution {{ background: #20c997; }}
        .event-type-default {{ background: #6c757d; }}
        .character-bar {{ position: absolute; top: 8px; height: 24px; border-radius: 4px; background: #17a2b8; display: flex; align-items: center; padding: 0 8px; font-size: 11px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .character-bar:hover {{ opacity: 0.8; }}
        .time-ruler {{ height: 30px; background: #f8f9fa; border-bottom: 1px solid #eee; display: flex; }}
        .time-marker {{ flex: 1; text-align: center; font-size: 10px; color: #666; padding-top: 8px; border-right: 1px dashed #ddd; position: relative; }}
        .time-marker::before {{ content: ''; position: absolute; top: 30px; left: 50%; height: 1000px; border-left: 1px dashed #ddd; pointer-events: none; }}
        .tooltip {{ position: fixed; background: #333; color: white; padding: 12px; border-radius: 6px; font-size: 12px; pointer-events: none; z-index: 1000; max-width: 300px; display: none; }}
        .tooltip.show {{ display: block; }}
        .legend {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 13px; }}
        .legend-color {{ width: 16px; height: 16px; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Movie Timeline: {data['movie_title']}</h1>
            <div class="meta">Duration: {data['duration']:.1f}s | Job: {data['job_id']}</div>
        </header>
        
        <div class="legend">
            <div class="legend-item"><div class="legend-color" style="background:#007bff"></div>Scenes</div>
            <div class="legend-item"><div class="legend-color" style="background:#17a2b8"></div>Characters</div>
            <div class="legend-item"><div class="legend-color event-type-discovery"></div>Discovery</div>
            <div class="legend-item"><div class="legend-color event-type-conflict"></div>Conflict</div>
            <div class="legend-item"><div class="legend-color event-type-betrayal"></div>Betrayal</div>
            <div class="legend-item"><div class="legend-color event-type-revelation"></div>Revelation</div>
            <div class="legend-item"><div class="legend-color event-type-climax"></div>Climax</div>
            <div class="legend-item"><div class="legend-color event-type-resolution"></div>Resolution</div>
        </div>
        
        <div class="timeline-wrapper" id="timeline"></div>
        <div class="tooltip" id="tooltip"></div>
    </div>
    
    <script>
        const data = {json_data};
        const timeline = document.getElementById('timeline');
        const tooltip = document.getElementById('tooltip');
        const duration = data.duration || 1;
        
        // Time ruler
        const ruler = document.createElement('div');
        ruler.className = 'time-ruler';
        const numMarkers = Math.max(10, Math.ceil(duration / 60));
        for (let i = 0; i <= numMarkers; i++) {{
            const t = (i / numMarkers) * duration;
            const marker = document.createElement('div');
            marker.className = 'time-marker';
            marker.textContent = formatTime(t);
            marker.style.flex = '1';
            ruler.appendChild(marker);
        }}
        timeline.appendChild(ruler);
        
        // Scenes track
        addTrack('Scenes', data.scenes, (scene) => {{
            const left = (scene.start / duration) * 100;
            const width = Math.max(1, (scene.duration / duration) * 100);
            return {{
                left: left + '%',
                width: width + '%',
                title: scene.scene_id,
                content: scene.scene_id + (scene.location ? ' - ' + scene.location : '')
            }};
        }}, 'scene-block');
        
        // Events track
        addTrack('Events', data.events, (event) => {{
            const left = (event.timestamp / duration) * 100;
            return {{
                left: left + '%',
                eventType: event.type.toLowerCase(),
                title: event.id,
                content: event.type + ': ' + event.description
            }};
        }}, 'event-marker');
        
        // Characters track
        addTrack('Characters', data.characters, (char) => {{
            const left = (char.first_seen / duration) * 100;
            const width = Math.max(2, ((char.last_seen - char.first_seen) / duration) * 100);
            return {{
                left: left + '%',
                width: width + '%',
                title: char.id,
                content: char.name
            }};
        }}, 'character-bar');
        
        function addTrack(label, items, renderer, blockClass) {{
            const track = document.createElement('div');
            track.className = 'track';
            track.innerHTML = '<div class="track-label">' + label + '</div><div class="track-content"></div>';
            const content = track.querySelector('.track-content');
            
            items.forEach(item => {{
                const rendered = renderer(item);
                const el = document.createElement('div');
                el.className = blockClass + (rendered.eventType ? ' event-type-' + rendered.eventType : '');
                el.style.left = rendered.left;
                if (rendered.width) el.style.width = rendered.width;
                el.textContent = rendered.content;
                el.title = rendered.title;
                
                el.addEventListener('mouseenter', (e) => showTooltip(e, rendered.content, item));
                el.addEventListener('mousemove', (e) => positionTooltip(e));
                el.addEventListener('mouseleave', hideTooltip);
                
                content.appendChild(el);
            }});
            timeline.appendChild(track);
        }}
        
        function showTooltip(e, title, item) {{
            tooltip.textContent = title;
            tooltip.classList.add('show');
            positionTooltip(e);
        }}
        
        function positionTooltip(e) {{
            tooltip.style.left = (e.clientX + 10) + 'px';
            tooltip.style.top = (e.clientY - 40) + 'px';
        }}
        
        function hideTooltip() {{
            tooltip.classList.remove('show');
        }}
        
        function formatTime(seconds) {{
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return mins + ':' + secs.toString().padStart(2, '0');
        }}
    </script>
</body>
</html>"""