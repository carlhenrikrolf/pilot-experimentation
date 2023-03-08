"""This script runs an exploring reinforcement learning agent in a specified environments. All specifications for the experiments should be given as a .json file. The path to that file is used as input to this script. Further the name of the output subdirectory in .data/ should be given as the second argument."""

# settings
render = False
#render = True

# import modules
import gymnasium as gym
from json import load, dumps
from os import system
from pprint import pprint
from sys import argv, stdout

# take arguments
agent_id = argv[1]
config_file_name = argv[2]
experiment_dir = argv[3]

# define output directory
if experiment_dir[-1] != '/':
    experiment_dir = experiment_dir + '/'
if experiment_dir[0] != '.':
    experiment_dir = '.' + experiment_dir
experiment_path = 'results/' + experiment_dir
system('mkdir ' + experiment_path)

# load and copy config file
config_file_path = 'config_files/' + config_file_name
config_file = open(config_file_path, 'r')
config = load(config_file)
config_file.close()
config['agent'] = agent_id
system('touch ' + experiment_path + config_file_name)
new_config_file = open(experiment_path + config_file_name, 'w')
new_config_file.write(dumps(config, indent=4))
new_config_file.close()
#system('cp ' + config_file_path + ' ' + experiment_path)
print('\nSTARTED TRAINING \n')
print('configurations:')
pprint(config)

# instantiate polarisation
if 'polarisation' in config_file_name:

    system('cd ..; pip3 install -e gym-cellular -q')
    import gym_cellular

    # instantiate environment
    env = gym.make(
        config["environment_version"],
        n_users=config["n_users"],
        n_user_states=config["n_user_states"],
        n_recommendations=config["n_recommendations"],
        n_moderators=config["n_moderators"],
        seed=config["environment_seed"],
    )

if 'peucrl' in agent_id:

    if 'minus_r_minus_shield' in agent_id:
        from agents import PeUcrlMinusRMinusShieldAgent as Agent
    elif 'minus_r_minus_experimentation' in agent_id:
        from agents import PeUcrlMinusRMinusExperimentationAgent as Agent
    elif 'minus_evi' in agent_id:
        from agents import PeUcrlMinusEviAgent as Agent
    elif 'minus_shield' in agent_id:
        from agents import PeUcrlMinusShieldAgent as Agent
    else:
        from agents import PeUcrlAgent as Agent

    # instantiate agent
    agt = Agent(
        confidence_level=config["confidence_level"],
        accuracy=config["accuracy"],
        n_cells=config["n_users"],
        n_intracellular_states=config["n_user_states"] * 2,
        cellular_encoding=env.cellular_encoding,
        n_intracellular_actions=config["n_recommendations"],
        cellular_decoding=env.cellular_decoding,
        reward_function=env.tabular_reward_function,
        cell_classes=config["cell_classes"],
        cell_labelling_function=config["cell_labelling_function"],
        regulatory_constraints=config["regulatory_constraints"],
        initial_policy=env.get_initial_policy(),
        seed=config["agent_seed"],
    )

# run agent
# initialise environment
state, info = env.reset()

# print
print("state:", state)
print("time step:", 0, "\n")

system('touch ' + experiment_path + 'data.csv')
data_file = open(experiment_path + 'data.csv', 'a')
data_file.write('time_step,reward,side_effects_incidence,ns_between_time_steps,ns_between_episodes')
data_file.close()

for time_step in range(config["max_time_steps"]):

    action = agt.sample_action(state)
    state, reward, terminated, truncated, info = env.step(action)
    agt.update(state, reward, info["side_effects"])

    data_file = open(experiment_path + 'data.csv', 'a')
    data_file.write('\n' + str(time_step + 1) + ',' + str(reward) + ',' + str(env.get_side_effects_incidence()) + ',' + str(agt.get_ns_between_time_steps()) + ',' + str(agt.get_ns_between_episodes()))
    data_file.close()

    if terminated or truncated:
        break

    # print
    if render:
        env.render()
    else:
        if time_step <= 0:
            print("action:", action, "\nstate:", state, "\nreward:", reward, "\nside effects:")
            pprint(info["side_effects"])
            print("time step:", time_step + 1, '\n\n', end='\r')
        elif time_step >= config["max_time_steps"] - 1:
            print("\n\naction:", action, "\nstate:", state, "\nreward:", reward, "\nside effects:")
            pprint(info["side_effects"])
            print("time step:", time_step + 1)
        else:
            stdout.write('\033[3K')
            print("time step:", time_step + 1, end='\r')

print('\nTRAINING ENDED\n')