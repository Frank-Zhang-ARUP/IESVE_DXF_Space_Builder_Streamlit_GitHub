import gc, io, math, os, re, tempfile, pathlib
from collections import Counter
import streamlit as st
import ezdxf
try:
    import ezdwg
except ImportError:
    ezdwg = None
from ezdxf.disassemble import recursive_decompose
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, snap, unary_union
from shapely.strtree import STRtree

st.set_page_config(page_title="DXF Space Boundary Builder for IESVE", layout="wide")
st.title("DXF Space Boundary Builder for IESVE")
st.caption("Semi-automatic extraction of sealed, non-overlapping room polygons from architectural DXF linework.")

MAX_UPLOAD_MB = 50
MAX_PRIMITIVES = 300000


def tmp_read_dxf(raw):
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
            f.write(raw); path = f.name
        return ezdxf.readfile(path)
    finally:
        if path and os.path.exists(path):
            try: os.remove(path)
            except OSError: pass


def clean_text(s):
    s = "" if s is None else str(s)
    s = re.sub(r"\\P", " ", s)
    s = re.sub(r"\\[A-Za-z][^;]*;", "", s)
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "")).strip()


def entity_layer(e):
    try: return e.dxf.layer
    except Exception: return "0"


def iter_flat_entities(msp, expand_blocks):
    if expand_blocks:
        yield from recursive_decompose(msp)
    else:
        yield from msp


def arc_points(cx, cy, radius, a0, a1, chord):
    span = (a1-a0) % 360.0
    if span == 0: span = 360.0
    length = math.radians(span)*radius
    n = max(4, min(720, int(math.ceil(length/max(chord, 1e-6)))))
    return [(cx+radius*math.cos(math.radians(a0+span*i/n)),
             cy+radius*math.sin(math.radians(a0+span*i/n))) for i in range(n+1)]


def entity_to_lines(e, chord):
    t=e.dxftype(); out=[]
    try:
        if t == "LINE":
            a,b=e.dxf.start,e.dxf.end; out=[LineString([(a.x,a.y),(b.x,b.y)])]
        elif t == "LWPOLYLINE":
            pts=[(p[0],p[1]) for p in e.get_points("xy")]
            if e.closed and len(pts)>2: pts.append(pts[0])
            if len(pts)>1: out=[LineString(pts)]
        elif t == "POLYLINE" and not e.is_polygon_mesh and not e.is_poly_face_mesh:
            pts=[(v.dxf.location.x,v.dxf.location.y) for v in e.vertices]
            if e.is_closed and len(pts)>2: pts.append(pts[0])
            if len(pts)>1: out=[LineString(pts)]
        elif t == "ARC":
            c=e.dxf.center; out=[LineString(arc_points(c.x,c.y,e.dxf.radius,e.dxf.start_angle,e.dxf.end_angle,chord))]
        elif t == "CIRCLE":
            c=e.dxf.center; pts=arc_points(c.x,c.y,e.dxf.radius,0,360,chord); out=[LineString(pts)]
        elif t in ("SPLINE","ELLIPSE"):
            pts=[(p.x,p.y) for p in e.flattening(max(chord,1e-6))]
            if len(pts)>1: out=[LineString(pts)]
    except Exception:
        pass
    return [g for g in out if g.length>0 and len(g.coords)>1]


def scan(doc, expand_blocks, chord):
    msp=doc.modelspace(); layer_counts=Counter(); texts=[]; primitives=0
    # Text is intentionally taken from modelspace plus direct INSERT attributes.
    for e in msp:
        t=e.dxftype()
        if t in ("TEXT","MTEXT"):
            raw=e.dxf.text if t=="TEXT" else e.text; name=clean_text(raw)
            if name:
                p=e.dxf.insert; texts.append((name,Point(float(p.x),float(p.y)),entity_layer(e)))
        elif t=="INSERT":
            for a in e.attribs:
                name=clean_text(a.dxf.text)
                if name:
                    p=a.dxf.insert; texts.append((name,Point(float(p.x),float(p.y)),entity_layer(a)))
    for e in iter_flat_entities(msp, expand_blocks):
        if e.dxftype() in ("LINE","LWPOLYLINE","POLYLINE","ARC","CIRCLE","SPLINE","ELLIPSE"):
            layer_counts[entity_layer(e)] += 1; primitives += 1
            if primitives > MAX_PRIMITIVES: raise MemoryError(f"More than {MAX_PRIMITIVES:,} geometry entities after block expansion.")
    return layer_counts, texts


