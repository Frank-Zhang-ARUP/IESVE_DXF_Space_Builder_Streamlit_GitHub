# DXF Space Boundary Builder for IESVE

A memory-conscious Streamlit app that converts selected architectural DXF linework into sealed, non-overlapping room polygons and places room-name text inside each polygon.

## GitHub / Streamlit deployment
Upload this repository to GitHub. In Streamlit Community Cloud, deploy `app.py` as the main file.

## Workflow
1. Bind/export external Xrefs in CAD.
2. Upload an ASCII DXF.
3. Select wall/partition/envelope layers and room-name layers.
4. Set gap snap tolerance and minimum room area.
5. Generate and download the simplified DXF.
6. Review the QA table and inspect the DXF before IESVE import.

## Geometry method
- Supports LINE, LWPOLYLINE, POLYLINE, ARC, CIRCLE, SPLINE and ELLIPSE.
- Optionally expands block geometry.
- Nodes and deduplicates linework with Shapely unary union.
- Snaps nearby endpoints/segments within the selected tolerance.
- Polygonizes the repaired network.
- Keeps only faces containing selected room-name TEXT/MTEXT/ATTRIB points.
- Writes each room as a closed LWPOLYLINE plus a room-name TEXT at a guaranteed interior representative point.
- Validates closure, polygon validity and area overlap.

## Important limitation
Architectural drawings vary substantially. Automatic wall-centreline extraction from arbitrary double-line walls, doors, curtain walls and unresolved Xrefs cannot be guaranteed. This tool is intentionally semi-automatic: layer selection, tolerance settings and CAD review are required.

## Cloud memory controls
- 50 MB recommended upload limit and 300,000 expanded geometry-entity cap.
- No DXF object caching.
- Temporary input/output files are deleted immediately.
- No full CAD image rendering.
- Line geometry is released before output serialization.
