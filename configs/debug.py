from .envs import debug_env as env
from agents import PeUcrlAgt as Agt

config = {
    'env': env,
    'agt': Agt,
    'seed': None,
    'regulatory_constraints': {'prism_props': 'P>=0.5 [ X X n<=1 ]'},
    'max_n_time_steps': int(1e4),
    'dir': 'debug1/',
    'kwargs': {},
}

