import os
import enum
import struct
import math
from typing import List, Optional, Tuple


from ..fileutils import FileUtils
from ..bf2_common import Vec3, Mat4, load_n_elems, calc_bounds

class BF2MeshException(Exception):
    pass

# copy-pastes from D3DX9 SDK
class D3DDECLTYPE(enum.IntEnum):
    FLOAT1 = 0  # 1D float expanded to (value, 0., 0., 1.)
    FLOAT2 = 1  # 2D float expanded to (value, value, 0., 1.)
    FLOAT3 = 2  # 3D float expanded to (value, value, value, 1.)
    FLOAT4 = 3  # 4D float
    D3DCOLOR = 4  # 4D packed unsigned bytes mapped to 0. to 1. range
    UBYTE4 = 5
    SHORT2 = 6
    SHORT4 = 7
    UBYTE4N = 8
    SHORT2N = 9
    SHORT4N = 10
    USHORT2N = 11
    USHORT4N = 12
    UDEC3 = 13
    DEC3N = 14
    FLOAT16_2 = 15
    FLOAT16_4 = 16
    UNUSED = 17  # When the type field in a decl is unused.

    def get_struct_fmt(self):
        _TYPE_TO_FORMAT = {
            D3DDECLTYPE.FLOAT1: '1f',
            D3DDECLTYPE.FLOAT2: '2f',
            D3DDECLTYPE.FLOAT3: '3f',
            D3DDECLTYPE.FLOAT4: '4f',
            D3DDECLTYPE.D3DCOLOR: '4B',
            D3DDECLTYPE.UNUSED: '', # will evaluate to 0 using calcsize
        }

        return _TYPE_TO_FORMAT[self]


class D3DDECLUSAGE(enum.IntEnum):
    POSITION = 0
    BLENDWEIGHT = 1
    BLENDINDICES = 2
    NORMAL = 3
    PSIZE = 4
    TEXCOORD0 = 5
    TANGENT = 6
    BINORMAL = 7
    TESSFACTOR = 8
    POSITIONT = 9
    COLOR = 10
    FOG = 11
    DEPTH = 12
    SAMPLE = 13
    # BF2 custom enums
    TEXCOORD1 = 1 << 8 | 5
    TEXCOORD2 = 2 << 8 | 5
    TEXCOORD3 = 3 << 8 | 5
    TEXCOORD4 = 4 << 8 | 5


class D3DPRIMITIVETYPE(enum.IntEnum):
    POINTLIST = 1
    LINELIST = 2
    LINESTRIP = 3
    TRIANGLELIST = 4
    TRIANGLESTRIP = 5
    TRIANGLEFAN = 6


class Vertex:
    def __init__(self):
        self.position = None
        self.blendweight = None
        self.blendindices = None
        self.normal = None
        self.psize = None
        self.texcoord0 = None
        self.texcoord1 = None
        self.texcoord2 = None
        self.texcoord3 = None
        self.texcoord4 = None
        self.tangent = None
        self.binormal = None
        self.tessfactor = None
        self.positiont = None
        self.color = None
        self.fog = None
        self.depth = None
        self.sample = None