def build_lines(doc, layers, expand_blocks, chord):
    lines=[]
    for e in iter_flat_entities(doc.modelspace(), expand_blocks):
        if entity_layer(e) in layers:
            lines.extend(entity_to_lines(e,chord))
            if len(lines)>MAX_PRIMITIVES: raise MemoryError(f"More than {MAX_PRIMITIVES:,} converted line primitives.")
    return lines


def valid_room_name(s, excludes):
    x=s.strip().casefold()
    return bool(x) and not any(k.strip().casefold() in x for k in excludes if k.strip())


def make_output(selected, units, text_height, layer_poly, layer_text):
    out=ezdxf.new("R2013"); out.units=units
    out.layers.add(layer_poly, color=3); out.layers.add(layer_text, color=2)
    msp=out.modelspace()
    for name,poly in selected:
        coords=list(poly.exterior.coords)
        msp.add_lwpolyline(coords[:-1], close=True, dxfattribs={"layer":layer_poly})
        label_pt=poly.representative_point()
        msp.add_text(name, height=text_height, dxfattribs={"layer":layer_text}).set_placement((label_pt.x,label_pt.y))
    fd,path=tempfile.mkstemp(suffix=".dxf"); os.close(fd)
    try:
        out.saveas(path)
        with open(path,"rb") as f: return f.read()
    finally:
        try: os.remove(path)
        except OSError: pass

def load_cad_upload(uploaded):
    suffix = pathlib.Path(uploaded.name).suffix.lower()
    raw = uploaded.getvalue()
    if suffix == ".dxf":
        doc = tmp_read_dxf(raw)
        del raw; gc.collect()
        return doc
    if suffix != ".dwg":
        raise ValueError("Please upload a DWG or DXF file.")
    if ezdwg is None:
        raise RuntimeError("DWG support package ezdwg is not installed.")
    in_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".dwg", delete=False) as f:
            f.write(raw); in_path = f.name
        del raw; gc.collect()
        fd, out_path = tempfile.mkstemp(suffix=".dxf"); os.close(fd)
        # Convert uploaded DWG to a temporary R2010 DXF, then run the normal DXF pipeline.
        result = ezdwg.to_dxf(in_path, out_path, dxf_version="R2010", strict=False, include_unsupported=True)
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("DWG conversion produced no DXF output.")
        return ezdxf.readfile(out_path)
    finally:
        for path in (in_path, out_path):
            if path and os.path.exists(path):
                try: os.remove(path)
                except OSError: pass
        try:
            if ezdwg is not None: ezdwg.clear_decode_caches()
        except Exception:
            pass
        gc.collect()

