from agents.utils.space_transformations import cellular2tabular, tabular2cellular

from copy import deepcopy, copy
from itertools import chain
import math
import numpy as np
from os import system
from pprint import pprint
from psutil import Process
import random
import subprocess
from time import perf_counter_ns



class PeUcrlAgent:

    # initialise agent

    def __init__(
        self,
        confidence_level: float, # a parameter
        n_cells: int,
        n_intracellular_states: int,
        cellular_encoding, # states to N^n
        n_intracellular_actions: int,
        cellular_decoding, # N^n to actions # the (size, coding) pair is equivalent to the state/action space
        cell_classes: set,
        cell_labelling_function,
        regulatory_constraints,
        initial_policy: np.ndarray, # should be in a cellular encoding
        reward_function,
        seed=0,
    ):

        # check correctness of inputs
        assert 0 < confidence_level < 1

        # seed generators
        random.seed(seed)
        np.random.seed(seed)

        # point inputs to self
        self.confidence_level = confidence_level
        self.n_cells = n_cells
        self.n_intracellular_states = n_intracellular_states
        self.cellular_encoding = cellular_encoding
        self.n_intracellular_actions = n_intracellular_actions
        self.cellular_decoding = cellular_decoding
        self.cell_classes = cell_classes
        self.cell_labelling_function = cell_labelling_function
        self.regulatory_constraints = regulatory_constraints

        # compute additional parameters
        self.n_states = n_intracellular_states ** n_cells
        self.n_actions = n_intracellular_actions ** n_cells

        self.reward_function = np.zeros((self.n_states, self.n_actions))
        for flat_state in range(self.n_states):
            for flat_action in range(self.n_actions):
                self.reward_function[flat_state,flat_action] = reward_function(flat_state,flat_action)

        # initialise behaviour policy
        self.initial_policy = initial_policy
        self.behaviour_policy = deepcopy(self.initial_policy)
        self.target_policy = deepcopy(self.initial_policy)
        self.policy_update = np.zeros(self.n_cells, dtype=int)

        # initialise counts to 0 or 1
        self.time_step = 0
        self.current_episode_count = np.zeros((self.n_states, self.n_actions), dtype=int)
        self.previous_episodes_count = np.zeros((self.n_states, self.n_actions), dtype=int)
        self.cellular_current_episode_count = np.zeros((self.n_states, self.n_actions), dtype=int)
        self.cellular_previous_episodes_count = np.zeros((self.n_states, self.n_actions), dtype=int)
        self.intracellular_episode_count = np.zeros((self.n_intracellular_states, self.n_intracellular_actions), dtype=int)
        self.intracellular_sum = np.zeros((self.n_intracellular_states, self.n_intracellular_actions), dtype=int)
        self.intracellular_transition_sum = np.zeros((self.n_intracellular_states, self.n_intracellular_actions, self.n_intracellular_states), dtype=int)

        # initialise statistics
        self.side_effects_functions = [{'safe', 'unsafe'} for _ in range(n_intracellular_states)]
        self.intracellular_transition_estimates = np.zeros((self.n_intracellular_states, self.n_intracellular_actions, self.n_intracellular_states))
        self.intracellular_transition_indicators = np.ones((self.n_intracellular_states, self.n_intracellular_actions), dtype=int)
        self.transition_indicators = np.ones((self.n_states, self.n_actions), dtype=int)
        self.transition_estimates = np.zeros((self.n_states, self.n_actions, self.n_states))
        self.transition_errors = np.zeros((self.n_states, self.n_actions))

        # miscellaneous initialisations
        self.previous_state = None
        self.current_state = None
        self.action_sampled = False
        self.cpu_id = Process().cpu_num() # xprmntl

        # initialise prism
        self.prism_path = 'agents/prism_files/cpu_' + str(self.cpu_id) + '/'
        system('rm -r -f ' + self.prism_path + '; mkdir ' + self.prism_path)
        with open(self.prism_path + 'constraints.props', 'a') as props_file:
            props_file.write(self.regulatory_constraints)
        #self._write_prism_files()


    # subroutines the user must call to run the agent

    def sample_action(
        self,
        previous_state,
    ):

        """Sample an action from the behaviour policy and assign current state to previous state"""

        # assert that we put in the right state
        self.action_sampled = True

        # update state, action
        self.previous_state = self.cellular_encoding(previous_state)
        self.flat_previous_state = cellular2tabular(self.previous_state, self.n_intracellular_states, self.n_cells)
        self.cellular_action = deepcopy(self.behaviour_policy[:, self.flat_previous_state])
        self.action = self.cellular_decoding(self.cellular_action)
        self.flat_action = cellular2tabular(self.action, self.n_intracellular_actions, self.n_cells)
        return self.action


    def update(
        self,
        current_state,
        reward,
        side_effects=None,
    ):

        """Update the agent's policy and statistics"""

        assert self.action_sampled # avoid double updating

        self.start_time_step = perf_counter_ns()

        self.action_sampled = False
        self.current_state = self.cellular_encoding(deepcopy(current_state))
        self.flat_current_state = cellular2tabular(self.current_state, self.n_intracellular_states, self.n_cells)
        self.reward = reward
        if side_effects is None:
            print("Warning: No side effects providing, assuming silence")
            side_effects = np.array([['silent' for _ in range(self.n_cells)] for _ in range(self.n_cells)])
        self.side_effects = side_effects

        # on-policy
        self._update_estimates()
        self._side_effects_processing()
        new_pruning = self._action_pruning()
        self._update_current_episode_counts() # moved below. Correct?
        self.time_step += 1

        # off-policy
        next_action = deepcopy(self.behaviour_policy[:, self.flat_current_state])
        flat_next_action = cellular2tabular(next_action, self.n_intracellular_actions, self.n_cells)
        new_episode = (self.current_episode_count[self.flat_current_state, flat_next_action] >= max([1, self.previous_episodes_count[self.flat_current_state, flat_next_action]]))
        
        self.end_time_step = perf_counter_ns()
        self.start_episode = np.nan
        self.end_episode = np.nan
        
        if new_episode or new_pruning:

            self.start_episode = perf_counter_ns()

            self._update_errors()
            self._planner()
            self._pe_shield()

            if new_episode:
                self.previous_episodes_count += self.current_episode_count
                self.cellular_previous_episodes_count += self.cellular_current_episode_count

            self.end_episode = perf_counter_ns()

    
    # subroutines the user can call to collect data

    def get_ns_between_time_steps(self):
        return self.end_time_step - self.start_time_step
    
    def get_ns_between_episodes(self):
        return self.end_episode - self.start_episode
    
    
    # subroutines for procedure
    ## on-policy

    def _update_current_episode_counts(self):

        # intracellular
        for (intracellular_state, intracellular_action) in zip(self.previous_state, self.action):
            self.intracellular_episode_count[intracellular_state, intracellular_action] += 1

        # cellular
        for flat_previous_state in range(self.n_states):
            for flat_action in range(self.n_actions):
                self.cellular_current_episode_count[flat_previous_state, flat_action] = np.amin(
                    [
                        [
                            self.intracellular_episode_count[intracellular_state, intracellular_action] for intracellular_state in tabular2cellular(flat_previous_state, self.n_intracellular_states, self.n_cells)
                        ] for intracellular_action in tabular2cellular(flat_action, self.n_intracellular_actions, self.n_cells)
                    ]
                )

        # standard
        self.current_episode_count[self.flat_previous_state, self.flat_action] += 1
        

    def _side_effects_processing(self):

        for reporting_cell in range(self.n_cells):
            for reported_cell in range(self.n_cells):
                if self.side_effects[reporting_cell, reported_cell] == 'safe':
                    self.side_effects_functions[self.current_state[reported_cell]] -= {'unsafe'}
                elif self.side_effects[reporting_cell, reported_cell] == 'unsafe':
                    self.side_effects_functions[self.current_state[reported_cell]] -= {'safe'}


    def _action_pruning(self):

        if self.time_step == 0:
            self.intracellular_action_is_pruned = np.zeros((self.n_intracellular_states, self.n_intracellular_actions), dtype=int)
        
        new_pruning = False

        # basic case
        for cell in range(self.n_cells):
            if {'unsafe'} == self.side_effects_functions[self.current_state[cell]]:
                if self.intracellular_transition_indicators[self.previous_state[cell], self.action[cell]] == 1:
                    new_pruning = True
                self.intracellular_transition_indicators[self.previous_state[cell], self.action[cell]] = 0
        
        # corner cases
        if self.time_step == 0:
            self.path = [set() for _ in range(self.n_cells)]
        for cell in range(self.n_cells):
            n_unpruned_actions = np.sum(self.intracellular_transition_indicators[self.previous_state[cell], :])
            if n_unpruned_actions >= 2:
                self.path[cell] = set()
            elif n_unpruned_actions == 1:
                self.path[cell].add((self.previous_state[cell], self.action[cell]))
            if ({'unsafe'} == self.side_effects_functions[self.current_state[cell]]) or n_unpruned_actions == 0:
                for (intracellular_state, intracellular_action) in self.path[cell]:
                    if self.intracellular_transition_indicators[intracellular_state, intracellular_action] == 1:
                        new_pruning = True
                    self.intracellular_transition_indicators[intracellular_state, intracellular_action] = 0

        if new_pruning:
            for flat_state in range(self.n_states):
                for flat_action in range(self.n_actions):
                    for (intracellular_state, intracellular_action) in zip(
                                tabular2cellular(flat_state, self.n_intracellular_states, self.n_cells),
                                tabular2cellular(flat_action, self.n_intracellular_actions, self.n_cells)
                        ):
                        if self.intracellular_transition_indicators[intracellular_state, intracellular_action] == 0:
                            self.transition_indicators[flat_state, flat_action] = 0
                            break
        
        return new_pruning
    

    def _update_estimates(self):

         # update transition count
        for cell in range(self.n_cells):
            self.intracellular_sum[self.previous_state[cell], self.action[cell]] += 1
            self.intracellular_transition_sum[self.previous_state[cell], self.action[cell], self.current_state[cell]] += 1


    ## off-policy

    def _update_errors(self):

        # update estimates
        for intracellular_state in range(self.n_intracellular_states):
            for intracellular_action in range(self.n_intracellular_actions):
                self.intracellular_transition_estimates[intracellular_state, intracellular_action, :] = self.intracellular_transition_sum[intracellular_state, intracellular_action, :] / max([1, self.intracellular_sum[intracellular_state, intracellular_action]])

        for flat_state in range(self.n_states):
            for flat_action in range(self.n_actions):
                for flat_next_state in range(self.n_states):
                    self.transition_estimates[flat_state, flat_action, flat_next_state] = 1
                    for (intracellular_state, intracellular_action, intracellular_next_state) in zip(
                                tabular2cellular(flat_state, self.n_intracellular_states, self.n_cells),
                                tabular2cellular(flat_action, self.n_intracellular_actions, self.n_cells),
                                tabular2cellular(flat_next_state, self.n_intracellular_states, self.n_cells)
                        ):
                        self.transition_estimates[flat_state, flat_action, flat_next_state] *= self.intracellular_transition_estimates[intracellular_state, intracellular_action, intracellular_next_state]

        # update errors for state--action pairs
        for flat_state in range(self.n_states):
            for flat_action in range(self.n_actions):
                self.transition_errors[flat_state, flat_action] = np.sqrt(
                    (
                        14 * self.n_states * np.log(2 * self.n_actions * self.time_step / self.confidence_level)
                    ) / (
                        max([1, self.cellular_previous_episodes_count[flat_state, flat_action]])
                    )
                )


    def _inner_max(
        self,
        flat_state,
        flat_action,
        value,
    ):

        initial_sorted_states = list(np.argsort(value))
        max_set = list(np.argwhere(value == np.amax(value))[:,0])
        permuted_max_set = np.random.permutation(max_set)
        sorted_states = [*initial_sorted_states[:-len(max_set)], *permuted_max_set]
        max_p = np.zeros(self.n_states)
        for flat_next_state in range(self.n_states):
            max_p[flat_next_state] = self.transition_estimates[flat_state,flat_action,flat_next_state]
        max_p[sorted_states[-1]] = min(
            [
                1,
                self.transition_estimates[flat_state,flat_action,sorted_states[-1]] + self.transition_errors[flat_state, flat_action] / 2
            ]
        )
        l = 0
        while sum(max_p) > 1:
            max_p[sorted_states[l]] = max(
                [
                    0,
                    1 - sum([max_p[k] for k in chain(range(0, sorted_states[l]), range(sorted_states[l] + 1, self.n_states))])
                ]
            )
            l += 1
        return sum([ v * p for (v, p) in zip(value, max_p)])   


    def _extended_value_iteration(self):

        quality = np.zeros((self.n_states, self.n_actions))
        previous_value = np.zeros(self.n_states)
        current_value = np.zeros(self.n_states)
        stop = False
        while not stop:
            for flat_state in range(self.n_states):
                quality[flat_state, :] = [(self.reward_function[flat_state, flat_action] + self._inner_max(flat_state, flat_action, previous_value)) for flat_action in range(self.n_actions)]
                quality[flat_state, :] *= self.transition_indicators[flat_state, :]
                current_value[flat_state] = max(quality[flat_state, :])
            diff = [current_value[flat_state] - previous_value[flat_state] for flat_state in range(self.n_states)]
            stop = (max(diff) - min(diff) < 1/self.time_step)
            previous_value = current_value
        self.value_function = current_value # for testing purposes
        return quality
    

    def _planner(self):

        quality = self._extended_value_iteration()
        for flat_state in range(self.n_states):
            max_flat_action_set = list(np.argwhere(quality[flat_state, :] == np.amax(quality[flat_state, :]))[:,0])
            max_flat_action = int(random.sample(max_flat_action_set, 1)[0])
            max_action = tabular2cellular(max_flat_action, self.n_intracellular_actions, self.n_cells)
            self.target_policy[:, flat_state] = deepcopy(max_action)


    def _pe_shield(self):
        
        tmp_policy = deepcopy(self.behaviour_policy)
        cell_set = set(range(self.n_cells))
        while len(cell_set) >= 1:
            cell = self._cell_prioritisation(cell_set)
            cell_set -= {cell}
            tmp_policy[cell, :] = deepcopy(self.target_policy[cell, :])
            if self.policy_update[cell] == 0:
                initial_policy_is_updated = True
                self.policy_update[cell] = 1
            else:
                initial_policy_is_updated = False
            verified = self._verify(tmp_policy)
            if not verified:
                tmp_policy[cell, :] = deepcopy(self.behaviour_policy[cell, :])
                if initial_policy_is_updated:
                    self.policy_update[cell] = 0
        self.behaviour_policy = deepcopy(tmp_policy)
        

    def _cell_prioritisation(
        self,
        cell_set: set,
    ):

        cell = int(random.sample(cell_set, 1)[0])
        return cell
    

    def _verify(
        self,
        tmp_policy,
    ):

        self._write_model_file(tmp_policy)
        verified = self._call_prism(tmp_policy)

        return verified


    # using prism

    def _call_prism(
        self,
        tmp_policy,
    ):
        
        try:
            output = subprocess.check_output(['prism/prism/bin/prism', self.prism_path + 'model.prism', self.prism_path + 'constraints.props'])
        except subprocess.CalledProcessError as error:
            error = error.output
            error = error.decode()
            print(error)
            raise ValueError('Prism returned an error, see above.')
        output = output.decode()
        occurances = 0
        for line in output.splitlines():
            if 'Result:' in line:
                occurances += 1
                if 'true' in line:
                    verified = True
                elif 'false' in line:
                    verified = False
                else:
                    raise ValueError('Verification returned non-Boolean result.')
        if occurances != 1:
            raise ValueError('Verification returned ' + str(occurances) + ' results. Expected 1 Boolean result.')
        self.prism_output = output # for debugging purposes

        return verified
    
    def _write_model_file(
            self,
            tmp_policy,
            epsilon: float = 0.000000000000001,
        ):
        
        system('rm -fr ' + self.prism_path + 'model.prism')
        with open(self.prism_path + 'model.prism', 'a') as prism_file:

            prism_file.write('dtmc\n\n')

            for flat_state in range(self.n_states):
                for cell in range(self.n_cells):
                    C = 0
                    if self.policy_update[cell] == 1:
                        intracellular_states_set = tabular2cellular(flat_state, self.n_intracellular_states, self.n_cells)
                        for intracellular_state in intracellular_states_set:
                            if 'unsafe' in self.side_effects_functions[intracellular_state]:
                                C = 1
                                break
                    prism_file.write('const int C' + str(flat_state) + '_' + str(cell) + ' = ' + str(C) + ';\n')
            prism_file.write('\n')

            prism_file.write('module M\n\n')

            prism_file.write('s : [0..' + str(self.n_states) + '] init ' + str(self.flat_current_state) + ';\n')
            for cell in range(self.n_cells):
                prism_file.write('c_' + str(cell) + ' : [0..1] init C' + str(self.flat_current_state) + '_' + str(cell) + ';\n')
            prism_file.write('\n')

            for flat_state in range(self.n_states):
                prism_file.write('[] (s = ' + str(flat_state) + ') -> ')
                flat_action = cellular2tabular(tmp_policy[:, flat_state], self.n_intracellular_actions, self.n_cells)
                init_iter = True
                for next_flat_state in range(self.n_states):
                    lb = max(
                        [epsilon,
                         self.transition_estimates[flat_state, flat_action, next_flat_state] - self.transition_errors[flat_state, flat_action]]
                    )
                    ub = min(
                        [1-epsilon,
                         self.transition_estimates[flat_state, flat_action, next_flat_state] + self.transition_errors[flat_state, flat_action]]
                    )
                    if not init_iter:
                        prism_file.write(' + ')
                    prism_file.write('[' + str(lb) + ',' + str(ub) + "] : (s' = " + str(next_flat_state) + ')')
                    for cell in range(self.n_cells):
                        prism_file.write(' & (c_' + str(cell) + "' = C" + str(next_flat_state) + '_' + str(cell) + ')')
                    init_iter = False
                prism_file.write(';\n')
            prism_file.write('\n')

            prism_file.write('endmodule\n\n')

            prism_file.write("formula n = ")
            for cell in range(self.n_cells):
                prism_file.write("c_" + str(cell)+ " + ")
            prism_file.write("0;\n")
            for count, cell_class in enumerate(self.cell_classes):
                prism_file.write("formula n_" + cell_class + " = ")
                for cell in self.cell_labelling_function[count]:
                    prism_file.write("c_" + str(cell) + " + ")
                prism_file.write("0;\n")