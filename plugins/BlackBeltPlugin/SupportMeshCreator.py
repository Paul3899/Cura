# Copyright (c) 2018 fieldOfView
# The Blackbelt plugin is released under the terms of the LGPLv3 or higher.

import numpy
import math
import trimesh

from UM.Extension import Extension
from UM.Application import Application
from UM.Logger import Logger

from UM.Mesh.MeshData import MeshData, calculateNormalsFromIndexedVertices
from UM.Math.Vector import Vector

from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")

class SupportMeshCreator():
    def createSupportMeshForNode(self, node):
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return None

        support_extruder_nr = global_container_stack.getExtruderPositionValueWithDefault("support_extruder_nr")
        support_angle_stack = Application.getInstance().getExtruderManager().getExtruderStack(support_extruder_nr)

        cos_support_angle = math.cos(math.radians(90 - support_angle_stack.getProperty("support_angle", "value")))
        down_vector = numpy.array([0,-1, 0])

        node_name = node.getName()
        mesh_data = node.getMeshData().getTransformed(node.getWorldTransformation())

        node_vertices = mesh_data.getVertices()
        node_indices = mesh_data.getIndices()
        if node_indices is None:
            # some file formats (eg 3mf) don't supply indices, but have unique vertices per face
            node_indices = numpy.arange(len(node_vertices)).reshape(-1, 3)

        tri_mesh = trimesh.base.Trimesh(vertices=node_vertices, faces=node_indices)
        tri_mesh.fix_normals()

        # get indices of faces that face down more than support_angle
        cos_angle_between_normal_down = numpy.dot(tri_mesh.face_normals, down_vector)
        faces_facing_down = numpy.argwhere(cos_angle_between_normal_down > cos_support_angle).flatten()
        if len(faces_facing_down) == 0:
            Logger.log("d", "Node %s doesn't need support" % node_name)
            return None
        roof_indices = node_indices[faces_facing_down]

        # filter out faces that are coplanar with the bottom
        non_bottom_indices = numpy.where(numpy.any(node_vertices[roof_indices].take(1, axis=2) > 0, axis=1))[0].flatten()
        roof_indices = roof_indices[non_bottom_indices]
        if len(roof_indices) == 0:
            Logger.log("d", "Node %s doesn't need support" % node_name)
            return None

        roof = trimesh.base.Trimesh(vertices=node_vertices, faces=roof_indices)
        roof.remove_unreferenced_vertices()
        roof.process()
        num_roof_vertices = len(roof.vertices)

        connecting_faces = []

        roof_outline = roof.outline()
        for entity in roof_outline.entities:
            entity_points = entity.points
            outline = roof_outline.vertices[entity_points]

            # numpy magic to find indices for each outline vertex
            outline_indices = numpy.where((roof.vertices==outline[:,None]).all(-1))[1]

            num_outline_vertices = len(outline)
            for i in range(0, num_outline_vertices - 1):
                connecting_faces.append([outline_indices[i], outline_indices[i + 1] + num_roof_vertices, outline_indices[i] + num_roof_vertices])
                connecting_faces.append([outline_indices[i], outline_indices[i + 1], outline_indices[i + 1] + num_roof_vertices])

        support_vertices = numpy.concatenate((roof.vertices, roof.vertices * [1,0,1]))
        support_faces = numpy.concatenate((roof.faces, roof.faces + len(roof.vertices), connecting_faces))

        support_mesh = trimesh.base.Trimesh(vertices=support_vertices, faces=support_faces)
        support_mesh.fix_normals()

        mesh_data = self._toMeshData(support_mesh)
        return mesh_data

    def _toMeshData(self, tri_node: trimesh.base.Trimesh) -> MeshData:
        tri_faces = tri_node.faces
        tri_vertices = tri_node.vertices

        indices = []
        vertices = []

        index_count = 0
        face_count = 0
        for tri_face in tri_faces:
            face = []
            for tri_index in tri_face:
                vertices.append(tri_vertices[tri_index])
                face.append(index_count)
                index_count += 1
            indices.append(face)
            face_count += 1

        vertices = numpy.asarray(vertices, dtype=numpy.float32)
        indices = numpy.asarray(indices, dtype=numpy.int32)
        normals = calculateNormalsFromIndexedVertices(vertices, indices, face_count)

        mesh_data = MeshData(vertices=vertices, indices=indices, normals=normals)
        return mesh_data