class Material:

    def __init__(self):
        self.fxfile : str = None
        self.technique : str = None

        self.maps : List[str] = [] # textures
        self.vertices : List[Vertex] = []
        self.faces : List[Tuple[int]] = []

        # temp import/export data
        self._vstart : int = None # vertex_buffer offset
        self._istart : int = None # index_buffer offset
        self._inum : int = None # number of indices
        self._vnum : int = None # number of vertices

        # unknowns
        self._u4 : int = None
        self._u5 : int = None

        # material bounds
        self._min : Vec3 = None
        self._max : Vec3 = None

    @classmethod
    def load(cls, f : FileUtils, **kwargs):
        obj = cls()
        obj.fxfile = f.read_string()
        obj.technique = f.read_string()

        obj.maps = [f.read_string() for _ in range(f.read_dword())]

        obj._vstart = f.read_dword()
        obj._istart = f.read_dword()
        obj._inum = f.read_dword()
        obj._vnum = f.read_dword()

        obj._u4 = f.read_dword() # XXX: only used for Staticmesh
        obj._u5 = f.read_dword()
        return obj

    def save(self, f : FileUtils):
        f.write_string(self.fxfile)
        f.write_string(self.technique)
        f.write_dword(len(self.maps))
        for map in self.maps:
            f.write_string(map)

        # assigned in save_vertices_faces
        f.write_dword(self._vstart)
        f.write_dword(self._istart)
        f.write_dword(self._inum)
        f.write_dword(self._vnum)

        f.write_dword(0) # wite zeros and hope it doesn't break anything
        f.write_dword(0)

    def load_vertices(self, vertex_decl_size, vertex_attributes, vertex_buffer):
        self.vertices = list()
        for i in range(self._vstart, self._vstart + self._vnum):
            vertex = Vertex()
            self.vertices.append(vertex)
            for vertex_attr in vertex_attributes:
                if vertex_attr._flag == VertexAttribute.UNUSED:
                    continue
                fmt = vertex_attr.decl_type.get_struct_fmt()
                size = struct.calcsize(fmt)
                vstart = i * vertex_decl_size + vertex_attr._offset
                data_packed = vertex_buffer[vstart:vstart+size]
                vertex_attr_value = struct.unpack(fmt, data_packed)
                setattr(vertex, vertex_attr.decl_usage.name.lower(), vertex_attr_value)

    def save_vertices(self, vertex_attributes, vertex_buffer, vstart):
        self._vstart = vstart
        self._vnum = len(self.vertices)
        for vertex in self.vertices:
            for vertex_attr in vertex_attributes:
                if vertex_attr._flag == VertexAttribute.UNUSED:
                    continue
                fmt = vertex_attr.decl_type.get_struct_fmt()
                vertex_attr_value = getattr(vertex, vertex_attr.decl_usage.name.lower())
                if vertex_attr_value is None:
                    raise BF2MeshException(f"Vertex missing '{vertex_attr.decl_usage.name}' attribute value")
                vertex_buffer += struct.pack(fmt, *vertex_attr_value)
        return self._vnum

    def load_faces(self, index_buffer):
        self.faces = list()
        for i in range(self._istart, self._istart + self._inum, 3):
            v1 = index_buffer[i + 0]
            v2 = index_buffer[i + 1]
            v3 = index_buffer[i + 2]
            self.faces.append((v1, v2, v3))

    def save_faces(self, index_buffer, istart):
        self._inum = len(self.faces) * 3
        self._istart = istart
        for face in self.faces:
            index_buffer.append(face[0])
            index_buffer.append(face[1])
            index_buffer.append(face[2])
        return self._inum

    def calc_bounds(self):
        if not self.vertices:
            raise ValueError("Cannot calculate bounds vertices is empty")
        verts = [vertex.position for vertex in self.vertices]
        self._min, self._max = calc_bounds(verts)
        return (self._min, self._max)

class Plane:
    def __init__(self, point, normal) -> None:
        self.point = point
        self.normal = normal

