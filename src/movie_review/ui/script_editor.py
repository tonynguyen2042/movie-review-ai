"""Script Editor UI (T093, optional Phase 11).

Interactive editor for reviewing and modifying the review script.
Shows sections, paragraphs, claims, and evidence with inline editing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from movie_review.artifacts import manager as artifacts


@dataclass(frozen=True)
class ScriptParagraph:
    """Paragraph in the review script."""
    id: str
    section_id: str
    text: str
    claims: list[dict[str, Any]]
    target_seconds: float


@dataclass(frozen=True)
class ScriptSection:
    """Section in the review script."""
    id: str
    type: str
    target_seconds: float
    purpose: str
    event_ids: list[str]
    paragraphs: list[ScriptParagraph]


class ScriptEditor:
    """Script editor for review script."""
    
    def __init__(self, jobs_dir: str | Path, job_id: str):
        self.jobs_dir = Path(jobs_dir)
        self.job_id = job_id
    
    def load(self) -> dict[str, Any]:
        """Load script from job artifacts."""
        script_path = self.jobs_dir / self.job_id / "review-script.json"
        
        if not script_path.is_file():
            return self._empty_script()
        
        document = artifacts.read_json(script_path)
        return self._build_from_script(document)
    
    def _build_from_script(self, document: dict[str, Any]) -> dict[str, Any]:
        """Build editor data from review script."""
        script_data = document.get("script", {})
        sections = []
        
        for section in script_data.get("sections", []):
            paragraphs = []
            for para in section.get("paragraphs", []):
                paragraphs.append(ScriptParagraph(
                    id=para.get("id", ""),
                    section_id=section.get("id", ""),
                    text=para.get("text", ""),
                    claims=para.get("claims", []),
                    target_seconds=para.get("target_seconds", 0.0),
                ))
            
            sections.append(ScriptSection(
                id=section.get("id", ""),
                type=section.get("type", ""),
                target_seconds=section.get("target_seconds", 0),
                purpose=section.get("purpose", ""),
                event_ids=section.get("event_ids", []),
                paragraphs=paragraphs,
            ))
        
        sections.sort(key=lambda s: s.id)
        
        # Calculate word count
        total_words = sum(len(p.text.split()) for s in sections for p in s.paragraphs)
        
        word_count = script_data.get("word_count", total_words)
        
        return {
            "job_id": self.job_id,
            "sections": [self._section_to_dict(s) for s in sections],
            "total_sections": len(sections),
            "total_paragraphs": sum(len(s.paragraphs) for s in sections),
            "total_words": total_words,
            "word_count": word_count,
        }
    
    def _empty_script(self) -> dict[str, Any]:
        """Return empty script structure."""
        return {
            "job_id": self.job_id,
            "sections": [],
            "total_sections": 0,
            "total_paragraphs": 0,
            "total_words": 0,
            "word_count": 0,
        }
    
    def _section_to_dict(self, section: ScriptSection) -> dict[str, Any]:
        return {
            "id": section.id,
            "type": section.type,
            "target_seconds": section.target_seconds,
            "purpose": section.purpose,
            "event_ids": section.event_ids,
            "paragraphs": [
                {
                    "id": p.id,
                    "text": p.text,
                    "claims": p.claims,
                    "target_seconds": p.target_seconds,
                    "word_count": len(p.text.split()),
                }
                for p in section.paragraphs
            ],
        }
    
    def to_json(self) -> str:
        """Export script as JSON."""
        return json.dumps(self.load(), indent=2)
    
    def to_html(self) -> str:
        """Generate standalone HTML script editor."""
        data = self.load()
        return self._html_template(data)
    
    def _html_template(self, data: dict[str, Any]) -> str:
        """Generate HTML with interactive script editor."""
        json_data = json.dumps(data)
        # Pre-render the script HTML in Python
        script_html = self._render_script_html(data)
        return (
            "<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "    <meta charset=\"UTF-8\">\n"
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
            f"    <title>Script Editor - Job {data['job_id']}</title>\n"
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
            "        .script-editor { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }\n"
            "        .section { border-bottom: 1px solid #eee; }\n"
            "        .section:last-child { border-bottom: none; }\n"
            "        .section-header { display: flex; justify-content: space-between; align-items: center; padding: 16px; background: #f8f9fa; }\n"
            "        .section-info { display: flex; gap: 16px; align-items: center; }\n"
            "        .section-type { background: #007bff; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }\n"
            "        .section-purpose { color: #666; font-size: 14px; }\n"
            "        .section-stats { display: flex; gap: 16px; font-size: 12px; color: #666; }\n"
            "        .paragraph { padding: 16px; border-bottom: 1px solid #eee; }\n"
            "        .paragraph:last-child { border-bottom: none; }\n"
            "        .paragraph-header { display: flex; justify-content: space-between; margin-bottom: 8px; }\n"
            "        .paragraph-id { font-family: monospace; font-size: 12px; color: #666; }\n"
            "        .paragraph-text { font-size: 15px; line-height: 1.7; color: #333; white-space: pre-wrap; margin-bottom: 12px; }\n"
            "        .paragraph-text.editing { background: #fffde7; padding: 8px; border-radius: 4px; border: 1px solid #ffc107; }\n"
            "        .claims { margin-top: 12px; }\n"
            "        .claim { display: inline-block; background: #e7f3ff; color: #007bff; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin: 2px 4px 2px 0; }\n"
            "        .claim.evidence { background: #d4edda; color: #155724; }\n"
            "        .claim.opinion { background: #fff3cd; color: #856404; }\n"
            "        .edit-textarea { width: 100%; min-height: 100px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-family: inherit; font-size: 15px; line-height: 1.7; resize: vertical; }\n"
            "        .edit-actions { margin-top: 8px; display: flex; gap: 8px; }\n"
            "        .empty-state { text-align: center; padding: 48px; color: #999; }\n"
            "        .evidence-badge { display: inline-block; background: #d4edda; color: #155724; padding: 1px 6px; border-radius: 10px; font-size: 10px; margin-left: 4px; }\n"
            "        @media (max-width: 768px) {\n"
            "            .section-header { flex-direction: column; align-items: flex-start; gap: 8px; }\n"
            "        }\n"
            "    </style>\n"
            "</head>\n"
            "<body>\n"
            "    <div class=\"container\">\n"
            "        <header>\n"
            f"            <h1>Script Editor</h1>\n"
            f"            <div class=\"meta\">Job: {data['job_id']}</div>\n"
            "        </header>\n"
            "\n"
            "        <div class=\"stats\">\n"
            f"            <div class=\"stat\"><div class=\"value\">{data['total_sections']}</div><div class=\"label\">Sections</div></div>\n"
            f"            <div class=\"stat\"><div class=\"value\">{data['total_paragraphs']}</div><div class=\"label\">Paragraphs</div></div>\n"
            f"            <div class=\"stat\"><div class=\"value\">{data['total_words']}</div><div class=\"label\">Words</div></div>\n"
            f"            <div class=\"stat\"><div class=\"value\">{data['word_count']}</div><div class=\"label\">Target</div></div>\n"
            "        </div>\n"
            "\n"
            "        <div class=\"toolbar\">\n"
            "            <button class=\"btn btn-success\" onclick=\"saveScript()\">Save Changes</button>\n"
            "            <button class=\"btn btn-secondary\" onclick=\"exportScript()\">Export JSON</button>\n"
            "            <button class=\"btn-secondary\" onclick=\"exportText()\">Export Text</button>\n"
            "        </div>\n"
            "\n"
            "        <div class=\"script-editor\" id=\"scriptEditor\">\n"
            f"            {script_html}\n"
            "        </div>\n"
            "    </div>\n"
            "\n"
            "    <script>\n"
            f"        const data = {json_data};\n"
            "        let hasChanges = false;\n"
            "\n"
            "        function saveScript() {\n"
            "            // Collect all changes\n"
            "            const updatedData = {...data};\n"
            "            updatedData.sections = data.sections.map(section => ({\n"
            "                ...section,\n"
            "                paragraphs: section.paragraphs.map(para => {\n"
            "                    const textEl = document.querySelector(`[data-para-id=\"${para.id}\"] .paragraph-text`);\n"
            "                    return {\n"
            "                        ...para,\n"
            "                        text: textEl?.dataset.text || para.text,\n"
            "                    };\n"
            "                })\n"
            "            }));\n"
            "\n"
            "            // Save to localStorage for now (in real app, would POST to server)\n"
            "            localStorage.setItem('script_' + data.job_id, JSON.stringify(updatedData));\n"
            "            alert('Script saved to localStorage. In production, this would POST to the server.');\n"
            "            hasChanges = false;\n"
            "        }\n"
            "\n"
            "        function exportScript() {\n"
            "            const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});\n"
            "            const url = URL.createObjectURL(blob);\n"
            "            const a = document.createElement('a');\n"
            "            a.href = url;\n"
            "            a.download = 'review-script.json';\n"
            "            a.click();\n"
            "            URL.revokeObjectURL(url);\n"
            "        }\n"
            "\n"
            "        function exportText() {\n"
            "            let text = '';\n"
            "            data.sections.forEach(section => {\n"
            "                text += `=== ${section.type.toUpperCase()} (${section.target_seconds}s) ===` + '\\n';\n"
            "                text += `${section.purpose}` + '\\n\\n';\n"
            "                section.paragraphs.forEach(para => {\n"
            "                    text += para.text + '\\n\\n';\n"
            "                });\n"
            "            });\n"
            "            const blob = new Blob([text], {type: 'text/plain'});\n"
            "            const url = URL.createObjectURL(blob);\n"
            "            const a = document.createElement('a');\n"
            "            a.href = url;\n"
            "            a.download = 'review-script.txt';\n"
            "            a.click();\n"
            "            URL.revokeObjectURL(url);\n"
            "        }\n"
            "\n"
            "        // Warn on unsaved changes\n"
            "        window.addEventListener('beforeunload', (e) => {\n"
            "            if (hasChanges) {\n"
            "                e.preventDefault();\n"
            "                e.returnValue = '';\n"
            "            }\n"
            "        });\n"
            "\n"
            "        // Make paragraphs editable on double-click\n"
            "        document.addEventListener('dblclick', (e) => {\n"
            "            const textEl = e.target.closest('.paragraph-text');\n"
            "            if (textEl && !textEl.classList.contains('editing')) {\n"
            "                startEdit(textEl);\n"
            "            }\n"
            "        });\n"
            "\n"
            "        function startEdit(textEl) {\n"
            "            const originalText = textEl.dataset.text;\n"
            "            textEl.classList.add('editing');\n"
            "            textEl.contentEditable = true;\n"
            "            textEl.focus();\n"
            "\n"
            "            // Move cursor to end\n"
            "            const range = document.createRange();\n"
            "            range.selectNodeContents(textEl);\n"
            "            range.collapse(false);\n"
            "            const sel = window.getSelection();\n"
            "            sel.removeAllRanges();\n"
            "            sel.addRange(range);\n"
            "\n"
            "            textEl.addEventListener('blur', () => finishEdit(textEl, originalText), {once: true});\n"
            "            textEl.addEventListener('keydown', (e) => {\n"
            "                if (e.key === 'Enter' && !e.shiftKey) {\n"
            "                    e.preventDefault();\n"
            "                    textEl.blur();\n"
            "                }\n"
            "            }, {once: true});\n"
            "        }\n"
            "\n"
            "        function finishEdit(textEl, originalText) {\n"
            "            const newText = textEl.textContent;\n"
            "            if (newText !== originalText) {\n"
            "                textEl.dataset.text = newText;\n"
            "                hasChanges = true;\n"
            "            }\n"
            "            textEl.classList.remove('editing');\n"
            "            textEl.contentEditable = false;\n"
            "        }\n"
            "    </script>\n"
            "</body>\n"
            "</html>"
        )
    
    def _render_script_html(self, data: dict[str, Any]) -> str:
        """Render script sections as HTML (Python side)."""
        if not data.get("sections") or len(data["sections"]) == 0:
            return '<div class="empty-state">No script found for this job</div>'
        
        def escape_html(text: str) -> str:
            quot = "&" + "quot;"
            apos = "'"
            return (
                text
                .replace("&", "&")
                .replace("<", "<")
                .replace(">", ">")
                .replace('"', quot)
                .replace("'", apos)
            )
        
        sections_html = []
        for section in data["sections"]:
            paragraphs_html = []
            for para in section["paragraphs"]:
                claims_html = ""
                if para.get("claims"):
                    claims_list = []
                    for claim in para["claims"]:
                        claim_class = claim.get("type", "").lower()
                        badge = ' <span class="evidence-badge">\u2713</span>' if claim.get("evidence") else ""
                        claims_list.append(f'<span class="claim {claim_class}" data-claim-id="{claim.get("claim_id", "")}">{escape_html(claim.get("text", ""))}{badge}</span>')
                    claims_html = f'<div class="claims">{"".join(claims_list)}</div>'
                
                paragraphs_html.append(
                    '<div class="paragraph" data-para-id="' + para["id"] + '">\n'
                    '    <div class="paragraph-header">\n'
                    '        <span class="paragraph-id">' + para["id"] + '</span>\n'
                    '        <span>' + str(para.get("word_count", 0)) + ' words | ' + f'{para.get("target_seconds", 0):.1f}' + 's target</span>\n'
                    '    </div>\n'
                    '    <div class="paragraph-text" data-text="' + escape_html(para.get("text", "")) + '">' + escape_html(para.get("text", "")) + '</div>\n'
                    + claims_html + '\n'
                    '</div>\n'
                )
            
            sections_html.append(
                '<div class="section" data-section-id="' + section["id"] + '">\n'
                '    <div class="section-header">\n'
                '        <div class="section-info">\n'
                '            <span class="section-type">' + section["type"] + '</span>\n'
                '            <span class="section-purpose">' + escape_html(section.get("purpose", "")) + '</span>\n'
                '        </div>\n'
                '        <div class="section-stats">\n'
                '            <span>' + str(len(section["paragraphs"])) + ' paragraphs</span>\n'
                '            <span>' + str(section.get("target_seconds", 0)) + 's target</span>\n'
                '        </div>\n'
                '    </div>\n'
                '    <div class="section-body">\n'
                + "".join(paragraphs_html) + '\n'
                '    </div>\n'
                '</div>\n'
            )
        
        return "".join(sections_html)
    
    def _render_script(self, data: dict[str, Any]) -> str:
        """Deprecated: kept for compatibility. Use _render_script_html instead."""
        return self._render_script_html(data)
