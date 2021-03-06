import time;
import sys;
import os;
import numpy as np;
import scipy.sparse;
import scipy.sparse.linalg;
import math;
import ARAP.face as face;
import ARAP.othermath as omath;
np.set_printoptions(precision=2, suppress=True);

solve   = scipy.sparse.linalg.spsolve;
matrix  = scipy.sparse.lil_matrix;
csrmatrix = scipy.sparse.csr_matrix;

# Read file into arrays
class Deformer:
    
    max_iterations = 100;
    threshold = 0.001;
    
    def __init__(self, filename=None):        
        self.filename = filename
        self.POWER = float('Inf');
        
    
    def __getRowsColumnsData(self, index=0):
        vpos = self.__verts;
        faces = self.__faces;
        index1 = (index+1)%3;
        index2 = (index+2)%3;
        dist_index1 = np.sqrt(np.sum((vpos[faces[:,index]] - vpos[faces[:,index1]])**2, axis=1));
        dist_index2 = np.sqrt(np.sum((vpos[faces[:,index]] - vpos[faces[:,index2]])**2, axis=1));
        
        rows = np.tile(faces[:,index], 2);
        cols = np.vstack((faces[:,index1], faces[:,index2])).flatten();
        data = np.vstack((dist_index1, dist_index2)).flatten();
        
        return rows, cols, data;
    
    def __meshadjacency(self):
        V_N = self.__verts.shape[0];
        r1, c1, d1 = self.__getRowsColumnsData(index=0);
        r2, c2, d2 = self.__getRowsColumnsData(index=1);
        r3, c3, d3 = self.__getRowsColumnsData(index=2);
        r, c, d = np.vstack((r1, r2, r3)).flatten(), np.vstack((c1, c2, c3)).flatten(), np.vstack((d1, d2, d3)).flatten();
        csgraph = csrmatrix((d, (r,c)), shape=(V_N, V_N)).tocsr();
        return csgraph;
    
    #vertces - np.array (n x 3);
    #faces - np.array (fn x 3, dtype=int) - faces and vertex ids
    #edgevertices = np.array (en x 2, dtype=int) - edges and vertex ids
    def setMesh(self, vertices, faces, edges):
        number_of_verticies =   vertices.shape[0];
        number_of_faces =       faces.shape[0];
        number_of_edges =       edges.shape[0];
        
        self.__verts = vertices;
        self.__faces = faces;
        self.__adjacency = self.__meshadjacency();
        
        self.n = number_of_verticies;        
        # Every vertex in the .off
        self.verts = [];
        self.verts_prime = [];
        # Every face in the .off
        self.faces = [];
        # The ID of the faces related to this vertx ID (i.e. vtf[i] contains faces that contain ID i)
        self.verts_to_face = [];
        
        for i in range(self.n):
            x,y,z = vertices[i];
            self.verts.append(np.array([x, y, z]));
            self.verts_prime.append(np.array([x, y, z]));
            self.verts_to_face.append([]);
            
        self.verts_prime = np.asmatrix(self.verts_prime);
        self.neighbour_matrix = matrix((self.n, self.n));

        print("Generating Adjacencies");
        for i in range(number_of_faces):
            v1_id, v2_id, v3_id = faces[i];
            self.faces.append(face.Face(v1_id, v2_id, v3_id));
            # Add this face to each vertex face map
            self.assign_values_to_neighbour_matrix(v1_id, v2_id, v3_id);
            self.verts_to_face[v1_id].append(i);
            self.verts_to_face[v2_id].append(i);
            self.verts_to_face[v3_id].append(i);

        print("Generating Edge Matrix")
        self.edge_matrix = matrix((self.n, self.n));

        for row in range(self.n):
            self.edge_matrix[row, row] = self.neighbour_matrix[row].sum();
        print("Generating Laplacian Matrix");

        # N size array of 3x3 matricies
        self.cell_rotations = np.zeros((self.n, 3, 3));

        print(str(len(self.verts)) + " verticies");
        print(str(len(self.faces)) + " faces");
        print(str(number_of_edges) + " edges"); 
    
    #handles(k x 1) list of vertex ids that are handles,
    #handledeformations(k x 4 x 4) deformation to apply for each handle
    #fixed (l x 1) list of vertex ids that are fixed
    def setVertexTypesAndDeformations(self, fixed, handles, handledeformations):
        self.selected_verts = [];
        self.fixed_verts = [];
        
        verts_types = np.ones((self.n), dtype=np.int);
        
        verts_types[handles] = 2;
        verts_types[fixed] = 0;
        
        self.vert_status = np.copy(verts_types);        
        self.selected_verts.extend(handles);
        #Handles ids and their transformed vertex positions 
        handles_ids_verts = [(handles[i], omath.apply_rotation(handledeformations[i], self.verts[handles[i]])) for i in range(handles.shape[0])];
        fixed_ids_verts =  [(fixed[i], self.verts[fixed[i]]) for i in range(fixed.shape[0])];
        
        self.fixed_verts.extend(handles_ids_verts);
        self.fixed_verts.extend(fixed_ids_verts);
        
        assert(len(self.vert_status) == len(self.verts));    
    
    #vertces - np.array (n x 3);
    #faces - np.array (fn x 3, dtype=int) - faces and vertex ids
    #edges = np.array (en x 2, dtype=int) - edges and vertex ids
    #fixed = np.array(fixed_n x 1, dtype=int) - array of vertex ids that are fixed
    #handles = np.array(handles_n x 1, dtype=int) - array of vertex ids that are handles
    #handledeformations = np.array(handledeformations_n x 4 x 4, dtype=float) - array of 4x4 deformations for vertex ids in handles. 
    #iterations - int - total iterations for ARAP to perform
    def arapParameters(self, vertices, faces, edges, fixed, handles, handledeformations, iterations=3):
        t = time.time();
        self.setMesh(vertices, faces, edges);
        self.setVertexTypesAndDeformations(fixed, handles, handledeformations);
        self.build_weight_matrix();
        self.calculate_laplacian_matrix();
        self.precompute_p_i();
        print("Precomputation time ", time.time() - t);
        t = time.time();
        self.apply_deformation(iterations);
        print("Total iteration time", time.time() - t);
    
    def arapParametersWithLaplacian(self, vertices, faces, edges, laplacian, fixed, handles, handledeformations, iterations=3):
        t = time.time();
        self.setMesh(vertices, faces, edges);
        self.setVertexTypesAndDeformations(fixed, handles, handledeformations);        
        
        print("Generating Weight Matrix with Supplied Laplacian");
        self.weight_sum = matrix((self.n, self.n), dtype=np.float);        
        rc = np.arange(vertices.shape[0]);
        
        self.weight_sum[rc, rc] = laplacian[rc, rc];
        self.weight_matrix = laplacian;
        self.weight_matrix[rc, rc] = 0.0;
        
