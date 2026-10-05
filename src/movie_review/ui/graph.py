"""Story Graph Viewer (T092, optional Phase 11).

Interactive graph visualization showing character relationships, event chains,
and story arcs from the movie analysis. Can be embedded in the dashboard or
viewed standalone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from movie_review.artifacts import manager as artifacts
from movie_review.ui.safe_json import json_for_script


@dataclass(frozen=True)
class GraphNode:
    """Node in the story graph."""
    id: str
    label: str
    type: str  # character, event, location, scene
    group: str  # for coloring
    x: Optional[float] = None
    y: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class GraphEdge:
    """Edge in the story graph."""
    source: str
    target: str
    relation: str
    weight: float = 1.0
    metadata: Optional[dict[str, Any]] = None


class StoryGraph:
    """Generates graph visualization data from movie analysis."""
    
    def __init__(self, jobs_dir: str | Path, job_id: str):
        self.jobs_dir = Path(jobs_dir)
        self.job_id = job_id
    
    def load(self) -> dict[str, Any]:
        """Load all graph data from job artifacts."""
        analysis_path = self.jobs_dir / self.job_id / "movie-analysis.json"
        
        if not analysis_path.is_file():
            return self._build_from_artifacts()
        
        document = artifacts.read_json(analysis_path)
        return self._build_from_analysis(document)
    
    def _build_from_analysis(self, document: dict[str, Any]) -> dict[str, Any]:
        """Build graph from canonical movie-analysis.json."""
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        node_ids = set()
        
        # Character nodes
        for char in document.get("characters", []):
            node_id = f"char:{char.get('id', '')}"
            if node_id not in node_ids:
                nodes.append(GraphNode(
                    id=node_id,
                    label=char.get("name", "Unknown"),
                    type="character",
                    group="character",
                    metadata={
                        "first_seen": char.get("first_seen"),
                        "last_seen": char.get("last_seen"),
                        "confidence": char.get("confidence"),
                    }
                ))
                node_ids.add(node_id)
        
        # Event nodes
        for event in document.get("events", []):
            node_id = f"event:{event.get('id', '')}"
            if node_id not in node_ids:
                nodes.append(GraphNode(
                    id=node_id,
                    label=f"{event.get('type', 'Event')}: {event.get('description', '')[:40]}",
                    type="event",
                    group="event",
                    metadata={
                        "event_type": event.get("type"),
                        "timestamp": event.get("timestamp"),
                        "importance": event.get("importance"),
                        "location": event.get("location"),
                    }
                ))
                node_ids.add(node_id)
        
        # Location nodes
        for loc in document.get("locations", []):
            node_id = f"location:{loc.get('id', '')}"
            if node_id not in node_ids:
                nodes.append(GraphNode(
                    id=node_id,
                    label=loc.get("name", "Unknown"),
                    type="location",
                    group="location",
                    metadata={
                        "first_seen": loc.get("first_seen"),
                        "last_seen": loc.get("last_seen"),
                    }
                ))
                node_ids.add(node_id)
        
        # Scene nodes
        for scene in document.get("scenes", []):
            node_id = f"scene:{scene.get('scene_id', '')}"
            if node_id not in node_ids:
                location = scene.get("analysis", {}).get("location", "") if scene.get("analysis") else ""
                nodes.append(GraphNode(
                    id=node_id,
                    label=f"Scene {scene.get('scene_id', '')}",
                    type="scene",
                    group="scene",
                    metadata={
                        "start": scene.get("start"),
                        "end": scene.get("end"),
                        "duration": scene.get("duration"),
                        "location": location,
                    }
                ))
                node_ids.add(node_id)
        
        # Edges from relationships
        for rel in document.get("relationships", []):
            subj = f"char:{rel.get('subject', '')}"
            obj = f"char:{rel.get('object', '')}"
            if subj in node_ids and obj in node_ids:
                edges.append(GraphEdge(
                    source=subj,
                    target=obj,
                    relation=rel.get("relation", "RELATED"),
                    weight=rel.get("confidence", 0.5),
                    metadata={"evidence": rel.get("evidence", [])}
                ))
        
        # Edges from event participation
        for event in document.get("events", []):
            event_id = f"event:{event.get('id', '')}"
            if event_id not in node_ids:
                continue
            for char_id in event.get("characters", []):
                char_node = f"char:{char_id}"
                if char_node in node_ids:
                    edges.append(GraphEdge(
                        source=event_id,
                        target=char_node,
                        relation="PARTICIPATES_IN",
                        weight=1.0,
                    ))
            # Location edge
            loc = event.get("location")
            if loc:
                loc_node = f"location:{loc}"
                if loc_node in node_ids:
                    edges.append(GraphEdge(
                        source=event_id,
                        target=loc_node,
                        relation="OCCURS_AT",
                        weight=1.0,
                    ))
            # Scene edges - find scene containing event timestamp
            timestamp = event.get("timestamp", 0.0)
            for scene in document.get("scenes", []):
                if scene.get("start", 0) <= timestamp < scene.get("end", 0):
                    scene_node = f"scene:{scene.get('scene_id', '')}"
                    if scene_node in node_ids:
                        edges.append(GraphEdge(
                            source=event_id,
                            target=scene_node,
                            relation="OCCURS_IN",
                            weight=1.0,
                        ))
                    break
        
        # Edges from scene analysis
        for scene in document.get("scenes", []):
            scene_id = f"scene:{scene.get('scene_id', '')}"
            if scene_id not in node_ids:
                continue
            analysis = scene.get("analysis")
            if analysis:
                # Characters in scene
                for char_name in analysis.get("characters", []):
                    # Find character by name
                    for char in document.get("characters", []):
                        if char.get("name") == char_name or char_name in char.get("aliases", []):
                            char_node = f"char:{char.get('id', '')}"
                            if char_node in node_ids:
                                edges.append(GraphEdge(
                                    source=scene_id,
                                    target=char_node,
                                    relation="APPEARS_IN",
                                    weight=1.0,
                                ))
                            break
                # Location
                loc = analysis.get("location")
                if loc:
                    loc_node = f"location:{loc}"
                    if loc_node in node_ids:
                        edges.append(GraphEdge(
                            source=scene_id,
                            target=loc_node,
                            relation="SET_IN",
                            weight=1.0,
                        ))
        
        # Temporal edges between consecutive events
        events = sorted(document.get("events", []), key=lambda e: e.get("timestamp", 0.0))
        for i in range(len(events) - 1):
            e1 = f"event:{events[i].get('id', '')}"
            e2 = f"event:{events[i+1].get('id', '')}"
            if e1 in node_ids and e2 in node_ids:
                edges.append(GraphEdge(
                    source=e1,
                    target=e2,
                    relation="PRECEDES",
                    weight=0.8,
                ))
        
        # Story arc edges
        for arc in document.get("story_arcs", []):
            arc_events = arc.get("events", [])
            for i in range(len(arc_events) - 1):
                e1 = f"event:{arc_events[i]}"
                e2 = f"event:{arc_events[i+1]}"
                if e1 in node_ids and e2 in node_ids:
                    edges.append(GraphEdge(
                        source=e1,
                        target=e2,
                        relation="ARCS_TO",
                        weight=0.7,
                    ))
        
        # Convert to dicts
        nodes_data = [{"id": n.id, "label": n.label, "type": n.type, "group": n.group, "x": n.x, "y": n.y, "metadata": n.metadata} for n in nodes]
        edges_data = [{"source": e.source, "target": e.target, "relation": e.relation, "weight": e.weight, "metadata": e.metadata} for e in edges]
        
        return {
            "job_id": self.job_id,
            "movie_title": document.get("movie", {}).get("title", "Unknown"),
            "nodes": nodes_data,
            "edges": edges_data,
            "stats": {
                "total_nodes": len(nodes_data),
                "total_edges": len(edges_data),
                "characters": len([n for n in nodes_data if n["type"] == "character"]),
                "events": len([n for n in nodes_data if n["type"] == "event"]),
                "locations": len([n for n in nodes_data if n["type"] == "location"]),
                "scenes": len([n for n in nodes_data if n["type"] == "scene"]),
            }
        }
    
    def _build_from_artifacts(self) -> dict[str, Any]:
        """Fallback: build from individual artifact files."""
        # Simplified fallback - return empty graph
        return {
            "job_id": self.job_id,
            "nodes": [],
            "edges": [],
            "stats": {"total_nodes": 0, "total_edges": 0, "characters": 0, "events": 0, "locations": 0, "scenes": 0}
        }
    
    def to_json(self) -> str:
        """Export graph as JSON."""
        return json.dumps(self.load(), indent=2)
    
    def to_html(self) -> str:
        """Generate standalone HTML graph visualization."""
        data = self.load()
        return self._html_template(data)
    
    def _html_template(self, data: dict[str, Any]) -> str:
        """Generate HTML with interactive graph using vanilla JS (force-directed)."""
        json_data = json_for_script(data)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Story Graph - Job {data['job_id']}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fafafa; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        header {{ margin-bottom: 20px; }}
        h1 {{ color: #333; }}
        .meta {{ color: #666; margin-top: 8px; }}
        .controls {{ margin-bottom: 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
        .btn {{ padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }}
        .btn:hover {{ background: #0056b3; }}
        .btn-secondary {{ background: #6c757d; }}
        .btn-secondary:hover {{ background: #5a6268; }}
        .filter-group {{ display: flex; gap: 8px; align-items: center; }}
        .filter-group label {{ font-size: 13px; color: #666; }}
        .filter-group input[type="checkbox"] {{ margin-right: 4px; }}
        #graph {{ width: 100%; height: 700px; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); position: relative; }}
        .legend {{ display: flex; gap: 16px; margin: 16px 0; flex-wrap: wrap; }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 13px; }}
        .legend-color {{ width: 16px; height: 16px; border-radius: 50%; }}
        .tooltip {{ position: fixed; background: #333; color: white; padding: 12px; border-radius: 6px; font-size: 12px; pointer-events: none; z-index: 1000; max-width: 300px; display: none; }}
        .tooltip.show {{ display: block; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-bottom: 16px; }}
        .stat-card {{ background: white; padding: 12px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
        .stat-card .value {{ font-size: 24px; font-weight: bold; color: #333; }}
        .stat-card .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Story Graph</h1>
            <div class="meta">Job: {data['job_id']}</div>
        </header>
        
        <div class="stats">
            <div class="stat-card"><div class="value">{data['stats']['total_nodes']}</div><div class="label">Total Nodes</div></div>
            <div class="stat-card"><div class="value">{data['stats']['total_edges']}</div><div class="label">Total Edges</div></div>
            <div class="stat-card"><div class="value">{data['stats']['characters']}</div><div class="label">Characters</div></div>
            <div class="stat-card"><div class="value">{data['stats']['events']}</div><div class="label">Events</div></div>
            <div class="stat-card"><div class="value">{data['stats']['locations']}</div><div class="label">Locations</div></div>
            <div class="stat-card"><div class="value">{data['stats']['scenes']}</div><div class="label">Scenes</div></div>
        </div>
        
        <div class="controls">
            <button class="btn" id="resetBtn">Reset View</button>
            <button class="btn btn-secondary" id="centerBtn">Center</button>
            <button class="btn btn-secondary" id="exportBtn">Export JSON</button>
            
            <div class="filter-group">
                <span>Show:</span>
                <label><input type="checkbox" checked data-filter="character"> Characters</label>
                <label><input type="checkbox" checked data-filter="event"> Events</label>
                <label><input type="checkbox" checked data-filter="location"> Locations</label>
                <label><input type="checkbox" checked data-filter="scene"> Scenes</label>
            </div>
            
            <div class="filter-group" style="margin-left: auto;">
                <label>Charge: <input type="range" id="chargeInput" min="-500" max="-50" value="-200" style="width: 150px;"></label>
                <span id="chargeValue">-200</span>
            </div>
        </div>
        
        <div class="legend">
            <div class="legend-item"><div class="legend-color" style="background:#007bff"></div>Characters</div>
            <div class="legend-item"><div class="legend-color" style="background:#dc3545"></div>Events</div>
            <div class="legend-item"><div class="legend-color" style="background:#28a745"></div>Locations</div>
            <div class="legend-item"><div class="legend-color" style="background:#fd7e14"></div>Scenes</div>
        </div>
        
        <div id="graph"></div>
        <div class="tooltip" id="tooltip"></div>
    </div>
    
    <script>
        const data = {json_data};
        const nodes = data.nodes;
        const edges = data.edges;
        
        const width = document.getElementById('graph').clientWidth;
        const height = 700;
        
        const colorMap = {{
            character: '#007bff',
            event: '#dc3545',
            location: '#28a745',
            scene: '#fd7e14'
        }};
        
        const relationColors = {{
            PARTICIPATES_IN: '#007bff',
            OCCURS_AT: '#28a745',
            OCCURS_IN: '#fd7e14',
            PRECEDES: '#6c757d',
            ARCS_TO: '#6f42c1',
            APPEARS_IN: '#17a2b8',
            SET_IN: '#fd7e14',
            RELATED: '#6c757d',
            // Default relations
            BETRAYS: '#6f42c1',
            KILLS: '#dc3545',
            LOVES: '#e83e8c',
            KNOWS: '#17a2b8',
            SUSPECTS: '#ffc107',
            DISCOVERS: '#28a745',
            CAUSES: '#fd7e14',
            FORESHADOWS: '#6f42c1',
            REVEALS: '#e83e8c'
        }};
        
        const simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(edges).id(d => d.id).distance(100).strength(0.5))
            .force("charge", d3.forceManyBody().strength(-200))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(d => 20))
            .on("tick", ticked);
        
        const svg = d3.select("#graph")
            .append("svg")
            .attr("width", "100%")
            .attr("height", "100%")
            .call(d3.zoom().on("zoom", (event) => {{
                g.attr("transform", event.transform);
            }}));
        
        const g = svg.append("g");
        
        // Arrow markers
        svg.append("defs").selectAll("marker")
            .data(Object.keys(relationColors))
            .enter().append("marker")
            .attr("id", d => "arrow-" + d)
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 18)
            .attr("refY", 0)
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("d", "M0,-5L10,0L0,5")
            .attr("fill", d => relationColors[d]);
        
        const link = g.append("g")
            .attr("stroke", "#999")
            .attr("stroke-opacity", 0.6)
            .selectAll("line")
            .data(edges)
            .enter().append("line")
            .attr("stroke-width", d => Math.sqrt(d.weight) * 2)
            .attr("stroke", d => relationColors[d.relation] || '#999')
            .attr("marker-end", d => `url(#arrow-${{d.relation}})`);
        
        const node = g.append("g")
            .attr("stroke", "#fff")
            .attr("stroke-width", 1.5)
            .selectAll("circle")
            .data(nodes)
            .enter().append("circle")
            .attr("r", 12)
            .attr("fill", d => colorMap[d.group] || '#666')
            .attr("stroke", "#fff")
            .call(drag(simulation));
        
        const label = g.append("g")
            .selectAll("text")
            .data(nodes)
            .enter().append("text")
            .text(d => d.label)
            .attr("font-size", 10)
            .attr("dy", -16)
            .attr("text-anchor", "middle")
            .attr("pointer-events", "none")
            .attr("fill", "#333");
        
        const tooltip = d3.select("#tooltip");
        
        node.on("mouseover", (event, d) => {{
            tooltip.style("display", "block")
                .html(`<strong>${{d.label}}</strong><br>Type: ${{d.type}}<br>Group: ${{d.group}}${{d.metadata ? '<br>' + JSON.stringify(d.metadata, null, 2) : ''}}`)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 40) + "px")
                .classed("show", true);
        }})
        .on("mousemove", (event) => {{
            tooltip.style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 40) + "px");
        }})
        .on("mouseout", () => {{
            tooltip.classed("show", false);
        }});
        
        function ticked() {{
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);
            
            node
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);
            
            label
                .attr("x", d => d.x)
                .attr("y", d => d.y);
        }}
        
        function drag(simulation) {{
            function dragstarted(event, d) {{
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            }}
            
            function dragged(event, d) {{
                d.fx = event.x;
                d.fy = event.y;
            }}
            
            function dragended(event, d) {{
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            }}
            
            return d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended);
        }}
        
        // Controls
        document.getElementById('resetBtn').addEventListener('click', () => {{
            simulation.alpha(1).restart();
        }});
        
        document.getElementById('centerBtn').addEventListener('click', () => {{
            svg.transition().duration(750).call(
                d3.zoom().transform,
                d3.zoomIdentity.translate(width / 2, height / 2).scale(1)
            );
        }});
        
        document.getElementById('exportBtn').addEventListener('click', () => {{
            const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'story-graph.json';
            a.click();
            URL.revokeObjectURL(url);
        }});
        
        document.querySelectorAll('[data-filter]').forEach(cb => {{
            cb.addEventListener('change', () => {{
                const filter = cb.dataset.filter;
                const visible = cb.checked;
                node.filter(n => n.group === filter).style('display', visible ? null : 'none');
                label.filter(n => n.group === filter).style('display', visible ? null : 'none');
                link.filter(e => nodes.find(n => n.id === e.source).group === filter || nodes.find(n => n.id === e.target).group === filter)
                    .style('display', visible ? null : 'none');
            }});
        }});
        
        document.getElementById('chargeInput').addEventListener('input', (e) => {{
            const val = parseInt(e.target.value);
            document.getElementById('chargeValue').textContent = val;
            simulation.force('charge', d3.forceManyBody().strength(val));
            simulation.alpha(0.3).restart();
        }});
    </script>
    <script src="https://d3js.org/d3.v7.min.js"></script>
</body>
</html>"""