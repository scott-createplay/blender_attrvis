import bpy

want = ("spiral", "radius", "volume", "distribute", "grid", "store",
        "curvetopoints", "meshtopoints", "vector")
names = sorted(bpy.types.Node.bl_rna_get_subclass_py(k).bl_idname
               for k in dir(bpy.types) if False)
# dump GeometryNode* matching keywords
found = []
for attr in dir(bpy.types):
    if not attr.startswith("GeometryNode") and not attr.startswith("FunctionNode"):
        continue
    low = attr.lower()
    if any(w in low for w in want):
        found.append(attr)
print("\n".join(found))

# inspect SetPointRadius / Store / MeshToPoints sockets
ng = bpy.data.node_groups.new("probe", "GeometryNodeTree")
for idn in (
    "GeometryNodeSetPointRadius",
    "GeometryNodeStoreNamedAttribute",
    "GeometryNodeMeshToPoints",
    "GeometryNodeCurveToPoints",
    "GeometryNodeMeshGrid",
    "GeometryNodeVolumeCube",
    "GeometryNodeDistributePointsInVolume",
    "GeometryNodeCurveSpiral",
    "GeometryNodeMeshIcoSphere",
    "GeometryNodeMeshUVSphere",
    "GeometryNodeMeshCube",
    "FunctionNodeRandomValue",
    "FunctionNodeInputVector",
):
    try:
        n = ng.nodes.new(idn)
        print(f"\n{idn}")
        print(f"  ins={[s.name+'/'+s.type for s in n.inputs]}")
        print(f"  outs={[s.name for s in n.outputs]}")
        for p in ("mode", "data_type", "operation"):
            if hasattr(n, p):
                print(f"  {p}={getattr(n, p)!r}")
    except Exception as e:
        print(f"\n{idn} FAIL {e}")

print("\n--- identifiers ---")
for idn, extra in (
    ("FunctionNodeRandomValue", {"data_type": "INT"}),
    ("FunctionNodeInputVector", {}),
    ("GeometryNodeDistributePointsInVolume", {}),
):
    n = ng.nodes.new(idn)
    for k, v in extra.items():
        setattr(n, k, v)
    print(idn, extra)
    for s in list(n.inputs) + list(n.outputs):
        print(f"  {s.name!r} id={s.identifier!r} type={s.type}")
    for p in n.bl_rna.properties:
        if p.identifier in ("vector", "mode"):
            print(f"  prop {p.identifier}")