#         self.weight_sum[self.weight_sum.nonzero()] *= -1;
        self.weight_matrix[self.weight_matrix.nonzero()] *= -1;
        
#         self.weight_sum[rc, rc] = laplacian[rc, rc]*-1.0;
#         self.weight_matrix = laplacian;
#         self.weight_matrix[rc, rc] = 0.0;
        
        self.calculate_laplacian_matrix();
        self.precompute_p_i();
        print("Precomputation time ", time.time() - t);
        t = time.time();
        self.apply_deformation(iterations);
        print("Total iteration time", time.time() - t);
    
    
    def assign_values_to_neighbour_matrix(self, v1, v2 ,v3):
        self.neighbour_matrix[v1, v2] = 1;
        self.neighbour_matrix[v2, v1] = 1;
        self.neighbour_matrix[v1, v3] = 1;
        self.neighbour_matrix[v3, v1] = 1;
        self.neighbour_matrix[v2, v3] = 1;
        self.neighbour_matrix[v3, v2] = 1;    
        
    
    # Returns a set of IDs that are neighbours to this vertexID (not including the input ID)
    def neighbours_of(self, vert_id):
        __, neighbours = self.__adjacency[vert_id].nonzero();        
        neighbours = neighbours.tolist();
        
#         neighbours = [];
#         for n_id in range(self.n):
#             if(self.neighbour_matrix[vert_id, n_id] == 1):
#                 neighbours.append(n_id);
        return neighbours;

    def build_weight_matrix(self):
        print("Generating Weight Matrix");
        self.weight_matrix = matrix((self.n, self.n), dtype=np.float);
        self.weight_sum = matrix((self.n, self.n), dtype=np.float);

        for vertex_id in range(self.n):
            neighbours = self.neighbours_of(vertex_id);
            for neighbour_id in neighbours:
                self.assign_weight_for_pair(vertex_id, neighbour_id);
        print(self.weight_matrix);
        print(self.weight_sum);

    def assign_weight_for_pair(self, i, j):
        if(self.weight_matrix[j, i] == 0):
            # If the opposite weight has not been computed, do so
            weightIJ = self.weight_for_pair(i, j);
        else:
            weightIJ = self.weight_matrix[j, i];
        self.weight_sum[i, i] += weightIJ * 0.5;
        self.weight_sum[j, j] += weightIJ * 0.5;
        self.weight_matrix[i, j] = weightIJ;

    def weight_for_pair(self, i, j):
        local_faces = [];
        # For every face associated with vert index I,
        for f_id in self.verts_to_face[i]:
            face = self.faces[f_id];
            # If the face contains both I and J, add it
            if face.contains_point_ids(i, j):
                local_faces.append(face);

        # Either a normal face or a boundry edge, otherwise bad mesh
        assert(len(local_faces) <= 2);

        vertex_i = self.verts[i];
        vertex_j = self.verts[j];

        # weight equation: 0.5 * (cot(alpha) + cot(beta))

        cot_theta_sum = 0;
        for face in local_faces:
            other_vertex_id = face.other_point(i, j);
            vertex_o = self.verts[other_vertex_id];
            theta = omath.angle_between(vertex_i - vertex_o, vertex_j - vertex_o);
            cot_theta_sum += omath.cot(theta);
        return cot_theta_sum * 0.5;

    def calculate_laplacian_matrix(self):
        print("Generating LAPLACIAN Matrix");
        # initial laplacian
        # self.laplacian_matrix = self.edge_matrix - self.neighbour_matrix
        self.laplacian_matrix = self.weight_sum - self.weight_matrix;
        fixed_verts_num = len(self.fixed_verts);
        # for each constrained point, add a new row and col
        new_n = self.n + fixed_verts_num;
        new_matrix = matrix((new_n, new_n), dtype=np.float);
        # Assign old values to new matrix
        new_matrix[:self.n, :self.n] = self.laplacian_matrix;
        # Add 1s in the row and column associated with the fixed point to constain it
        # This will increase L by the size of fixed_verts
        for i in range(fixed_verts_num):
            new_i = self.n + i;
            vert_id = self.fixed_verts[i][0];
            new_matrix[new_i, vert_id] = 1;
            new_matrix[vert_id, new_i] = 1;
        print(self.laplacian_matrix);

        self.laplacian_matrix = new_matrix;

    def apply_deformation(self, iterations):
        print('APPLY DEFORMATION ');
        print("Length of sel verts", len(self.selected_verts));

        if iterations < 0:
            iterations = self.max_iterations;

        self.current_energy = 0;

        # initialize b and assign constraints
        number_of_fixed_verts = len(self.fixed_verts);

        self.b_array = np.zeros((self.n + number_of_fixed_verts, 3));
        # Constraint b points
        for i in range(number_of_fixed_verts):
            self.b_array[self.n + i] = self.fixed_verts[i][1];

        # Apply following deformation iterations
        for t in range(iterations):
            print("Iteration: ", t);

            self.calculate_cell_rotations();
            self.apply_cell_rotations();
            iteration_energy = self.calculate_energy();
            print("Total Energy: ", self.current_energy);
            # if(self.energy_minimized(iteration_energy)):
            #     print("Energy was minimized at iteration", t, " with an energy of ", iteration_energy)
            #     break
            self.current_energy = iteration_energy;

    def energy_minimized(self, iteration_energy):
        return abs(self.current_energy - iteration_energy)  < self.threshold;

    def calculate_cell_rotations(self):
        print("Calculating Cell Rotations");
        for vert_id in range(self.n):
            rotation = self.calculate_rotation_matrix_for_cell(vert_id);
            self.cell_rotations[vert_id] = rotation;

    def vert_is_deformable(self, vert_id):
        return self.vert_status[vert_id] == 1;

    def precompute_p_i(self):
        print("PRECOMPUTE_P_I");
        self.P_i_array = []
        for i in range(self.n):
            vert_i = self.verts[i];