uploaded=st.file_uploader(f"Architectural DWG / DXF (recommended <= {MAX_UPLOAD_MB} MB)",type=["dwg","dxf"])
if uploaded:
    if uploaded.size>MAX_UPLOAD_MB*1024*1024:
        st.error("DXF exceeds the cloud-safe upload limit."); st.stop()
    expand=st.checkbox("Expand block geometry",value=True,help="Required when walls are inside blocks/Xrefs already bound into the DXF. External Xrefs are not loaded.")
    chord=st.number_input("Curve approximation chord length (drawing units)",0.1,10000.0,100.0)
    try:
        doc=load_cad_upload(uploaded)
        counts,texts=scan(doc,expand,float(chord))
    except Exception as ex:
        st.error(f"CAD scan/conversion failed: {type(ex).__name__}: {ex}"); st.stop()

    c1,c2,c3=st.columns(3)
    c1.metric("Geometry layers",len(counts)); c2.metric("Room-label candidates",len(texts)); c3.metric("Geometry entities",sum(counts.values()))
    options=sorted(counts)
    boundary_layers=st.multiselect("Select layers containing space-closing wall/partition lines",options,
        format_func=lambda x:f"{x} ({counts[x]})")
    label_layers=st.multiselect("Select layers containing room names",sorted(set(t[2] for t in texts)),default=sorted(set(t[2] for t in texts)))

    st.subheader("Geometry repair and validation")
    a,b,c,d=st.columns(4)
    snap_tol=a.number_input("Snap tolerance",0.0,100000.0,20.0,help="Closes small endpoint-to-line or endpoint-to-endpoint gaps.")
    min_area=b.number_input("Minimum room area (drawing units²)",0.0,1e15,1000000.0)
    simplify=c.number_input("Simplify tolerance",0.0,100000.0,0.0,help="Use 0 for maximum fidelity.")
    text_height=d.number_input("Output text height",0.1,100000.0,250.0)
    excludes=st.text_input("Ignore labels containing these terms (comma-separated)","NOTE,DIM,LEVEL,GRID,DOOR,WINDOW")
    use_unique=st.checkbox("Require exactly one selected room label inside each output space",value=False)
    st.warning("This method extracts polygonized room faces containing room-name text. It does not infer missing external Xrefs or reliably derive wall centre-lines from every arbitrary double-line wall drawing. Review the QA table before IESVE import.")

    if st.button("BUILD SEALED SPACE DXF",type="primary",disabled=not boundary_layers):
        try:
            with st.spinner("Converting and noding selected linework..."):
                lines=build_lines(doc,set(boundary_layers),expand,float(chord))
                if not lines: raise ValueError("No supported linework found on selected layers.")
                merged=unary_union(lines)
                if snap_tol>0: merged=unary_union(snap(merged,merged,float(snap_tol)))
                faces=[p for p in polygonize(merged) if p.area>=float(min_area) and p.is_valid]
                if simplify>0:
                    faces=[p.simplify(float(simplify),preserve_topology=True) for p in faces]
                del lines,merged; gc.collect()

            labels=[t for t in texts if t[2] in set(label_layers) and valid_room_name(t[0],excludes.split(','))]
            tree=STRtree(faces) if faces else None
            assignments={i:[] for i in range(len(faces))}
            if tree:
                for name,pt,layer in labels:
                    for idx in tree.query(pt,predicate="covers"):
                        assignments[int(idx)].append(name)

            selected=[]; qa=[]
            for i,p in enumerate(faces):
                names=assignments[i]
                if not names: continue
                if use_unique and len(names)!=1:
                    qa.append({"Status":"EXCLUDED: multiple labels","Label count":len(names),"Names":" | ".join(names),"Area":round(p.area,2)})
                    continue
                name=names[0] if len(names)==1 else " / ".join(dict.fromkeys(names))
                selected.append((name,p))
                qa.append({"Status":"OK" if len(names)==1 else "CHECK: multiple labels","Label count":len(names),"Names":name,"Area":round(p.area,2)})

            # polygonize returns mutually exclusive faces; explicit overlap QA remains as a guard.
            overlap_count=0
            out_polys=[p for _,p in selected]
            out_tree=STRtree(out_polys) if out_polys else None
            if out_tree:
                for i,p in enumerate(out_polys):
                    for j in out_tree.query(p,predicate="intersects"):
                        j=int(j)
                        if j>i and p.intersection(out_polys[j]).area>1e-6: overlap_count+=1
            invalid=sum(not p.is_valid or not p.exterior.is_ring for p in out_polys)
            payload=make_output(selected,doc.units,float(text_height),"IES_SPACE_BOUNDARY","IES_SPACE_NAME")
            st.success(f"Generated {len(selected)} sealed spaces. Invalid/open polygons: {invalid}. Overlapping polygon pairs: {overlap_count}.")
            st.download_button("DOWNLOAD IESVE SPACE DXF",payload,re.sub(r"(?i)\.dxf$","",uploaded.name)+"_IESVE_Spaces.dxf","application/dxf")
            st.dataframe(qa,use_container_width=True)
            del payload,out_polys,faces; gc.collect()
        except Exception as ex:
            st.error(f"Processing failed: {type(ex).__name__}: {ex}")

with st.expander("Recommended first-run settings"):
    st.markdown("""
- Export/bind Xrefs in AutoCAD before upload; the cloud app cannot access external Xref files.
- Select only wall-face, partition and external-envelope layers. Exclude furniture, dimensions, hatches, grids and symbols.
- For drawings in millimetres, start with snap tolerance **10–30 mm**, minimum area **1,000,000 mm²**, curve chord **50–100 mm**, and text height **200–300 mm**.
- The output contains only closed `LWPOLYLINE` entities on `IES_SPACE_BOUNDARY` and room-name `TEXT` on `IES_SPACE_NAME`.
- Always inspect excluded rooms, multiple-label rooms, shafts, atria, curtain-wall edges and door openings before importing into IESVE.
""")