class MaterialWithTransparency(Material):

    ALPHA_BLEND_FACE_SET_COUNT = 8 # same as 3Ds max exporter

    class AlphaMode(enum.IntEnum):
        NONE = 0
        ALPHA_BLEND = 1
        ALPHA_TEST = 2

    def __init__(self) -> None:
        self.alpha_mode : Material.AlphaMode = None
        # extra sets of pre-sorted faces, only used for materials with alpha blend
        self.face_sets : Optional[List[List[int]]] = None

        # temp import/export data
        self._alpha_blend_indexnum = None
        super().__init__()

    @classmethod
    def load(cls, f : FileUtils, version, alpha_blend_indexnum):
        alpha_mode = cls.AlphaMode(f.read_dword())
        obj : MaterialWithTransparency = super(MaterialWithTransparency, cls).load(f, version=version)
        obj.alpha_mode = alpha_mode
        obj._alpha_blend_indexnum = alpha_blend_indexnum                
        return obj

    def load_faces(self, index_buffer):
        if self.alpha_mode == self.AlphaMode.ALPHA_BLEND:
            self.face_sets = list()
            for i in range(self._alpha_blend_indexnum):
                face_set = list()
                self.face_sets.append(face_set)
                istart = self._istart + i * self._inum
                for i in range(istart, istart + self._inum, 3):
                    v1 = index_buffer[i + 0]
                    v2 = index_buffer[i + 1]
                    v3 = index_buffer[i + 2]
                    face_set.append((v1, v2, v3))
            self.faces = self.face_sets[0]
        else:
            super().load_faces(index_buffer)

    def save_faces(self, index_buffer, istart):         
        if self.alpha_mode == self.AlphaMode.ALPHA_BLEND:
            return self._save_faces_alpha_blend(index_buffer, istart)
        else:
            return super().save_faces(index_buffer, istart)

    def save(self, f : FileUtils):
        f.write_dword(self.alpha_mode)
        super().save(f)

    def _get_sorting_planes(self):
        planes_count = self.ALPHA_BLEND_FACE_SET_COUNT
        self.calc_bounds()
        max_dist = Vec3.distance(Vec3(), self._max)
        min_dist = Vec3.distance(Vec3(), self._min)
        max_radius = max(max_dist, min_dist)

        sorting_planes = list()
        for i in range(planes_count):
            plane_rotation = 360.0 / (2 * planes_count) + i * (360.0 / planes_count)
            rot_m = Mat4.rotation(-math.radians(plane_rotation), 'Y')
            plane_normal = Vec3(0, 0, -1)
            plane_normal.rotate(rot_m)
            plane_point = plane_normal.copy().scale(max_radius)
            sorting_planes.append(Plane(plane_point, plane_normal))
        return sorting_planes

    def _save_faces_alpha_blend(self, index_buffer, istart):
        sorting_planes = self._get_sorting_planes()
        self._inum = len(self.faces) * 3
        self._istart = istart

        face_mid_points = list()
        for face in self.faces:
            face_center = Vec3()
            for v in face:
                face_center.add(Vec3(*self.vertices[v].position))
            face_center.scale(1.0 / 3)
            face_mid_points.append(face_center)

        for plane in sorting_planes:
            face_dist_to_plane = list()
            for face, face_center in zip(self.faces, face_mid_points):
                delta = face_center.copy().sub(plane.point)
                dist = abs(delta.dot_product(plane.normal))
                face_dist_to_plane.append(dist)

            for _, face in sorted(zip(face_dist_to_plane, self.faces)):
                index_buffer.append(face[0])
                index_buffer.append(face[1])
                index_buffer.append(face[2])
        return self._inum * len(sorting_planes)

class Lod:
    _MATERIAL_TYPE = Material

    def __init__(self):
        # boundaries
        self._min = None
        self._max = None

        self.materials : List[Material] = []
    
    @classmethod
    def load(cls, f : FileUtils):
        return cls()
    
    def save(self, f : FileUtils):
        pass # nothing to do

    def load_parts_rigs(self, f : FileUtils, version):
        self._min = Vec3.load(f)
        self._max = Vec3.load(f)
        if version <= 6: # some old meshes, version 4, 6
            Vec3.load(f)

    def save_parts_rigs(self, f : FileUtils):
        inf = float("inf")
        self._min = Vec3(inf, inf, inf)
        self._max = Vec3(0.0, 0.0, 0.0)
        for mat in self.materials:
            mat_min, mat_max = mat.calc_bounds()
            for i in range(3):
                if mat_min[i] < self._min[i]:
                    self._min[i] = mat_min[i]
                if mat_max[i] > self._max[i]:
                    self._max[i] = mat_max[i]
        self._min.save(f)
        self._max.save(f)

    def load_materials(self, f : FileUtils, **kwargs):
        self.materials = load_n_elems(f, self._MATERIAL_TYPE, count=f.read_dword(), **kwargs)

    def save_materials(self, f : FileUtils):
        f.write_dword(len(self.materials))
        for mat in self.materials:
            mat.save(f)

    def new_material(self):
        self.materials.append(self._MATERIAL_TYPE())
        return self.materials[-1]