#             neighbour_ids = self.neighbours_of(i);
            __, neighbour_ids = self.weight_matrix[i].nonzero();
            neighbour_ids = neighbour_ids.tolist();
            
            number_of_neighbours = len(neighbour_ids);

            P_i = np.zeros((3, number_of_neighbours));

            for n_i in range(number_of_neighbours):
                n_id = neighbour_ids[n_i];

                vert_j = self.verts[n_id];
                P_i[:, n_i] = (vert_i - vert_j);
                
            self.P_i_array.append(P_i);

    def apply_cell_rotations(self):
        print("Applying Cell Rotations");

        # Regular b points
        for i in range(self.n):
            self.b_array[i] = self.calculate_b_for(i);

        print("Printing B")
        print(self.b_array);

        p_prime = solve(self.laplacian_matrix.tocsr(), self.b_array);

        # self.verts = self.verts_prime

        for i in range(self.n):
            self.verts_prime[i] = p_prime[i];

        # print("p prime")
        # print(p_prime)

    def calculate_rotation_matrix_for_cell(self, vert_id):
        covariance_matrix = self.calculate_covariance_matrix_for_cell(vert_id);

        U, s, V_transpose = np.linalg.svd(covariance_matrix);

        # U, s, V_transpose
        # V_transpose_transpose * U_transpose


        rotation = V_transpose.transpose().dot(U.transpose());
        if np.linalg.det(rotation) <= 0:
            U[:0] *= -1;
            rotation = V_transpose.transpose().dot(U.transpose());
        return rotation;

    def calculate_covariance_matrix_for_cell(self, vert_id):
        # s_i = P_i * D_i * P_i_prime_transpose
        vert_i_prime = self.verts_prime[vert_id];

