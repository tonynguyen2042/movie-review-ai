"""Character Explorer UI (T091, optional Phase 11).

Interactive character browser showing character details, appearances,
relationships, and evidence from the movie analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.ui.safe_json import json_for_script


@dataclass(frozen=True)
class CharacterDetail:
    """Full character detail for explorer."""

    id: str
    name: str
    aliases: list[str]
    gender: str
    first_seen: float
    last_seen: float
    confidence: float
    scenes: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    mentions: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


class CharacterExplorer:
    """Character browser for movie analysis."""

    def __init__(self, jobs_dir: str | Path, job_id: str):
        self.jobs_dir = Path(jobs_dir)
        self.job_id = job_id

    def load(self) -> dict[str, Any]:
        """Load all character data from job artifacts."""
        analysis_path = self.jobs_dir / self.job_id / "movie-analysis.json"

        if not analysis_path.is_file():
            return self._build_from_artifacts()

        document = artifacts.read_json(analysis_path)
        return self._build_from_analysis(document)

    def _build_from_analysis(self, document: dict[str, Any]) -> dict[str, Any]:
        """Build character explorer from canonical movie-analysis.json."""
        characters = []
        char_by_id = {}

        for char in document.get("characters", []):
            detail = CharacterDetail(
                id=char.get("id", ""),
                name=char.get("name", ""),
                aliases=char.get("aliases", []),
                gender=char.get("gender", ""),
                first_seen=char.get("first_seen", 0.0),
                last_seen=char.get("last_seen", 0.0),
                confidence=char.get("confidence", 0.0),
            )
            characters.append(detail)
            char_by_id[detail.id] = detail

        # Enrich with scene appearances
        for scene in document.get("scenes", []):
            analysis = scene.get("analysis")
            if analysis:
                for char_name in analysis.get("characters", []):
                    # Find character by name
                    for char in characters:
                        if char.name == char_name or char_name in char.aliases:
                            if scene.get("scene_id") not in char.scenes:
                                object.__getattribute__(char, "scenes").append(
                                    scene.get("scene_id")
                                )

        # Enrich with events
        for event in document.get("events", []):
            for char_id in event.get("characters", []):
                if char_id in char_by_id:
                    if event.get("id") not in char_by_id[char_id].events:
                        object.__getattribute__(char_by_id[char_id], "events").append(
                            event.get("id")
                        )

        # Enrich with relationships
        for rel in document.get("relationships", []):
            subj = rel.get("subject")
            obj = rel.get("object")
            if subj in char_by_id:
                object.__getattribute__(char_by_id[subj], "relationships").append(
                    {
                        "relation": rel.get("relation"),
                        "target": obj,
                        "evidence": rel.get("evidence", []),
                        "confidence": rel.get("confidence", 0.0),
                    }
                )
            if obj in char_by_id:
                object.__getattribute__(char_by_id[obj], "relationships").append(
                    {
                        "relation": rel.get("relation"),
                        "target": subj,
                        "evidence": rel.get("evidence", []),
                        "confidence": rel.get("confidence", 0.0),
                        "inverse": True,
                    }
                )

        # Sort by first_seen
        characters.sort(key=lambda c: c.first_seen)

        return {
            "job_id": self.job_id,
            "characters": [self._detail_to_dict(c) for c in characters],
            "total": len(characters),
        }

    def _build_from_artifacts(self) -> dict[str, Any]:
        """Fallback: build from individual artifact files."""
        chars_path = self.jobs_dir / self.job_id / "characters" / "characters.json"
        mentions_path = self.jobs_dir / self.job_id / "characters" / "mentions.json"
        relationships_path = self.jobs_dir / self.job_id / "relationships" / "relationships.json"
        events_path = self.jobs_dir / self.job_id / "events" / "events.json"

        characters = []
        char_by_id = {}

        if chars_path.is_file():
            doc = artifacts.read_json(chars_path)
            for char in doc.get("characters", []):
                detail = CharacterDetail(
                    id=char.get("id", ""),
                    name=char.get("name", ""),
                    aliases=char.get("aliases", []),
                    gender=char.get("gender", ""),
                    first_seen=char.get("first_seen", 0.0),
                    last_seen=char.get("last_seen", 0.0),
                    confidence=char.get("confidence", 0.0),
                )
                characters.append(detail)
                char_by_id[detail.id] = detail

        if mentions_path.is_file():
            doc = artifacts.read_json(mentions_path)
            for mention in doc.get("mentions", []):
                char_id = mention.get("character_id")
                if char_id in char_by_id:
                    object.__getattribute__(char_by_id[char_id], "mentions").append(
                        {
                            "mention": mention.get("mention"),
                            "segment_id": mention.get("source_segment_id"),
                            "timestamp": mention.get("timestamp"),
                        }
                    )

        if relationships_path.is_file():
            doc = artifacts.read_json(relationships_path)
            for rel in doc.get("relationships", []):
                subj = rel.get("subject")
                obj = rel.get("object")
                if subj in char_by_id:
                    object.__getattribute__(char_by_id[subj], "relationships").append(
                        {
                            "relation": rel.get("relation"),
                            "target": obj,
                            "evidence": rel.get("evidence", []),
                            "confidence": rel.get("confidence", 0.0),
                        }
                    )
                if obj in char_by_id:
                    object.__getattribute__(char_by_id[obj], "relationships").append(
                        {
                            "relation": rel.get("relation"),
                            "target": subj,
                            "evidence": rel.get("evidence", []),
                            "confidence": rel.get("confidence", 0.0),
                            "inverse": True,
                        }
                    )

        if events_path.is_file():
            doc = artifacts.read_json(events_path)
            for event in doc.get("events", []):
                for char_id in event.get("characters", []):
                    if char_id in char_by_id:
                        object.__getattribute__(char_by_id[char_id], "events").append(
                            event.get("id")
                        )

        characters.sort(key=lambda c: c.first_seen)

        return {
            "job_id": self.job_id,
            "characters": [self._detail_to_dict(c) for c in characters],
            "total": len(characters),
        }

    def _detail_to_dict(self, detail: CharacterDetail) -> dict[str, Any]:
        return {
            "id": detail.id,
            "name": detail.name,
            "aliases": detail.aliases,
            "gender": detail.gender,
            "first_seen": detail.first_seen,
            "last_seen": detail.last_seen,
            "confidence": detail.confidence,
            "scene_count": len(detail.scenes),
            "event_count": len(detail.events),
            "relationship_count": len(detail.relationships),
            "mention_count": len(detail.mentions),
            "scenes": detail.scenes,
            "events": detail.events,
            "relationships": detail.relationships,
            "mentions": detail.mentions,
        }

    def _render_char_list(self, characters: list[dict[str, Any]]) -> str:
        """Render the character sidebar as HTML (Python side).

        Mirrors the client-side ``_render_char_list`` so the pre-rendered
        markup and the JS refresh path agree.
        """
        if not characters:
            return '<div class="empty-state">No characters found for this job</div>'

        def escape_html(text: str) -> str:
            return (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;")
            )

        items = []
        for character in characters:
            char_id = escape_html(str(character.get("id", "")))
            name = escape_html(str(character.get("name", "")))
            aliases = character.get("aliases") or []
            alias_html = ""
            if aliases:
                joined = escape_html(", ".join(str(a) for a in aliases))
                alias_html = f" <small>({joined})</small>"
            confidence = float(character.get("confidence", 0.0)) * 100
            items.append(
                f'<div class="char-item" data-id="{char_id}" '
                f"onclick=\"selectCharacter('{char_id}')\">\n"
                f'    <div class="char-name">{name}{alias_html}</div>\n'
                '    <div class="char-meta">\n'
                f"        <span>{character.get('scene_count', 0)} scenes</span>\n"
                f"        <span>{character.get('event_count', 0)} events</span>\n"
                f"        <span>{confidence:.0f}%</span>\n"
                "    </div>\n"
                "</div>\n"
            )
        return "".join(items)

    def to_json(self) -> str:
        """Export character data as JSON."""
        return json.dumps(self.load(), indent=2)

    def to_html(self) -> str:
        """Generate standalone HTML character explorer."""
        data = self.load()
        return self._html_template(data)

    def _html_template(self, data: dict[str, Any]) -> str:
        """Generate HTML with interactive character browser."""
        json_data = json_for_script(data)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Character Explorer - Job {data["job_id"]}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fafafa; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; display: grid; grid-template-columns: 300px 1fr; gap: 20px; }}
        header {{ grid-column: 1 / -1; margin-bottom: 20px; }}
        h1 {{ color: #333; }}
        .meta {{ color: #666; margin-top: 8px; }}
        .char-list {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow-y: auto; max-height: calc(100vh - 120px); }}
        .char-item {{ padding: 16px; border-bottom: 1px solid #eee; cursor: pointer; transition: background 0.15s; }}
        .char-item:hover {{ background: #f8f9fa; }}
        .char-item.selected {{ background: #e7f3ff; border-left: 3px solid #007bff; }}
        .char-name {{ font-weight: 600; color: #333; margin-bottom: 4px; }}
        .char-meta {{ font-size: 12px; color: #666; display: flex; gap: 16px; }}
        .char-detail {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 24px; }}
        .detail-section {{ margin-bottom: 24px; }}
        .detail-section h3 {{ font-size: 14px; color: #333; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #eee; }}
        .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
        .detail-field {{ background: #f8f9fa; padding: 12px; border-radius: 6px; }}
        .detail-field label {{ font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
        .detail-field value {{ font-size: 13px; color: #333; font-weight: 500; }}
        .tag {{ display: inline-block; padding: 2px 8px; background: #e7f3ff; color: #007bff; border-radius: 12px; font-size: 11px; margin: 2px; }}
        .tag-alias {{ background: #fff3cd; color: #856404; }}
        .relationship {{ padding: 8px; background: #f8f9fa; border-radius: 4px; margin: 4px 0; font-size: 13px; }}
        .relationship-type {{ font-weight: 600; color: #007bff; }}
        .mention-item {{ font-size: 12px; color: #666; padding: 4px 0; font-family: monospace; }}
        .empty-state {{ text-align: center; padding: 48px; color: #999; }}
        @media (max-width: 1024px) {{
            .container {{ grid-template-columns: 1fr; }}
            .char-list {{ max-height: 400px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Character Explorer</h1>
            <div class="meta">Job: {data["job_id"]} | {data["total"]} characters</div>
        </header>
        
        <div class="char-list" id="charList">
            {self._render_char_list(data["characters"])}
        </div>
        
        <div class="char-detail" id="charDetail">
            <div class="empty-state" id="emptyState">
                Select a character to view details
            </div>
            <div id="detailContent" style="display: none;"></div>
        </div>
    </div>
    
    <script>
        const data = {json_data};
        const characters = data.characters;
        let selectedId = null;
        
        const charList = document.getElementById('charList');
        const detailContent = document.getElementById('detailContent');
        const emptyState = document.getElementById('emptyState');
        
        function selectCharacter(id) {{
            // Update selection
            document.querySelectorAll('.char-item').forEach(el => {{
                el.classList.toggle('selected', el.dataset.id === id);
            }});
            selectedId = id;
            
            const char = characters.find(c => c.id === id);
            if (!char) return;
            
            emptyState.style.display = 'none';
            detailContent.style.display = 'block';
            detailContent.innerHTML = renderDetail(char);
        }}
        
        function renderDetail(char) {{
            return `
                <div class="detail-section">
                    <h3>Basic Info</h3>
                    <div class="detail-grid">
                        <div class="detail-field"><label>ID</label><value>${{char.id}}</value></div>
                        <div class="detail-field"><label>Name</label><value>${{char.name}}</value></div>
                        <div class="detail-field"><label>Gender</label><value>${{char.gender || 'Unknown'}}</value></div>
                        <div class="detail-field"><label>Confidence</label><value>${{(char.confidence * 100).toFixed(0) + '%'}}</value></div>
                        <div class="detail-field"><label>First Seen</label><value>${{formatTime(char.first_seen)}}</value></div>
                        <div class="detail-field"><label>Last Seen</label><value>${{formatTime(char.last_seen)}}</value></div>
                    </div>
                    <div style="margin-top: 12px;">
                        <strong>Aliases:</strong>
                        <div>${{char.aliases.map(a => `<span class="tag tag-alias">${{a}}</span>`).join(' ') || 'None'}}</div>
                    </div>
                </div>
                
                <div class="detail-section">
                    <h3>Appearances (${{char.scenes.length}} scenes, ${{char.events.length}} events)</h3>
                    <div class="detail-grid">
                        <div class="detail-field"><label>Scenes</label><value>${{char.scenes.join(', ') || 'None'}}</value></div>
                        <div class="detail-field"><label>Events</label><value>${{char.events.join(', ') || 'None'}}</value></div>
                    </div>
                </div>
                
                ${{char.mentions && char.mentions.length > 0 ? `
                <div class="detail-section">
                    <h3>Dialogue Mentions (${{char.mentions.length}})</h3>
                    <div>
                        ${{char.mentions.map(m => `<div class="mention-item">@${{m.timestamp?.toFixed(1) || '?'}}s: "${{m.mention || ''}}" (segment: ${{m.segment_id || '?'}})</div>`).join('')}}
                    </div>
                </div>
                ` : ''}}
                
                ${{char.relationships && char.relationships.length > 0 ? `
                <div class="detail-section">
                    <h3>Relationships (${{char.relationships.length}})</h3>
                    <div>
                        ${{char.relationships.map(r => `
                            <div class="relationship">
                                <span class="relationship-type">${{r.relation}}</span> ${{r.inverse ? '←' : '→'}} ${{r.target}}
                                ${{r.evidence && r.evidence.length ? `<br><small>Evidence: ${{r.evidence.join(', ')}}</small>` : ''}}
                                ${{r.confidence ? `<br><small>Confidence: ${{(r.confidence * 100).toFixed(0) + '%'}}</small>` : ''}}
                            </div>
                        `).join('')}}
                    </div>
                </div>
                ` : ''}}
            `;
        }}
        
        function formatTime(seconds) {{
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return mins + ':' + secs.toString().padStart(2, '0');
        }}
        
        // Initial list render
        function _render_char_list(chars) {{
            return chars.map(char => `
                <div class="char-item" data-id="${{char.id}}" onclick="selectCharacter('${{char.id}}')">
                    <div class="char-name">${{char.name}}${{char.aliases.length ? ' <small>(' + char.aliases.join(', ') + ')</small>' : ''}}</div>
                    <div class="char-meta">
                        <span>${{char.scene_count}} scenes</span>
                        <span>${{char.event_count}} events</span>
                        <span>${{(char.confidence * 100).toFixed(0)}}{"%"}</span>
                    </div>
                </div>
            `).join('');
        }}
        
        charList.innerHTML = _render_char_list(characters);
    </script>
</body>
</html>"""
