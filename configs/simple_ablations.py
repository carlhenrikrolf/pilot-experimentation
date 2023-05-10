from .envs import debug_env
from agents import PeUcrlAgt, NoPruningAgt, NoShieldAgt

config = {
    'env': [debug_env] * 9,
    'agt': [
        PeUcrlAgt,
        PeUcrlAgt,
        PeUcrlAgt,
        NoPruningAgt,
        NoPruningAgt,
        NoPruningAgt,
        NoShieldAgt,
        NoShieldAgt,
        NoShieldAgt,
    ],
    'seed': [
        0,
        1,
        2,
        0,
        1,
        2,
        0,
        1,
        2,
    ],
    'regulatory_constraints': ['true'] * 9,
    'max_n_time_steps': [100] * 9,
    'dir': [
        'peucrl0/',
        'peucrl1/',
        'peucrl2/',
        'nopruning0/',
        'nopruning1/',
        'nopruning2/',
        'noshield0/',
        'noshield1/',
        'noshield2/',
    ],
    'super_dir': 'simple_ablations/',
    'max_workers': 9,
}