#         neighbour_ids = self.neighbours_of(vert_id);
        __, neighbour_ids = self.weight_matrix[vert_id].nonzero();
        neighbour_ids = neighbour_ids.tolist();
        
        number_of_neighbours = len(neighbour_ids);

        D_i = np.zeros((number_of_neighbours, number_of_neighbours));

        P_i =       self.P_i_array[vert_id];
        P_i_prime = np.zeros((3, number_of_neighbours));

        for n_i in range(number_of_neighbours):
            n_id = neighbour_ids[n_i];

            D_i[n_i, n_i] = self.weight_matrix[vert_id, n_id];

            vert_j_prime = self.verts_prime[n_id];
            P_i_prime[:, n_i] = (vert_i_prime - vert_j_prime);

        P_i_prime = P_i_prime.transpose();
        return P_i.dot(D_i).dot(P_i_prime);
    
    
    @property
    def outputvertices(self):
        return self.verts_prime;
    
    def calculate_b_for(self, i):
        b = np.zeros((1, 3));
#         neighbours = self.neighbours_of(i);
        __, neighbours = self.weight_matrix[i].nonzero();
        neighbours = neighbours.tolist();
            
        for j in neighbours:
            w_ij = self.weight_matrix[i, j] / 2.0;
            r_ij = self.cell_rotations[i] + self.cell_rotations[j];
            # print(r_ij)
            p_ij = self.verts[i] - self.verts[j];
            b += (w_ij * r_ij.dot(p_ij));
        return b;

    def calculate_energy(self):
        total_energy = 0;
        for i in range(self.n):
            total_energy += self.energy_of_cell(i);
        return total_energy;

    def energy_of_cell(self, i):
#         neighbours = self.neighbours_of(i);
        __, neighbours = self.weight_matrix[i].nonzero();
        neighbours = neighbours.tolist();
            
        total_energy = 0;
        for j in neighbours:
            w_ij = self.weight_matrix[i, j];
            e_ij_prime = self.verts_prime[i] - self.verts_prime[j];
            e_ij = self.verts[i] - self.verts[j];
            r_i = self.cell_rotations[i];
            value = e_ij_prime - r_i.dot(e_ij);
            if(self.POWER == float('Inf')):
                norm_power = omath.inf_norm(value);
            else:
                norm_power = np.power(value, self.POWER);
                norm_power = np.sum(norm_power);
            # total_energy += w_ij * np.linalg.norm(, ord=self.POWER) ** self.POWER
            total_energy += w_ij * norm_power;
        return total_energy;

    def hex_color_for_energy(self, energy, max_energy):
        relative_energy = (energy / max_energy) * 255;
        relative_energy = max(0, min(int(relative_energy), 255));
        red = hex(relative_energy)[2:];
        blue = hex(255 - relative_energy)[2:];
        if len(red) == 1:
            red = "0" + red;
        if len(blue) == 1:
            blue = "0" + blue;
        return "#" + red + "00" + blue;

    def hex_color_array(self):
        energies = [ self.energy_of_cell(i) for i in range(self.n) ];
        max_value = np.amax(energies);
        return [ self.hex_color_for_energy(energy, max_value) for energy in energies ];    
    
    def output_s_prime_to_file(self):
        print("Writing to `output.off`");
        f = open('output.off', 'w');
        f.write("OFF\n");
        f.write(str(self.n) + " " + str(len(self.faces)) + " 0\n");
        for vert in self.verts_prime:
            for i in np.nditer(vert):
                f.write(str(i) + " ");
            f.write("\n");
        for face in self.faces:
            f.write(face.off_string() + "\n");
        f.close();
        print("Output file to `output.off`");
    
    
    
    
    