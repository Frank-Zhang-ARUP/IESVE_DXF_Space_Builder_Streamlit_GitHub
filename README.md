# DWG/DXF Space Boundary Builder for IESVE

Input: architectural **DWG or DXF**. Output: simplified **DXF** containing sealed room-boundary LWPOLYLINE entities and room-name TEXT.

## Pipeline
DWG -> temporary R2010 DXF -> geometry cleanup/polygonization -> IESVE DXF.
DXF -> geometry cleanup/polygonization -> IESVE DXF.

DWG is converted in a temporary workspace and is never overwritten. Temporary DWG/DXF files and decoder caches are removed after conversion.

## Streamlit deployment
Upload `app.py`, `requirements.txt`, and `.streamlit/config.toml` to GitHub. Deploy `app.py` on Streamlit Community Cloud.

## Cloud controls
- Recommended source file <= 50 MB.
- 300,000 expanded geometry-entity cap.
- No CAD document caching.
- No whole-drawing raster preview.
- Temporary conversion files deleted immediately.
- `ezdwg.clear_decode_caches()` is called after DWG conversion.

## Output
- `IES_SPACE_BOUNDARY`: closed LWPOLYLINE rooms.
- `IES_SPACE_NAME`: TEXT labels placed at interior representative points.
- Geometry QA covers invalid/open polygons and area overlaps.

Always review the generated drawing before IESVE import; architectural wall representations, unresolved Xrefs, proxy/custom objects, door openings and curtain walls can require manual correction.