class Geom:
    _LOD_TYPE = Lod

    def __init__(self):
        self.lods : List[Lod] = []

    @classmethod
    def load(cls, f : FileUtils):
        obj = cls()
        obj.lods = load_n_elems(f, cls._LOD_TYPE, count=f.read_dword())
        return obj
    
    def save(self, f : FileUtils):
        f.write_dword(len(self.lods))
        for lod in self.lods:
            lod.save(f)

    def new_lod(self):
        self.lods.append(self._LOD_TYPE())
        return self.lods[-1]


class VertexAttribute:
    USED = 0
    UNUSED = 255

    def __init__(self, decl_type : D3DDECLTYPE, decl_usage : D3DDECLUSAGE):
        self._flag = None # USED\UNUSED
        self._offset = None # byte offset from vertex_buffer start
        self.decl_type : D3DDECLTYPE = decl_type
        self.decl_usage : D3DDECLUSAGE = decl_usage

    @classmethod
    def load(cls, f : FileUtils):
        _flag = f.read_word()
        _offset = f.read_word()
        decl_type = D3DDECLTYPE(f.read_word())
        decl_usage = D3DDECLUSAGE(f.read_word())

        obj = cls(decl_type, decl_usage)
        obj._flag = _flag
        obj._offset = _offset
        return obj

    def save(self, f : FileUtils):
        f.write_word(self._flag)
        f.write_word(self._offset)
        f.write_word(self.decl_type)
        f.write_word(self.decl_usage)

class MeshHeader:
    @staticmethod
    def load(f : FileUtils):
        f.read_dword()
        version = f.read_dword()
        # those below seem to be reserved for future use
        # BF2 just reads them and doesn't save the values anywhere
        f.read_dword()
        f.read_dword()
        f.read_dword()
        f.read_byte() # seems to be version flag for bfp4f
        return version

    @staticmethod
    def save(f : FileUtils, version):
        f.write_dword(0)
        f.write_dword(version)
        f.write_dword(0)
        f.write_dword(0)
        f.write_dword(0)
        f.write_byte(0)


