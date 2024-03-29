#!/usr/bin/env python
"""
Starter code for EE106B Turtlebot Lab
Author: Valmik Prabhu, Chris Correa
Adapted for Spring 2020 by Amay Saxena
"""
from math import *
import numpy as np
import rospy
from scipy.integrate import quad,quadrature,ode,odeint
from scipy import optimize
import sys
from copy import copy
import matplotlib.pyplot as plt
from configuration_space import Plan, BicycleConfigurationSpace

class SinusoidPlanner():
    def __init__(self, config_space):
        """
        Turtlebot planner that uses sequential sinusoids to steer to a goal pose.

        config_space should be a BicycleConfigurationSpace object.
        """
        self.config_space = config_space
        self.l = config_space.robot_length
        self.max_phi = config_space.high_lims[3]
        self.max_u1 = config_space.input_high_lims[0]
        self.max_u2 = config_space.input_high_lims[1]

    def plan_to_pose(self, start_state, goal_state, dt = 0.01, delta_t=2):
        """
        Plans to a specific pose in (x,y,theta,phi) coordinates.  You 
        may or may not have to convert the state to a v state with state2v()
        You may want to plan each component separately
        so that you can reset phi in case there's drift in phi.

        You will need to edit some or all of this function to take care of
        configuration

        Parameters
        ----------
        start_state: numpy.ndarray of shape (4,) [x, y, theta, phi]
        goal_state: numpy.ndarray of shape (4,) [x, y, theta, phi]
        dt : float
            how many seconds between trajectory timesteps
        delta_t : float
            how many seconds each trajectory segment should run for

        Returns
        -------
        :obj: Plan
            See configuration_space.Plan.
        """

        print "======= Planning with SinusoidPlanner ======="

        self.plan = None
        # This bit hasn't been exhaustively tested, so you might hit a singularity anyways
        x_s, y_s, theta_s, phi_s = start_state
        x_g, y_g, theta_g, phi_g = goal_state
        max_abs_angle = max(abs(theta_g), abs(theta_s))
        min_abs_angle = min(abs(theta_g), abs(theta_s))
        if (max_abs_angle > np.pi/2) and (min_abs_angle < np.pi/2):
            raise ValueError("You'll cause a singularity here. You should add something to this function to fix it")

        if abs(phi_s) > self.max_phi or abs(phi_g) > self.max_phi:
            raise ValueError("Either your start state or goal state exceeds steering angle bounds")

        # We can only change phi up to some threshold
        self.phi_dist = min(
            abs(phi_g - self.max_phi),
            abs(phi_g + self.max_phi)
        )

        
        y_path =        self.steer_y(
                            start_state, 
                            goal_state,
                            dt=dt,
                            delta_t=delta_t
                        )    
        phi_path =      self.steer_phi(
                            y_path.end_position(), 
                            goal_state,  
                            dt=dt, 
                            delta_t=delta_t
                        )
        alpha_path =    self.steer_alpha(
                            phi_path.end_position(), 
                            goal_state, 
                            dt=dt, 
                            delta_t=delta_t
                        )
        x_path =        self.steer_x(
                            alpha_path.end_position(), 
                            goal_state, 
                            dt=dt, 
                            delta_t=delta_t
                        )

        self.plan = Plan.chain_paths(y_path, phi_path, alpha_path, x_path)
        return self.plan

    def plot_execution(self):
        """
        Creates a plot of the planned path in the environment. Assumes that the 
        environment of the robot is in the x-y plane, and that the first two
        components in the state space are x and y position. Also assumes 
        plan_to_pose has been called on this instance already, so that self.graph
        is populated. If planning was successful, then self.plan will be populated 
        and it will be plotted as well.
        """
        ax = plt.subplot(1,1,1)
        if self.plan:
            plan_x = self.plan.positions[:, 0]
            plan_y = self.plan.positions[:, 1]
            ax.set(xlim=(0,5), ylim=(0,5))
            ax.plot(plan_x, plan_y, color='green')
            # print('Plan_State:{} \nReal_State:{}'.format(goal,self.plan.positions[-1]))
        plt.show()
        plt.plot(np.linspace(1,2,int(np.shape(self.plan.positions)[0])), self.plan.positions[:,2]-np.pi/2)
        plt.plot(np.linspace(1,2,int(np.shape(self.plan.positions)[0])), self.plan.positions[:,3])
        plt.legend('tp')
        plt.show()
        
    def steer_y(self, start_state, goal_state, t0=0, dt=0.01, delta_t=2):
        start_state_v = self.state2v(start_state)
        goal_state_v = self.state2v(goal_state)
        delta_y = goal_state_v[0] - start_state_v[0]
        v1 = delta_y / delta_t
        v2 = 0

        path, t =[], t0
        while t < t0 + delta_t:
            path.append([t,v1,v2])
            t += dt
        return self.v_path_to_u_path(path, start_state, dt)
    
    def steer_phi(self, start_state, goal_state, t0=0, dt=0.01, delta_t=2):
        start_state_v = self.state2v(start_state)
        goal_state_v = self.state2v(goal_state)
        delta_phi = goal_state_v[1] - start_state_v[1]

        v1 = 0
        v2 = delta_phi/delta_t

        path, t = [], t0
        while t < t0 + delta_t:
            path.append([t, v1, v2])
            t = t + dt
        return self.v_path_to_u_path(path, start_state, dt)

    def steer_alpha(self, start_state, goal_state, t0=0, dt=0.01, delta_t=2):
        start_state_v = self.state2v(start_state)
        goal_state_v = self.state2v(goal_state)
        delta_alpha = goal_state_v[2] - start_state_v[2]

        omega = 2*np.pi / delta_t

        a2 = min(1, self.phi_dist*omega)
        f = lambda phi: (1/self.l)*np.tan(phi) # This is from the car model
        phi_fn = lambda t: (a2/omega)*np.sin(omega*t) + start_state_v[1]
        integrand = lambda t: f(phi_fn(t))*np.sin(omega*t) # The integrand to find beta
        beta1 = (omega/np.pi) * quad(integrand, 0, delta_t)[0]

        a1 = (delta_alpha*omega)/(np.pi*beta1)
              
        v1 = lambda t: a1*np.sin(omega*(t))
        v2 = lambda t: a2*np.cos(omega*(t))

        path, t = [], t0
        while t < t0 + delta_t:
            path.append([t, v1(t-t0), v2(t-t0)])
            t = t + dt
        return self.v_path_to_u_path(path, start_state, dt)

    def steer_x(self, start_state, goal_state, t0=0, dt=0.01, delta_t=2):
        start_state_v = self.state2v(start_state)
        goal_state_v = self.state2v(goal_state)
        delta_y = goal_state_v[3] - start_state_v[3]

        omega = 2 * np.pi / delta_t

        max_a1 = self.max_u1 
        max_a2 = self.max_u2 

        def ode_function(x):
            # use ode to solve the problem
            # v1 = a1 sin(wt)
            # v2 = a2 cos(2wt)
            (a1,a2) = x
            def ode_f(z,t):
                #ode original form
                (x,y,theta,phi) = z
                inf_list = [np.inf,np.inf,np.inf,np.inf]
                if x == np.inf:
                    return inf_list
                if cos(theta) == 0 :
                    return inf_list
                u1 = a1 * sin(omega * t) / cos(theta)
                u2 = a2 * cos(2 * omega * t) 
                flag = True
                # flag = self.check_limit(u1,u2,phi)
                result = [np.cos(theta)*u1, np.sin(theta)*u1, 1/self.l*tan(phi)*u1, u2]
                return result if flag else inf_list
            z0, t= self.state2u(start_state), np.array([0, delta_t])
            sol = odeint(ode_f, z0, t, printmessg=False)
            y = sol[-1][1] # y is the final state
            return [y - goal_state_v[3],0]

        def find_root(ode_func):
            # find root for ode_func = 0
            guess_init = np.array([delta_y*2, delta_y*2])
            while not rospy.is_shutdown():
                sol = optimize.root(ode_func, guess_init, method='lm')
                if (sol.success):
                    break
                else:
                    guess_init[0] = max_a1 * np.random.rand()
                    guess_init[1] = max_a2 * np.random.rand()
                    print("Find root failed, because %s "%(sol.message))
                    print("change initial guess to (%f,%f) and try again..."%(guess_init[0],guess_init[1]))
            return sol.x


         # Generate path        
        while not rospy.is_shutdown():
            (a1,a2) = find_root(ode_function)
            print("In steer_y a1=%f a2=%f delta_y=%f"%(a1,a2,delta_y))
            v1 = lambda t: a1*np.sin(omega*(t))
            v2 = lambda t: a2*np.cos(2*omega*(t))

            path, t = [], t0
            while t < t0 + delta_t:
                path.append([t, v1(t-t0), v2(t-t0)])
                t = t + dt
            u_path = self.v_path_to_u_path(path, start_state, dt)

            if not self.limit_flag:
                break
            else:
                print("Generated y path reached the limit, reduce the max a1 %f a2 %f and try again..."%(max_a1,max_a2))
                coeff = 0.99
                max_a1 = max_a1 * coeff
                max_a2 = max_a2 * coeff
        return u_path

    def state2u(self,state):
        return np.array([state[0], state[1], state[2], state[3]])


    def check_limit(self,u1,u2,phi):
        return abs(u1) <= self.max_u1 and abs(u2) <= self.max_u2 and abs(phi) <= self.max_phi

    def state2v(self, state):
        """
        Takes a state in (x,y,theta,phi) coordinates and returns a state of (x,phi,alpha,y)

        Parameters
        ----------
        state : numpy.ndarray of shape (4,) [x, y, theta, phi]
            some state

        Returns
        -------
        4x1 :obj:`numpy.ndarray` 
            x, phi, alpha, y
        """
        x, y, theta, phi = state
        return np.array([y, phi, np.cos(theta), x])

    def v_path_to_u_path(self, path, start_state, dt):
        """
        convert a trajectory in v commands to u commands

        Parameters
        ----------
        path : :obj:`list` of (float, float, float)
            list of (time, v1, v2) commands
        start_state : numpy.ndarray of shape (4,) [x, y, theta, phi]
            starting state of this trajectory
        dt : float
            how many seconds between timesteps in the trajectory

        Returns
        -------
        :obj: Plan
            See configuration_space.Plan.
        """
        self.limit_flag = False
        def v2cmd(v1, v2, state):
            u1 = v1/np.sin(state[2])
            u2 = v2
            # if abs(u1) > self.max_u1:
            #     print("The limit is reached. u1 %f max %f"%(u1,self.max_u1))
            #     self.limit_flag = True
            # if abs(u2) > self.max_u2:
            #     print("The limit is reached. u2 %f max %f"%(u2,self.max_u2))
            #     self.limit_flag = True
            # phi = state[3]
            # if abs(phi) > self.max_phi:
            #     print("The limit is reached. phi %f max %f"%(phi,self.max_phi))
            #     self.limit_flag = True
            return [u1, u2]

        curr_state = start_state
        positions = []
        times = []
        open_loop_inputs = []
        for i, (t, v1, v2) in enumerate(path):
            cmd_u = v2cmd(v1, v2, curr_state)
            positions.append(curr_state)
            open_loop_inputs.append(cmd_u)
            times.append(t)

            x, y, theta, phi = curr_state
            linear_velocity, steering_rate = cmd_u
            curr_state = [
                x     + np.sin(theta)               * linear_velocity*dt,
                y     + np.cos(theta)               * linear_velocity*dt,
                theta - np.tan(phi) / float(self.l) * linear_velocity*dt,
                phi   + steering_rate*dt
            ]

        return Plan(np.array(times), np.array(positions), np.array(open_loop_inputs), dt=dt)

def main():
    """Use this function if you'd like to test without ROS.
    """
    global goal
    start = np.array([1, 1, np.pi/2, 0]) 
    goal = np.array([1, 1, 0, 0])
    # goal = np.array([3,1, np.pi/2, 0])

    xy_low = [0, 0]
    xy_high = [5, 5]
    phi_max = 0.6
    u1_max = 2
    u2_max = 3
    obstacles = []

    config = BicycleConfigurationSpace( xy_low + [-1000, -phi_max],
                                        xy_high + [1000, phi_max],
                                        [-u1_max, -u2_max],
                                        [u1_max, u2_max],
                                        obstacles,
                                        0.15)

    planner = SinusoidPlanner(config)
    plan = planner.plan_to_pose(start, goal, 0.01, 2.0)
    planner.plot_execution()

if __name__ == '__main__':
    main()