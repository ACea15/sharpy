import numpy as np
import h5py as h5
from sharpy.utils.solver_interface import solver, BaseSolver, initialise_solver
import sharpy.utils.settings as settings
import sharpy.linear.src.libss as libss
import sharpy.utils.algebra as algebra
import scipy.linalg as sclalg
import sharpy.utils.h5utils as h5utils
from sharpy.utils.datastructures import LinearTimeStepInfo
import sharpy.utils.cout_utils as cout
import time
import pandas as pd
import warnings

@solver
class LinearDynamicSimulation(BaseSolver):
    solver_id = 'LinDynamicSim'

    def __init__(self):

        self.settings_types = dict()
        self.settings_default = dict()

        self.settings_default['struct_states'] = 0
        self.settings_types['struct_states'] = 'int'

        self.settings_types['modal'] = 'bool'
        self.settings_default['modal'] = False

        self.settings_default['n_tsteps'] = 10
        self.settings_types['n_tsteps'] = 'int'

        self.settings_default['dt'] = 0.001
        self.settings_types['dt'] = 'float'
        
        self.settings_default['sys_id'] = ''
        self.settings_types['sys_id'] = 'str'

        self.settings_types['postprocessors'] = 'list(str)'
        self.settings_default['postprocessors'] = list()

        self.settings_types['postprocessors_settings'] = 'dict'
        self.settings_default['postprocessors_settings'] = dict()

        self.settings_types['output'] = 'str'
        self.settings_default['output'] = './cases/output/'

        self.data = None
        self.settings = dict()
        self.postprocessors = dict()
        self.with_postprocessors = False

        self.input_data_dict = dict()
        self.input_file_name = ""

        warnings.warn('LinDynamicSim solver under development')


    def initialise(self, data, custom_settings=None):

        self.data = data
        if custom_settings:
            self.settings = custom_settings
        else:
            self.settings = data.settings[self.solver_id]
        settings.to_custom_types(self.settings, self.settings_types, self.settings_default)

        # Read initial state and input data and store in dictionary
        self.read_files()

        # initialise postprocessors
        self.postprocessors = dict()
        if len(self.settings['postprocessors']) > 0:
            self.with_postprocessors = True
        for postproc in self.settings['postprocessors']:
            self.postprocessors[postproc] = initialise_solver(postproc)
            self.postprocessors[postproc].initialise(
                self.data, self.settings['postprocessors_settings'][postproc])

    def run(self):

        dt = self.settings['dt'].value
        n_steps = self.settings['n_tsteps'].value
        T = n_steps*dt
        t_dom = np.linspace(0, T, n_steps)
        sys_id = self.settings['sys_id']

        x0 = self.input_data_dict['x0']
        u = self.input_data_dict['u']

        ss = self.data.linear.ss

        # Use the scipy linear solver
        sys = libss.ss_to_scipy(ss)
        cout.cout_wrap('Solving linear system using scipy...')
        t0 = time.time()
        out = sys.output(u, t=t_dom, x0=x0)
        ts = time.time() - t0
        cout.cout_wrap('\tSolved in %.2fs' % ts, 1)

        t_out = out[0]
        x_out = out[2]
        y_out = out[1]

        process = True  # Under development
        if process:
            # Pack state variables into linear timestep info
            cout.cout_wrap('Plotting results...')
            for n in range(len(t_out)-1):
                tstep = LinearTimeStepInfo()
                tstep.x = x_out[n, :]
                tstep.y = y_out[n, :]
                tstep.t = t_out[n]
                tstep.u = u[n, :]
                self.data.linear.timestep_info.append(tstep)
                # TODO: option to save to h5

                # Pack variables into respective aero or structural time step infos (with the + f0 from lin)
                # Need to obtain information from the variables in a similar fashion as done with the database
                # for the beam case

                aero_tstep, struct_tstep = state_to_timestep(self.data, sys_id, tstep.x, tstep.u, tstep.y)

                self.data.aero.timestep_info.append(aero_tstep)
                self.data.structure.timestep_info.append(struct_tstep)

                # run postprocessors
                if self.with_postprocessors:
                    for postproc in self.postprocessors:
                        self.data = self.postprocessors[postproc].run(online=True)


        export = True
        if export:
            y_pd = pd.DataFrame(data=y_out)
            x_pd = pd.DataFrame(data=x_out)
            t_pd = pd.DataFrame(data=t_out)
            u_pd = pd.DataFrame(data=u)
            y_pd.to_csv(self.data.settings['SHARPy']['route'] + '/output/y_out.csv')
            x_pd.to_csv(self.data.settings['SHARPy']['route'] + '/output/x_out.csv')
            t_pd.to_csv(self.data.settings['SHARPy']['route'] + '/output/t_out.csv')
            u_pd.to_csv(self.data.settings['SHARPy']['route'] + '/output/u_out.csv')
        return self.data


    def read_files(self):

        self.input_file_name = self.data.settings['SHARPy']['route'] + '/' + self.data.settings['SHARPy']['case'] + '.lininput.h5'

        # Check that the file exists
        try:
            h5utils.check_file_exists(self.input_file_name)
            # Read and store
            with h5.File(self.input_file_name, 'r') as input_file_handle:
                self.input_data_dict = h5utils.load_h5_in_dict(input_file_handle)
        except FileNotFoundError:
            pass


    def structural_state_to_timestep(self, x):
        """
        Convert SHARPy beam state to original beam structure for plotting purposes.

        Args:
            x:

        Returns:

        """

        tstep = self.data.structure.timestep_info[0].copy()

        num_node = tstep.num_node

        q = x[:len(x)//2]
        dq = x[len(x)//2:]

        coords_a = np.array([q[6*i_node + [0, 1, 2]] for i_node in range(num_node-1)])
        crv = np.array([q[6*i_node + [3, 4, 5]] for i_node in range(num_node-1)])
        for_vel = dq[6*num_node:6*num_node+6]

        orient = dq[6*num_node:6*num_node+6:]
        if len(orient) == 3:
            quat = algebra.euler2quat(orient)
        else:
            quat = orient


def state_to_timestep(data, sys_id, x, u=None, y=None):
    """
    Writes a state-space vector to SHARPy timesteps

    Args:
        data:
        sys_id:
        x:
        u:
        y:
        modal:

    Returns:

    """

    if data.settings['LinearAssembler']['linear_system_settings']['beam_settings']['modal_projection'].value and \
            data.settings['LinearAssembler']['linear_system_settings']['beam_settings']['inout_coords'] == 'modes':
        modal = True
    else:
        modal = False
    # modal = True
    x_aero = x[:data.linear.linear_system.uvlm.ss.states]
    x_struct = x[-data.linear.linear_system.beam.ss.states:]
    # u_aero = TODO: external velocities
    phi = data.linear.linear_system.beam.sys.U
    Kas = data.linear.linear_system.couplings['Kas']

    # Beam output
    y_beam = x_struct

    u_q = np.zeros(data.linear.linear_system.uvlm.ss.inputs)
    if u is not None:
        u_q += u[:data.linear.linear_system.uvlm.ss.inputs]
        u_q[:y_beam.shape[0]] += y_beam
    else:
        u_q[:y_beam.shape[0]] += y_beam

    if modal:
        # add eye matrix for extra inputs
        n_modes = phi.shape[1]
        n_inputs_aero_only = len(u_q) - 2*n_modes  # Inputs to the UVLM other than structural inputs
        u_aero = Kas.dot(sclalg.block_diag(phi, phi, np.eye(n_inputs_aero_only)).dot(u_q))
    else:
        # if u_q.shape[0] !=
        # u_aero_zero = data.linear.tsaero0
        u_aero = Kas.dot(u_q)

    # Unpack input
    zeta, zeta_dot, u_ext = data.linear.linear_system.uvlm.unpack_input_vector(u_aero)

    # Also add the beam forces. I have a feeling there is a minus there as well....
    # Aero
    forces, gamma, gamma_dot, gamma_star = data.linear.linear_system.uvlm.unpack_ss_vector(
        data,
        x_n=x_aero,
        aero_tstep=data.linear.tsaero0,
        track_body=True)

    current_aero_tstep = data.aero.timestep_info[-1].copy()
    current_aero_tstep.forces = [forces[i_surf] + 0 * data.linear.tsaero0.forces[i_surf] for i_surf in
                                 range(len(gamma))]
    current_aero_tstep.gamma = [gamma[i_surf] + data.linear.tsaero0.gamma[i_surf] for i_surf in
                                range(len(gamma))]
    current_aero_tstep.gamma_dot = [gamma_dot[i_surf] + data.linear.tsaero0.gamma_dot[i_surf] for i_surf in
                                    range(len(gamma))]
    current_aero_tstep.gamma_star = [gamma_star[i_surf] + data.linear.tsaero0.gamma_star[i_surf] for i_surf in
                                     range(len(gamma))]
    current_aero_tstep.zeta = zeta
    current_aero_tstep.zeta_dot = zeta_dot
    current_aero_tstep.u_ext = u_ext

    # self.data.aero.timestep_info.append(current_aero_tstep)

    aero_forces = data.linear.linear_system.uvlm.C_to_vertex_forces.dot(x_aero)
    beam_forces = data.linear.linear_system.couplings['Ksa'].dot(aero_forces)

    if u is not None:
        u_struct = u[-data.linear.linear_system.beam.ss.inputs:]
    # y_struct = y[:self.data.linear.lsys[sys_id].lsys['LinearBeam'].ss.outputs]

    # Reconstruct the state if modal
    if modal:
        phi = data.linear.linear_system.beam.sys.U
        x_s = sclalg.block_diag(phi, phi).dot(x_struct)
    else:
        x_s = x_struct
    y_s = beam_forces #+ phi.dot(u_struct)
    # y_s = self.data.linear.lsys['LinearBeam'].sys.U.T.dot(y_struct)

    current_struct_step = data.linear.linear_system.beam.unpack_ss_vector(x_s, y_s, data.linear.tsstruct0)
    # data.structure.timestep_info.append(current_struct_step)

    return current_aero_tstep, current_struct_step

