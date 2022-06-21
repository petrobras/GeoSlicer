"""
Created on Mon Oct  3 21:29:25 2022

@author: Ronaldo Herlinger Jr.

This file has been modified to better integrate with
GeoSlicer. The original version can be found at: 
https://pypi.org/project/pspsmgen/
"""

import numpy as np
import math
import scipy.ndimage
from ltrace.slicer.cli_utils import progressUpdate

# import from_euler
from scipy.spatial.transform import Rotation as R
import cv2


SPHERE_ARRANGEMENTS = "Touching", "Untouching", "Tangential", "Orthorhombic"
CUBE_ARRANGEMENTS = "Touching", "Untouching"
CUBE_MODES = "Random", "Regular", "Biased"


class Psgen:
    class Spheres:

        """
        Sphere class has functions to build sphere models to reproduce
        microfabrics of Pre-Salt rocks composed of spherulites or particles
        and other components. It has functions to place random touching and
        untouching spheres in 3d array models. It can populate spheres on
        previously shrubstones models or empty arrays. There are also
        functions to place spheres tangentially to reproduce intraclastic
        rudstones and grainstones.

        """

        def __init__(
            self,
            side,
            n_spheres,
            radius,
            radius_std,
            phi,
            phase_number=2,
            shrub_number=3,
            compaction=False,
            comp_ratio=1.1,
        ):
            """
            :side: maximum grid value.
            :n_spheres: initial number of spheres.
            :radius: sphere mean radius.
            :radius_std: sphere std radi.
            :phi: minimum porosity.
            :phase_number: the sphere voxels will receive the number 2 by
            default.
            :compaction: if true, spheres will be dilated to simulate pressure
            solution.
            :comp_ratio: the ratio of compaction
            """

            self.phase_number = phase_number
            self.side = side
            self.n_spheres = n_spheres
            self.radius = radius
            self.radius_std = radius_std
            self.phi = phi
            self.shrub_number = shrub_number
            self.compaction = compaction
            self.comp_ratio = comp_ratio

        def sphere_generator(self):
            """
            Generates a sphere within limits with aleatory
            coordinate and radius.

            :plim_x,lim_y,lim_z: max coordinates.
            :return: coordinates(x,y, and z) and radius.
            """

            x = np.random.randint(0, self.side)
            y = np.random.randint(0, self.side)
            z = np.random.randint(0, self.side)
            radius = max(int(np.random.normal(self.radius, self.radius_std)), 1)

            return [x, y, z, radius]

        def sphere_generator_tang(self, x, y, z, radius1):
            """
            Generates a sphere within limits with aleatory
            coordinate and radius. The spheres can touch tangentially
            to reproduce reworked particles. The function receives a
            sphere and returns an tangential sphere.

            :x, y, z: input sphere center coordinates.
            :radius1: input sphere radius.
            :return: coordinates(x,y, and z) and radius of a tangential
            sphere.
            """

            radius2 = max(int(np.random.normal(self.radius, self.radius_std)), 1)
            dist = radius1 + radius2
            n = 0
            tol = 1000

            tetha = np.random.randint(-360, 360)
            omega = np.random.randint(-360, 360)
            x2 = int(x + dist * math.cos(math.radians(tetha)) * math.sin(math.radians(omega)))
            y2 = int(y + dist * math.sin(math.radians(tetha)) * math.sin(math.radians(omega)))
            z2 = int(z + dist * math.cos(math.radians(omega)))

            # This looping was implemented to avoid the spheres
            # be placed outside the array.
            while (
                x2 not in range(-radius2, self.side + radius2)
                or y2 not in range(-radius2, self.side + radius2)
                or z2 not in range(-radius2, self.side + radius2)
            ):
                tetha = np.random.randint(-360, 360)
                omega = np.random.randint(-360, 360)
                x2 = int(x + dist * math.cos(math.radians(tetha)) * math.sin(math.radians(omega)))
                y2 = int(y + dist * math.sin(math.radians(tetha)) * math.sin(math.radians(omega)))
                z2 = int(z + dist * math.cos(math.radians(omega)))
                n += 1
                if n == tol:
                    break

            return [x2, y2, z2, radius2]

        def dist_test(self, x1, y1, z1, x2, y2, z2, radius1, radius2):
            """

            Measures distance between two spheres returning
            if they are touching each other.

            :x1,y1,z1: coordinates of first spheres.
            :x2,y2,z2: coordinates of second spheres.
            :radius1,radius2: radius of two spheres.
            :return: True for not touching.
            """

            dist = np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)
            return dist < radius1 + radius2

        def sphere_list(self):
            """

            Generates sphere list containing center coordinates and radius.
            The spheres do not occupy the same space.

            :try_number: number of attempts of sphere placement.
            :return: Sphere List.
            """
            Spheres = []
            sphere = self.sphere_generator()
            Spheres.append(sphere)
            yield sphere

            for n in range(self.n_spheres):
                sphere = self.sphere_generator()
                if sphere[1] < 0 or sphere[2] < 0 or sphere[3] < 0:
                    continue

                touching = False
                for Sphere in Spheres:
                    touching = self.dist_test(
                        Sphere[0], Sphere[1], Sphere[2], sphere[0], sphere[1], sphere[2], Sphere[3], sphere[3]
                    )
                    if touching:
                        break

                if not touching:
                    Spheres.append(sphere)
                    yield sphere

        def sphere_list_tang(self, array):
            """

            Generates sphere list containing center coordinates and radius.
            The spheres do not occupy the same space. All spheres tangent
            at least one sphere.

            :return: Sphere List.
            """

            Spheres = []

            random_position = [np.random.randint(0, self.side) for _ in range(3)]
            sphere = random_position + [self.radius]
            Spheres.append(sphere)
            yield sphere

            search_n = 1

            for n in range(self.n_spheres):
                # Prefer newer spheres as they often have more space to grow
                sphere_rand = Spheres[-search_n]
                sphere = self.sphere_generator_tang(sphere_rand[0], sphere_rand[1], sphere_rand[2], sphere_rand[3])

                is_empty_heuristic = False
                sphere_bounds = array[
                    sphere[0] - sphere[3] : sphere[0] + sphere[3],
                    sphere[1] - sphere[3] : sphere[1] + sphere[3],
                    sphere[2] - sphere[3] : sphere[2] + sphere[3],
                ]
                if sphere_bounds.shape == (2 * sphere[3],) * 3:
                    is_empty_heuristic = np.all(sphere_bounds != self.phase_number)

                touching = False
                if not is_empty_heuristic:
                    for Sphere in Spheres:
                        touching = self.dist_test(
                            Sphere[0], Sphere[1], Sphere[2], sphere[0], sphere[1], sphere[2], Sphere[3], sphere[3]
                        )
                        if touching:
                            tries = 10 if search_n < 20 else 1
                            if n % tries == 0:
                                search_n += 1
                                if search_n > len(Spheres):
                                    search_n = 1
                            break
                if not touching:
                    search_n = 1
                    Spheres.append(sphere)
                    yield sphere

        def sphere_list_touching(self):
            """

            Generates a list of coordinates and radius of touching spheres.

            :try_number: number of attempts of sphere placement.
            :radius: mean sphere radius.
            :radius_std: sphere std radius.
            :side: maximum grid value.
            :return: sphere List.
            """

            Esferas = []

            for n in range(self.n_spheres):
                Esferas.append(self.sphere_generator())

            return Esferas

        def rhomb_sphere_pack(self):
            """

            This function generates an orthorhombic sphere packing.


            :return: sphere packing array.
            """

            coords = []
            coord_x = 0
            coord_y = 0
            coord_z = 0

            for x in range(int((self.side + self.radius * 2) / (self.radius * 2))):
                coord_y = 0
                for y in range(int((self.side + self.radius * 2) / (self.radius * 2))):
                    coords.append([coord_x, coord_y, coord_z, self.radius])
                    coord_z = 0
                    for z in range(int((self.side + self.radius * 2) / (self.radius * 2))):
                        coords.append([coord_x, coord_y, coord_z, self.radius])
                        coord_z = coord_z + self.radius * 2
                    coord_y = coord_y + self.radius * 2
                coords.append([coord_x, coord_y, coord_z, self.radius])
                coord_x = coord_x + self.radius * np.sqrt(3) * 1.63

            coord_x = self.radius * np.sqrt(3) / 2 * 1.63
            coord_y = self.radius
            coord_z = self.radius

            for x in range(int((self.side + self.radius * 2) / (self.radius * 2))):
                coord_y = self.radius
                for y in range(int((self.side + self.radius * 2) / (self.radius * 2))):
                    coords.append([coord_x, coord_y, coord_z, self.radius])
                    coord_z = self.radius
                    for z in range(int((self.side + self.radius * 2) / (self.radius * 2))):
                        coords.append([coord_x, coord_y, coord_z, self.radius])
                        coord_z = coord_z + self.radius * 2
                    coord_y = coord_y + self.radius * 2
                coords.append([coord_x, coord_y, coord_z, self.radius])
                coord_x = coord_x + self.radius * np.sqrt(3) * 1.63

            return coords

        def sphere_array(self, Sphere_List, array, avoid_shrubs, silent=False):
            """

            Generates an array with a sphere list. An array must be provided:
            it can be a zero array or an array with spheres.

            :Sphere_List: list of spheres containing coordinates and radius.
            :side: array limits.
            :phi: desirable porosity.
            :array: zeros or previous array.
            :silent: no prints.
            :return: final array.
            """

            if not self.compaction:
                self.comp_ratio = 1

            target_n_voxels = self.side**3 * (1 - self.phi)
            n_voxels = 0
            progress_voxels = 0
            progress_spheres = 0
            progress = 0
            for i, center in enumerate(Sphere_List):
                radius = int(center[3] * self.comp_ratio)
                center = np.array(center[:3], dtype=int)
                min_bound = np.clip(center - radius, 0, self.side)
                max_bound = np.clip(center + radius, 0, self.side)

                x, y, z = np.meshgrid(
                    np.arange(min_bound[0], max_bound[0]),
                    np.arange(min_bound[1], max_bound[1]),
                    np.arange(min_bound[2], max_bound[2]),
                    indexing="ij",
                )

                array_crop = array[
                    min_bound[0] : max_bound[0], min_bound[1] : max_bound[1], min_bound[2] : max_bound[2]
                ]
                list_coord = np.stack([x, y, z], axis=-1)
                dist = np.linalg.norm(list_coord - center, axis=-1)
                mask = dist <= radius
                if avoid_shrubs and np.any(mask & (array_crop == self.shrub_number)):
                    continue

                n_voxels += (mask & (array_crop != self.phase_number)).sum()
                array_crop[mask] = self.phase_number

                progress_voxels = n_voxels / target_n_voxels
                progress_spheres = i / self.n_spheres
                progress = max(progress_voxels, progress_spheres)
                if progress_voxels >= 1:
                    break
                if i % 10 == 0:
                    progressUpdate(progress)

            if not silent:
                print("")
                if progress_voxels < 1:
                    print("Porosity reached", 1 - (n_voxels / self.side**3))
                    print(
                        "If you desire to reach "
                        + str(self.phi)
                        + """, please increase the tries number 
                          on sphere_list function parameter."""
                    )
                else:
                    print("Done!")
                print(" ")

            return array

    class Cubes:
        """

        This class has several functions to place cubes in a 3d array model. The
        cubes represents diverse ways of dolomite replacement or cimentation.
        """

        def __init__(
            self, side, side_cube, side_cube_std, phi, phase_number=1, cal_tou=True, sphere_number=2, shrub_number=3
        ):
            """

            :side: maximum grid value.
            :side_cube: single cube side.
            :side_cube_std: single cube std side.
            :phi: minimum porosity.
            :phase_number: the cube voxels will receive the number 1 by default.
            :cal_tou: this parameter sets if the spheres or shrubs provided by a
            previously populated array will be touched by cubes.
            :sphere number: in the case of a sphere populated array be used,
            the phase number of spheres should be informed.
            """
            self.phase_number = phase_number
            self.side = side
            self.side_cube = side_cube
            self.side_cube_std = side_cube_std
            self.phi = phi
            self.cal_tou = cal_tou
            self.sphere_number = sphere_number
            self.shrub_number = shrub_number

        def unit_vector(self, vector):
            """

            Returns the unit vector of the vector."""

            return vector / np.linalg.norm(vector)

        def angle_between(self, v1, v2):
            """

            Finds angle between two vectors."""

            v1_u = self.unit_vector(v1)
            v2_u = self.unit_vector(v2)

            return np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))

        def x_rotation(self, vector, theta):
            """

            Rotates 3-D vector around x-axis"""

            R = np.array([[1, 0, 0], [0, np.cos(theta), -np.sin(theta)], [0, np.sin(theta), np.cos(theta)]])

            return np.dot(R, vector)

        def y_rotation(self, vector, theta):
            """

            Rotates 3-D vector around y-axis"""

            R = np.array([[np.cos(theta), 0, np.sin(theta)], [0, 1, 0], [-np.sin(theta), 0, np.cos(theta)]])

            return np.dot(R, vector)

        def z_rotation(self, vector, theta):
            """

            Rotates 3-D vector around z-axis"""

            R = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])

            return np.dot(R, vector)

        def rotation_correction(self, array):
            """

            After rotation, cubes tend to develop some holes inside.
            This function fills the holes.

            :array: 3d array with cubes.
            :return: 3d array with corrected cubes.
            """
            return scipy.ndimage.binary_closing(array, iterations=1, border_value=0).astype(array.dtype)

        def cube_generator(self, rotation, max_rotation):
            """

            Generates a cube within provided array limits with aleatory
            coordinates and rotation.

            :rotation: sets if the cubes will rotate.
            :max_rotation: maximum rotation of cubes.
            :return: radius in which the cube is inscribed, center list
                    coordinate of the cube after random rotation, random
                    coordinate list before rotation, axis random rotation
                    angle list, and new random side length.
            """

            side_cube = max(int(np.random.normal(self.side_cube, self.side_cube_std)), 1)
            radius_ins = int(self.side_cube * np.sqrt(2) / 2)

            random_coord_x = np.random.randint(-self.side_cube, self.side + self.side_cube)
            random_coord_y = np.random.randint(-self.side_cube, self.side + self.side_cube)
            random_coord_z = np.random.randint(-self.side_cube, self.side + self.side_cube)
            if rotation:
                rotation_x = int(np.random.randint(-max_rotation, max_rotation))
                rotation_y = int(np.random.randint(-max_rotation, max_rotation))
                rotation_z = int(np.random.randint(-max_rotation, max_rotation))

            else:
                rotation_x = 0
                rotation_y = 0
                rotation_z = 0

            center_cube = [
                int(random_coord_x + self.side_cube / 2),
                int(random_coord_y + self.side_cube / 2),
                int(random_coord_z + self.side_cube / 2),
            ]

            rotated_center_cube = self.x_rotation(center_cube, math.radians(rotation_x / math.pi))
            rotated_center_cube = self.y_rotation(rotated_center_cube, math.radians(rotation_y / math.pi))
            rotated_center_cube = self.z_rotation(rotated_center_cube, math.radians(rotation_z / math.pi))

            return [
                radius_ins,
                rotated_center_cube,
                [random_coord_x, random_coord_y, random_coord_z],
                [rotation_x, rotation_y, rotation_z],
                side_cube,
            ]

        def cube_generator_biased(self):
            """

            Generates a cube within provided limits with biased
            coordinates and aleatory rotation. The cube will be placed according
            to a center coordinate, considering a normal probability function and
            the center accounting to the average.

            :return: radius in which the cube is inscribed, center list coordinate of
                    cube after random rotation, random coordinate list before rotation,
                    axis random rotation angle list, and new random side lengh.
            """

            side_cube = max(int(np.random.normal(self.side_cube, self.side_cube_std)), 1)
            radius_ins = int(self.side_cube * np.sqrt(2) / 2)
            random_coord_x = self.side * self.het * np.random.randn() + self.center[0]
            random_coord_y = self.side * self.het * np.random.randn() + self.center[1]
            random_coord_z = self.side * self.het * np.random.randn() + self.center[2]
            rotation_x = int(np.random.randint(-90, 90))
            rotation_y = int(np.random.randint(-90, 90))
            rotation_z = int(np.random.randint(-90, 90))
            center_cube = [
                int(random_coord_x + self.side_cube / 2),
                int(random_coord_y + self.side_cube / 2),
                int(random_coord_z + self.side_cube / 2),
            ]
            rotated_center_cube = self.x_rotation(center_cube, math.radians(rotation_x / math.pi))
            rotated_center_cube = self.y_rotation(rotated_center_cube, math.radians(rotation_y / math.pi))
            rotated_center_cube = self.z_rotation(rotated_center_cube, math.radians(rotation_z / math.pi))

            return [
                radius_ins,
                rotated_center_cube,
                [random_coord_x, random_coord_y, random_coord_z],
                [rotation_x, rotation_y, rotation_z],
                side_cube,
            ]

        def cube_list(self, try_number, bias=False, het=1, center=[0, 0, 0], rotation=True, max_rotation=90):
            """

            Generates a cube list.

            :het: heterogeneity factor.
            :center: center is the coordinate of the maximum probability of a
                    cube to be placed.
            :bias: true will generate heterogeneous cube distribution
            :try_number: number of attempts of cube placement (some of them are placed
                        outside the array grid after rotation).
            :return: a list of cubes with the outputs of the cube_generator function.
            """

            self.het = het
            self.center = center
            Cubes = []
            self.bias = bias
            cube_range = self.side + self.side_cube

            for n in range(try_number):
                if self.bias:
                    cube = self.cube_generator_biased()
                else:
                    cube = self.cube_generator(rotation, max_rotation)
                if cube[1][0] < cube_range and cube[1][1] < cube_range and cube[1][2] < cube_range:
                    if (
                        cube[1][0] > -self.side_cube / 2
                        and cube[1][1] > -self.side_cube / 2
                        and cube[1][2] > -self.side_cube / 2
                    ):
                        Cubes.append(cube)

            return Cubes

        def cubes_array(self, center_cube, rotations, new_side_cube, array, touching):
            """

            Insert a cube in a 3D array. Inputs are provided by the cube
            generator in addition to a 3d array.

            :center_cube: coordinate of cube vertice provided by the cube list.
                        function.
            :rotations: rotations provided by the cube list.
            :new_side_cube: side changed by the random probability set
                            on cube generator function.
            :array: array of zeros or a previously populated array.
            :touching: if true, the cubes will overlap themselves.
            :return: 3d array with a new cube.
            """
            x, y, z = np.meshgrid(
                np.arange(center_cube[0], center_cube[0] + new_side_cube),
                np.arange(center_cube[1], center_cube[1] + new_side_cube),
                np.arange(center_cube[2], center_cube[2] + new_side_cube),
            )
            list_coord = np.stack([x.flatten(), y.flatten(), z.flatten()], axis=-1)
            rot_matrix = R.from_euler("xyz", rotations, degrees=True).as_matrix()
            list_rotated = np.dot(list_coord, rot_matrix)
            list_rotated = np.rint(list_rotated).astype(int)
            list_rotated = np.clip(list_rotated, 0, self.side - 1)

            coord_min = np.min(list_rotated, axis=0)
            coord_max = np.max(list_rotated, axis=0)
            bounds_size = coord_max - coord_min + 1
            list_rotated -= coord_min

            dolomite_array = np.zeros(bounds_size, dtype=bool)
            dolomite_array[list_rotated[:, 0], list_rotated[:, 1], list_rotated[:, 2]] = True

            array_crop = array[
                coord_min[0] : coord_max[0] + 1, coord_min[1] : coord_max[1] + 1, coord_min[2] : coord_max[2] + 1
            ]
            if not touching:
                overlap = dolomite_array & (array_crop == self.phase_number)
                if np.any(overlap):
                    return array, 0

            if not self.cal_tou:
                overlap = dolomite_array & ((array_crop == self.sphere_number) | (array_crop == self.shrub_number))
                if np.any(overlap):
                    return array, 0
            new_voxels = (dolomite_array & (array_crop != self.phase_number)).sum()
            array_crop[dolomite_array] = self.phase_number
            return array, new_voxels

        def cubes(self, cube_list, array, touching):
            """

            Inserts a cube in a 3D array. Inputs are provided by the cube
            generator in addition to a 3d array.

            :cube_list: provided by cube_list_touching function
            :return: 3d array with a new cube.
            """

            array_2 = np.copy(array)
            Cubes_2, total = self.cubes_array(cube_list[0][2], cube_list[0][3], cube_list[0][4], array_2, touching)
            for i, cube in enumerate(cube_list[1:], start=1):
                Cubes_2, n = self.cubes_array(cube[2], cube[3], cube[4], Cubes_2, touching)
                total += n

                filled = total / self.side**3
                progress_phi = filled / (1 - self.phi)
                progress_cubes = i / len(cube_list)
                progress = max(progress_phi, progress_cubes)
                progressUpdate(progress)
                if filled > (1 - self.phi):
                    break

            Cubes_2[Cubes_2 == self.sphere_number] = 0
            Cubes_2[Cubes_2 == self.shrub_number] = 0
            Result = self.rotation_correction(Cubes_2)
            Result[array == self.sphere_number] = self.sphere_number
            Result[array == self.shrub_number] = self.shrub_number
            print("")

            if progress < 1:
                print("Porosity reached " + str(round((np.count_nonzero(Cubes_2 == 0) / self.side**3), 2)) + ".")
                print(
                    """If you desire to reach the input porosity, please 
                      increase the cubes number on the cube_list function parameter.
                      """
                )
                if self.bias:
                    print("Biased models tend to not reach low porosity.")
            else:
                print("Done!")
            print(" ")

            return Result

        def touching_cubes(self, cube_list, array):
            return self.cubes(cube_list, array, touching=True)

        def untouching_cubes(self, cube_list, array):
            return self.cubes(cube_list, array, touching=False)

        def touching_regular_cubes(self, cube_list, array):
            return self.regular_cubes(cube_list, array, touching=True)

        def untouching_regular_cubes(self, cube_list, array):
            return self.regular_cubes(cube_list, array, touching=False)

        def cubes_regular_spacing(self, gap, max_rotation=30, rotation=False, shift_position=False, shift_value=10):
            """

            Generates a list of regularly spaced cubes. They can touch
            each one.

            :gap: the gap between cubes.
            :max_rotation: maximum rotation of cubes.
            :rotation: if true, perform rotation of cubes.
            :shift_position: applies a random shift on cube position.
            :shift_value: maximum shift applied to the cube.
            :return: random coordinate list before rotation,
                axis random rotation angle list,
                and new random side length.
            """

            x, y, z = np.meshgrid(
                np.arange(0, self.side, self.side_cube + gap),
                np.arange(0, self.side, self.side_cube + gap),
                np.arange(0, self.side, self.side_cube + gap),
            )

            list_coord = np.stack([x.flatten(), y.flatten(), z.flatten()], axis=-1)

            n = 0
            result = []

            for coord in list_coord:
                if shift_position:
                    new_coord_x = int(coord[0] + np.random.randint(-shift_value, shift_value))
                    new_coord_y = int(coord[1] + np.random.randint(-shift_value, shift_value))
                    new_coord_z = int(coord[2] + np.random.randint(-shift_value, shift_value))

                else:
                    new_coord_x = int(list_coord[n][0])
                    new_coord_y = int(list_coord[n][1])
                    new_coord_z = int(list_coord[n][2])

                if rotation:
                    rotation_x = int(np.random.randint(-max_rotation, max_rotation))
                    rotation_y = int(np.random.randint(-max_rotation, max_rotation))
                    rotation_z = int(np.random.randint(-max_rotation, max_rotation))

                else:
                    rotation_x = 0
                    rotation_y = 0
                    rotation_z = 0

                side_cube_single = max(int(np.random.normal(self.side_cube, self.side_cube_std)), 1)
                result.append(
                    [[new_coord_x, new_coord_y, new_coord_z], [rotation_x, rotation_y, rotation_z], side_cube_single]
                )
                n += 1

            return result

        def regular_cubes(self, cube_regular_list, array, touching):
            """

            Insert regularly spaced cubes in an array. The cubes can touch
            each one.

            :cube_regular_list: regularly spaced cubes list provided by
                cubes_regular_spacing function.
            :return: the final 3d array
            """

            print("")
            print("---------- Progress ----------")
            n = 0

            array_2 = np.copy(array)
            Cubes_2, _ = self.cubes_array(
                cube_regular_list[0][0], cube_regular_list[0][1], cube_regular_list[0][2], array_2, touching=touching
            )

            for cube in cube_regular_list[1:]:
                Cubes_2, _ = self.cubes_array(cube[0], cube[1], cube[2], Cubes_2, touching=touching)

                progress = n / len(cube_regular_list)
                progressUpdate(progress)
                n += 1
            Cubes_2[Cubes_2 == self.sphere_number] = 0
            Cubes_2[Cubes_2 == self.shrub_number] = 0
            Result = self.rotation_correction(Cubes_2)
            Result[array == self.sphere_number] = self.sphere_number
            Result[array == self.shrub_number] = self.shrub_number
            print("")
            print("Done!")
            return Result

    class Shrubs:
        """

        This class built shrubstone models. I provide an initial shape that
        can be stretched or flattened. The shrubs nucleate in a random coordinate.
        They also can nucleate after a datum, which is useful to build models
        with spherulites.
        """

        def __init__(
            self,
            height,
            height_std,
            side,
            ratio=1,
            inclination_min=80,
            dat_set=False,
            datum=0,
            phase_number=3,
            spherulite_number=2,
        ):
            """

            :height: shrub height.
            :height_std: shrub std height.
            :side: side of the array.
            :ratio: it defines the shape, 0 is more elongated, and more than 1 will
            generate a flat shrub.
            :inclination: it sets the inclination of the shrub.
            :dat_set: it sets if shurbs will nucleate after a defined datum
            or randomly.
            :datum: if dat_set is true, the nucleation datum should be
            provided. The shrubs will nucleate after the datum.
            :spherulite_number: if an array with spherulites is used as input,
            it sets the spherulite on it. The default is 2.
            :phase_number: the shrub number on models.
            """

            self.height = height
            self.height_std = height_std
            self.side = side
            self.ratio = ratio
            self.inclination_min = inclination_min
            self.dat_set = dat_set
            self.datum = datum
            self.phase_number = phase_number
            self.spherulite_number = spherulite_number
            self.precompute()

        def precompute(self):
            from scipy.interpolate import interp1d

            # The shape of shrubs was provided according to the relative change
            # of their radius.
            Shrub_Shape_radius = [0, 65, 90, 105, 115, 127.5, 135, 137.5, 135, 130, 115, 60, 0]
            Shrub_Shape_height = [0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 570]

            height_proportion = self.height / max(Shrub_Shape_height)

            duplicated_radii = [int(x * height_proportion * self.ratio) for x in Shrub_Shape_radius]
            duplicated_heights = [int(x * height_proportion) for x in Shrub_Shape_height]

            radii = [duplicated_radii[0]]
            heights = [duplicated_heights[0]]

            for i in range(1, len(duplicated_heights)):
                if duplicated_heights[i] > duplicated_heights[i - 1]:
                    radii.append(duplicated_radii[i])
                    heights.append(duplicated_heights[i])

            f = interp1d(heights, radii, kind="quadratic")
            self.Shrub_Shape_radius = radii
            self.Shrub_Shape_height_new = np.linspace(0, self.height - 1, num=self.height, endpoint=True)
            self.Shrub_Shape_radius_new = f(self.Shrub_Shape_height_new)

        def shrub_generator(self):
            """

            Generates a shrub list used by other functions.

            :return: the shrub list used by other functions.
            """

            Shrub_Shape_radius = self.Shrub_Shape_radius
            Shrub_Shape_height_new = self.Shrub_Shape_height_new
            Shrub_Shape_radius_new = self.Shrub_Shape_radius_new

            x = np.random.randint(-max(Shrub_Shape_radius) / 2, self.side + max(Shrub_Shape_radius) / 2)
            z = np.random.randint(-max(Shrub_Shape_radius) / 2, self.side + max(Shrub_Shape_radius) / 2)

            n = 0
            list_coord = []

            for radius in Shrub_Shape_radius_new:
                list_coord.append((x, Shrub_Shape_height_new[n], z))
                n += 1

            inclination_x = np.random.randint(self.inclination_min, 90)
            x_rotated = [
                math.tan(math.radians(90 - inclination_x)) * (coord[1] - min(Shrub_Shape_height_new)) + coord[0]
                for coord in list_coord
            ]
            inclination_z = np.random.randint(self.inclination_min, 90)
            z_rotated = [
                math.tan(math.radians(90 - inclination_z)) * (coord[1] - min(Shrub_Shape_height_new)) + coord[2]
                for coord in list_coord
            ]

            n = 0
            result = []

            if self.dat_set:
                y_factor = np.random.randint(self.datum, self.side)

            else:
                y_factor = np.random.randint(-self.height, self.side)

            for y_n in list_coord:
                result.append((int(x_rotated[n]), int(y_n[1] + y_factor), int(z_rotated[n]), Shrub_Shape_radius_new[n]))
                n += 1

            return result

        def single_shrub(self, Shrub_List, array):
            """

            Inserts a single shrub in a 3d array. The shrubs are allowed
            to replace previous ones.

            :Shrub_List: list provided by shrub_generator function.
            :array: an array with zeros or other shrubs.

            :return: an array with a new shrub.
            """

            x_ = np.linspace(0, self.side, self.side)
            y_ = np.linspace(0, self.side, self.side)
            u, v = np.meshgrid(x_, y_, indexing="ij")
            d = array

            # The shrub will be built by print a sphere in each x slice,
            # from bottom to the top.
            for center in Shrub_List:
                if (center[1] >= 0) and (center[1] < self.side):
                    radius = int(center[3])
                    center = center[:3]

                    """
                    c = np.square(u - center[0]) + np.square(v - center[2])
                    c1 = c <= radius ** 2
                    n_voxels += c1.sum()
                    d[center[1], c1] = self.phase_number
                    """
                    cv2.circle(d[center[1], :, :], (center[0], center[2]), radius, self.phase_number, -1)

            return d

        def shrubstone(self, array, phi):
            """

            Inserts all shrubs provided by the shrub list, invoking shrub_generator
            and single_shrub functions until the target porosity is reached.

            :array: an array with zeros or other shrubs.
            :phi: target porosity.
            :return: an array with the final shrubstone model.
            """

            print("")
            print("---------- Progress ----------")

            print(" If datum option is set, the porosity will be approximated")
            print(" only after the datum.")

            third_side = self.side - self.datum if self.dat_set else self.side
            target_n_voxels = int((1 - phi) * self.side * self.side * third_side)
            progress = 0
            n = 0
            sample_period = 10
            while progress < 1:
                list_coord = self.shrub_generator()
                array = self.single_shrub(list_coord, array)

                n += 1

                if n % 10 == 0:
                    array_sample = array[0::sample_period, 0::sample_period, 0::sample_period]
                    n_voxels = (array_sample == self.phase_number).sum()
                    progress = n_voxels * sample_period**3 / target_n_voxels
                    progressUpdate(progress)

            print("")
            print("Done!")

            return array

    def dissolve(array, from_phase, to_phase, phi, grow_prob, speed=0.5):
        side = array.shape[0]
        from_count = (array == from_phase).sum()
        target_dissolve_voxels_n = int(from_count * phi)

        kernel_1d = np.array([True, True, True], dtype=bool)
        progress = 0
        original_to_phase = to_phase
        to_phase = 77

        i = 0
        while progress < 0.95:
            from_array = array == from_phase

            if i == 0 and from_array.sum() == 0:
                return array

            if i % 10 == 0:
                # Update these less often for performance
                random_array = np.random.rand(side, side, side)
                grow_mask = random_array < speed
                from_voxels = np.argwhere(from_array)
            i += 1
            to_array = array == to_phase

            will_grow = np.random.rand() < grow_prob and i > 0

            if will_grow:
                neighbors = scipy.ndimage.convolve1d(to_array, kernel_1d, axis=0, mode="constant", cval=0.0)
                neighbors |= scipy.ndimage.convolve1d(to_array, kernel_1d, axis=1, mode="constant", cval=0.0)
                neighbors |= scipy.ndimage.convolve1d(to_array, kernel_1d, axis=2, mode="constant", cval=0.0)

                neighbors = neighbors & from_array
                array[grow_mask & neighbors] = to_phase

            else:
                random_index = np.random.randint(0, len(from_voxels))
                random_voxel = tuple(from_voxels[random_index])
                array[random_voxel] = to_phase

            progress = (array == to_phase)[::10, ::10, ::10].sum() * 1000 / target_dissolve_voxels_n
            progressUpdate(progress)

        array[array == to_phase] = original_to_phase
        return array

    def fracture(array, phase, n_planes, x_angle_range, y_angle_range, offset_range, thickness_range, displace):
        for n in range(n_planes):
            x_angle = np.random.uniform(*x_angle_range)
            y_angle = np.random.uniform(*y_angle_range)
            offset = np.random.uniform(*offset_range)
            thickness = np.random.uniform(*thickness_range)

            x_angle = np.radians(x_angle)
            y_angle = np.radians(y_angle)

            normal = np.array([np.cos(x_angle) * np.cos(y_angle), np.sin(x_angle) * np.cos(y_angle), np.sin(y_angle)])
            print(normal)

            side = array.shape[0]
            center = side // 2
            min_ = -center
            max_ = min_ + side

            z, y, x = np.meshgrid(np.arange(min_, max_), np.arange(min_, max_), np.arange(min_, max_), indexing="ij")
            coords = np.stack([z.flatten(), y.flatten(), x.flatten()], axis=-1)
            coords = coords.reshape((side, side, side, 3))
            signed_distances = np.dot(coords, normal) - offset

            if displace:
                displaced_a = scipy.ndimage.shift(array, normal * thickness / 2, order=0)
                displaced_b = scipy.ndimage.shift(array, -normal * thickness / 2, order=0)
                array[signed_distances >= 0] = displaced_a[signed_distances >= 0]
                array[signed_distances < 0] = displaced_b[signed_distances < 0]

            array[np.abs(signed_distances) < thickness / 2] = phase
            progress = n / n_planes
            progressUpdate(progress)
        return array