class BF2VisibleMesh():
    _VERSION = None
    _GEOM_TYPE = Geom
    _FILE_EXT = ''

    def __init__(self, file='', name=''):
        self.geoms : List[Geom] = []
        self.vertex_attributes : List[VertexAttribute] = []

        if name:
            self.name = name
        elif file:
            self.name = os.path.splitext(os.path.basename(file))[0]
        else:
            raise BF2MeshException("file or name required")

        if not file:
            return

        with open(file, mode='rb') as fo:
            f = FileUtils(fo)
            self.load(f)

            if os.fstat(fo.fileno()).st_size != fo.tell():
                raise BF2MeshException(f"Corrupted {self._FILE_EXT} file? Reading finished and file pointer != filesize")


    def load(self, f : FileUtils):
        version = MeshHeader.load(f)

        self.geoms = load_n_elems(f, self._GEOM_TYPE, count=f.read_dword())
        self.vertex_attributes = load_n_elems(f, VertexAttribute, count=f.read_dword())

        if self.vertex_attributes[-1]._flag == VertexAttribute.UNUSED:
            # skip unused, dunno what is the purpouse of this
            self.vertex_attributes.pop()

        primitive_type = D3DPRIMITIVETYPE(f.read_dword())

        if primitive_type != D3DPRIMITIVETYPE.TRIANGLELIST:
            # seems to be always D3DPT_TRIANGLELIST but DICE's code also handles D3DPT_TRIANGLESTRIP
            raise BF2MeshException(f"Unsupported primitive type: {D3DPRIMITIVETYPE(primitive_type).name}")

        vertex_decl_size = f.read_dword() # byte size of Vertex declaration

        vertex_buffer : bytes = f.read_raw(vertex_decl_size * f.read_dword())
        index_buffer : List[int] = f.read_word(count=f.read_dword())

        alpha_blend_indexnum = None
        if issubclass(self._GEOM_TYPE._LOD_TYPE._MATERIAL_TYPE, MaterialWithTransparency):
            alpha_blend_indexnum = f.read_dword()

        for geom in self.geoms:
            for lod in geom.lods:
                lod.load_parts_rigs(f, version=version)

        for geom in self.geoms:
            for lod in geom.lods:
                lod.load_materials(f, version=version, alpha_blend_indexnum=alpha_blend_indexnum)
                for mat in lod.materials:
                    mat.load_vertices(vertex_decl_size, self.vertex_attributes, vertex_buffer)
                    mat.load_faces(index_buffer)

    def export(self, export_path):
        with open(export_path, "wb") as file:
            f = FileUtils(file)
            MeshHeader.save(f, self._VERSION)
            f.write_dword(len(self.geoms))
            for geom in self.geoms:
                geom.save(f)
   
            f.write_dword(len(self.vertex_attributes) + 1) # +1 for unused

            vertex_decl_size = 0
            for vertex_attr in self.vertex_attributes:
                if vertex_attr._flag == VertexAttribute.UNUSED:
                    continue
                vertex_attr._offset = vertex_decl_size
                vertex_attr._flag = VertexAttribute.USED
                vertex_attr.save(f)
                fmt = vertex_attr.decl_type.get_struct_fmt()
                vertex_decl_size += struct.calcsize(fmt)

            # add last dummy attribute that always is set to unused for _reasons_
            unused_attr = VertexAttribute(D3DDECLTYPE.UNUSED, 0)
            unused_attr._offset = 0
            unused_attr._flag = VertexAttribute.UNUSED
            unused_attr.save(f)

            f.write_dword(D3DPRIMITIVETYPE.TRIANGLELIST)
            f.write_dword(vertex_decl_size)

            vertex_buffer : bytearray = bytearray()
            index_buffer : List[int] = list()

            has_alpha_blend_material = False

            vstart = 0
            istart = 0
            for geom in self.geoms:
                for lod in geom.lods:
                    for mat in lod.materials:
                        if isinstance(mat, MaterialWithTransparency):
                            is_alpha_blend = mat.alpha_mode == MaterialWithTransparency.AlphaMode.ALPHA_BLEND
                            has_alpha_blend_material |= is_alpha_blend
                        vstart += mat.save_vertices(self.vertex_attributes, vertex_buffer, vstart)
                        istart += mat.save_faces(index_buffer, istart)

            f.write_dword(int(len(vertex_buffer) / vertex_decl_size))
            f.write_raw(bytes(vertex_buffer))
            f.write_dword(len(index_buffer))
            f.write_word(index_buffer)

            if issubclass(self._GEOM_TYPE._LOD_TYPE._MATERIAL_TYPE, MaterialWithTransparency):
                if has_alpha_blend_material:
                    f.write_dword(MaterialWithTransparency.ALPHA_BLEND_FACE_SET_COUNT)
                else:
                    f.write_dword(0)

            for geom in self.geoms:
                for lod in geom.lods:
                    lod.save_parts_rigs(f)
            
            for geom in self.geoms:
                for lod in geom.lods:
                    lod.save_materials(f)

    def add_vert_attr(self, decl_type, decl_usage):
        vert_attr = VertexAttribute(D3DDECLTYPE[decl_type], D3DDECLUSAGE[decl_usage])
        self.vertex_attributes.append(vert_attr)

    def _has_vert_attr(self, decl_usage):
        for vert_attr in self.vertex_attributes:
            if vert_attr.decl_usage == decl_usage:
                return True
        return False

    def has_normal(self):
        return self._has_vert_attr(D3DDECLUSAGE.NORMAL)

    def has_uv(self, uv_channel):
        attr = D3DDECLUSAGE(uv_channel << 8 | 5)
        return self._has_vert_attr(attr)
    
    def has_blend_indices(self):
        return self._has_vert_attr(D3DDECLUSAGE.BLENDINDICES)

    def has_blend_weight(self):
        return self._has_vert_attr(D3DDECLUSAGE.BLENDWEIGHT)

    def new_geom(self):
        self.geoms.append(self._GEOM_TYPE())
        return self.geoms[-1]
