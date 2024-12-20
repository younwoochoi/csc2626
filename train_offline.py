
import argparse
import json 
import os
from d4rl.infos import REF_MIN_SCORE, REF_MAX_SCORE

import wandb
from sac import SAC, CQL, ReplayMemory
from models import ProbEnsemble, PredictEnv
from batch_utils import *
from mbrl_utils import *
from utils import *

from tqdm import tqdm

MODEL_FREE = ['sac', 'cql', 'codac']


def readParser():
    parser = argparse.ArgumentParser(description='BATCH_RL')
    parser.add_argument('--wandb', action='store_true')
    parser.add_argument('--env', default="hopper-medium-replay-v0",
        help='Mujoco Gym environment (default: hopper-medium-replay-v0)')
    parser.add_argument('--algo', default="codac")
    parser.add_argument('--version', type=int, default=2,
        help='CODAC policy update version')
    parser.add_argument('--tau_type', default="iqn")
    parser.add_argument('--dist_penalty_type', default="uniform")
    parser.add_argument('--entropy', default="false")
    parser.add_argument('--lag', type=float, default=10.0)
    parser.add_argument('--min_z_weight', type=float, default=10.0)
    parser.add_argument('--actor_lr', type=float, default=0.00003)
    parser.add_argument('--risk_type', default="neutral")
    parser.add_argument('--risk_param', default=0.1)
    # risk parameters for the environment
    parser.add_argument('--risk_prob', type=float, default=0.8)
    parser.add_argument('--risk_penalty', type=float, default=200)
    parser.add_argument('--use_bc', dest='use_bc', action='store_true')
    parser.set_defaults(use_bc=False)
    parser.add_argument('--pretrained', dest='pretrained', action='store_true')
    parser.set_defaults(pretrained=False)
    parser.add_argument('--penalty', type=float, default=1.0,
        help='reward penalty')
    parser.add_argument('--rollout_length', type=int, default=1, metavar='A',
                        help='rollout length')
    parser.add_argument('--seed', type=int, default=0, metavar='N',
        help='random seed (default: 0)')

    parser.add_argument('--replay_size', type=int, default=2000000, metavar='N',
                    help='size of replay buffer (default: 10000000)')
    parser.add_argument('--model_retain_epochs', type=int, default=5, metavar='A',
                    help='retain epochs')
    parser.add_argument('--model_train_freq', type=int, default=1000, metavar='A',
                    help='frequency of training')
    parser.add_argument('--rollout_batch_size', type=int, default=50000, metavar='A',
                    help='rollout number M')
    parser.add_argument('--epoch_length', type=int, default=1000, metavar='A',
                    help='steps per epoch')
    parser.add_argument('--num_epoch', type=int, default=1000, metavar='A',
                    help='total number of epochs')
    parser.add_argument('--dataset_epoch', type=int, default=100)
    parser.add_argument('--real_ratio', type=float, default=0.05, metavar='A',
                    help='ratio of env samples / model samples')
    parser.add_argument('--init_exploration_steps', type=int, default=5000, metavar='A',
                    help='initial random exploration steps')
    parser.add_argument('--train_every_n_steps', type=int, default=1, metavar='A',
                    help='frequency of training policy')
    parser.add_argument('--num_train_repeat', type=int, default=1, metavar='A',
                    help='times to training policy per step')
    parser.add_argument('--eval_n_episodes', type=int, default=1, metavar='A',
                    help='number of evaluation episodes')
    parser.add_argument('--max_train_repeat_per_step', type=int, default=5, metavar='A',
                    help='max training times per step')
    parser.add_argument('--policy_train_batch_size', type=int, default=256, metavar='A',
                    help='batch size for training policy')
    parser.add_argument('--model_type', default='pytorch', metavar='A',
                    help='predict model -- pytorch or tensorflow')
    parser.add_argument('--pre_trained', type=bool, default=False,
                    help='flag for whether dynamics model pre-trained')
    parser.add_argument('--device', default='cuda:0',
                    help='run on CUDA (default: True)')
    return parser.parse_args()


def train(args, env_sampler, predict_env, agent, env_pool, model_pool):
    total_step = 0
    reward_sum = 0
    rollout_length = args.rollout_length

    save_interval = int(args.num_epoch / 1)
    eval_interval = int(args.num_epoch / 100)
    for epoch_step in tqdm(range(args.num_epoch)):
        
        if (epoch_step+1) % save_interval == 0:
            agent_path = f'saved_policies/{args.env}/{args.dataset}/{args.run_name}-epoch{epoch_step+1}'
            # agent_path = f'saved_policies/{args.env}-{args.run_name}-epoch{epoch_step+1}'
            agent.save_model(agent_path)

        start_step = total_step
        train_policy_steps = 0
        for i in range(args.epoch_length):
            cur_step = total_step - start_step

            # epoch_length = 1000, min_pool_size = 1000
            if cur_step >= args.epoch_length:
                break

            if cur_step % args.model_train_freq == 0 and args.real_ratio < 1.0:
                assert(args.algo not in MODEL_FREE)
                rollout_model(args, predict_env, agent, model_pool, env_pool, rollout_length)

            # train policy
            train_policy_steps += train_policy_repeats(args, total_step, train_policy_steps, cur_step, env_pool, model_pool, agent)
            total_step += 1
        
        if epoch_step % eval_interval == 0:
            
            rewards = [evaluate_policy(args, env_sampler, agent, args.epoch_length) for _ in range(args.eval_n_episodes)]
            rewards = np.array(rewards)
            rewards_avg = np.mean(rewards, axis=0)
            rewards_std = np.std(rewards, axis=0)
            sorted_rewards = np.sort(rewards)
            cvar = sorted_rewards[:int(0.1 * sorted_rewards.shape[0])].mean()
            if args.d4rl:
                env_name = args.env
                min_score = REF_MIN_SCORE[env_name]
                max_score = REF_MAX_SCORE[env_name]
                normalized_score = 100 * (rewards_avg - min_score) / (max_score - min_score)
            else:
                normalized_score = rewards_avg

            print("")
            print(f'Epoch {epoch_step} Eval_Reward {rewards_avg:.2f} Eval_Cvar {cvar:.2f} Eval_Std {rewards_std:.2f} Normalized_Score {normalized_score:.2f}')
            if args.wandb:
                wandb.log({'epoch': epoch_step,
                           'eval_reward': rewards_avg,
                           'normalized_score': normalized_score,
                           'eval_cvar0.1': cvar,
                           'reward_std': rewards_std})


def main():
    args = readParser()

    if args.env == 'riskymass' or args.env == 'AntObstacle-v0':
        run_name = f"offline-{args.risk_prob}-{args.risk_penalty}-{args.algo}-{args.dist_penalty_type}-{args.risk_type}{args.risk_param}-E{args.entropy}-{args.seed}"
        if 'dsac' in args.algo:
            run_name = f"offline-{args.risk_prob}-{args.risk_penalty}-{args.algo}-{args.dist_penalty_type}-{args.risk_type}{args.risk_param}-Z{args.min_z_weight}-L{args.lag}-E{args.entropy}-{args.seed}"
    else:
        run_name = f"offline-{args.algo}-{args.dist_penalty_type}-{args.risk_type}{args.risk_param}-{args.seed}"
        if 'dsac' in args.algo:
            run_name = f"offline-{args.algo}-{args.dist_penalty_type}-{args.risk_type}{args.risk_param}-Z{args.min_z_weight}-L{args.lag}-E{args.entropy}-{args.seed}"

    # Initial environment
    
    args.num_epoch = 100
    args.entropy_tuning = False

    # Load config from config file
    try:
        config = json.load(open('configs/d4rl_configs.json', 'r'))[args.env]
        args.min_z_weight = config['min_z_weight']
        args.lag = config['lag']
        args.actor_lr = config['actor_lr']
        args.entropy = config['entropy']
    except:
        pass 

    if args.entropy == "true":
        args.entropy_tuning = True
    args.adapt = False
    args.d4rl = False
    if args.env == "riskymass":
        args.entropy_tuning = False
        from env.risky_pointmass import PointMass
        env = PointMass(risk_prob=args.risk_prob, risk_penalty=args.risk_penalty)
        args.epoch_length = 100
        args.num_epoch = 100
        args.eval_n_episodes = 100
        dataset_name = f'online-{args.risk_prob}-{args.risk_penalty}-codac-neutral0.1-Etrue-0-epoch{args.dataset_epoch}'
        print(f'Dataset used: {dataset_name}')
        dataset = np.load(f'dataset/{args.env}/{dataset_name}.npy', allow_pickle=True).item()
        args.dataset = dataset_name
    elif args.env == 'AntObstacle-v0':
        import env
        env = gym.make(args.env)
        env.set_risk(args.risk_prob, args.risk_penalty)
        args.epoch_length = 200
        args.num_epoch = 5000
        args.eval_n_episodes = 100
        dataset_name = f'online-{args.risk_prob}-{args.risk_penalty}-codac-neutral0.1-Etrue-0-epoch{args.dataset_epoch}'
        print(f'Dataset used: {dataset_name}')
        dataset = np.load(f'dataset/{args.env}/{dataset_name}.npy', allow_pickle=True).item()
        args.dataset = dataset_name
    elif args.env == 'kitchen':
        dataset_name = 'kitchen'
        import h5py
        args.dataset = dataset_name
        f = h5py.File('kitchen_microwave_kettle_light_slider-v0.hdf5', 'r')
        dataset = {}
        dataset['observations'] = np.array(f['observations'][:])
        dataset['actions'] = np.array(f['actions'][:])
        dataset['rewards'] = np.array(f['rewards'][:])
        dataset['terminals'] = np.array(f['terminals'][:])
        dataset['timeouts'] = np.array(f['timeouts'][:])
        
        from d4rl.kitchen import KitchenMicrowaveKettleLightSliderV0
        env = KitchenMicrowaveKettleLightSliderV0()
        dataset = d4rl.qlearning_dataset(env, dataset)
    elif args.env == "flow":
        args.entropy_tuning = False
        from env.flowenv import FlowMergeEnv
        env = FlowMergeEnv()
        args.epoch_length = 100
        args.num_epoch = 100
        args.eval_n_episodes = 100
        dataset_name = 'flow'
        args.dataset = dataset_name
        import h5py
        f = h5py.File('flow-merge-v0-random.hdf5', 'r')
        dataset = {}
        dataset['observations'] = np.array(f['observations'][:])
        dataset['actions'] = np.array(f['actions'][:])
        dataset['rewards'] = np.array(f['rewards'][:])
        dataset['terminals'] = np.array(f['terminals'][:])
        dataset['timeouts'] = np.array(f['timeouts'][:])
        dataset = d4rl.qlearning_dataset(env, dataset)
        
        import sys
        sys.path.append('flow')
        from flow.envs import MergePOEnv
        from flow.networks import MergeNetwork
        from copy import deepcopy
        from flow.core.params import SumoParams, EnvParams, InitialConfig, NetParams, InFlows, SumoCarFollowingParams
        from flow.networks.merge import ADDITIONAL_NET_PARAMS
        from flow.core.params import VehicleParams
        from flow.controllers import SimCarFollowingController, RLController
        # time horizon of a single rollout
        HORIZON = 750
        # inflow rate at the highway
        FLOW_RATE = 2000
        # percent of autonomous vehicles
        RL_PENETRATION = 0.1
        # num_rl term (see ADDITIONAL_ENV_PARAMs)
        NUM_RL = 5

        # We consider a highway network with an upstream merging lane producing
        # shockwaves
        additional_net_params = deepcopy(ADDITIONAL_NET_PARAMS)
        additional_net_params["merge_lanes"] = 1
        additional_net_params["highway_lanes"] = 1
        additional_net_params["pre_merge_length"] = 500

        # RL vehicles constitute 5% of the total number of vehicles
        vehicles = VehicleParams()
        vehicles.add(
            veh_id="human",
            acceleration_controller=(SimCarFollowingController, {}),
            car_following_params=SumoCarFollowingParams(
                speed_mode=9,
            ),
            num_vehicles=5)
        vehicles.add(
            veh_id="rl",
            acceleration_controller=(RLController, {}),
            car_following_params=SumoCarFollowingParams(
                speed_mode=9,
            ),
            num_vehicles=0)

        # Vehicles are introduced from both sides of merge, with RL vehicles entering
        # from the highway portion as well
        inflow = InFlows()
        inflow.add(
            veh_type="human",
            edge="inflow_highway",
            vehs_per_hour=(1 - RL_PENETRATION) * FLOW_RATE,
            depart_lane="free",
            depart_speed=10)
        inflow.add(
            veh_type="rl",
            edge="inflow_highway",
            vehs_per_hour=RL_PENETRATION * FLOW_RATE,
            depart_lane="free",
            depart_speed=10)
        inflow.add(
            veh_type="human",
            edge="inflow_merge",
            vehs_per_hour=100,
            depart_lane="free",
            depart_speed=7.5)

    
        # name of the experiment
        exp_tag="merge_0"

        # name of the flow environment the experiment is running on
        env_name=MergePOEnv

        # name of the network class the experiment is running on
        network=MergeNetwork

        # simulator that is used by the experiment
        simulator='traci'

        # sumo-related parameters (see flow.core.params.SumoParams)
        sim=SumoParams(restart_instance=True,sim_step=0.5,render=False,save_render=True)

        # environment related parameters (see flow.core.params.EnvParams)
        env=EnvParams(horizon=HORIZON,sims_per_step=2,warmup_steps=0,additional_params={"max_accel": 1.5,"max_decel": 1.5,"target_velocity": 20,"num_rl": NUM_RL,},)

        # network-related parameters (see flow.core.params.NetParams and the
        # network's documentation or ADDITIONAL_NET_PARAMS component)
        net=NetParams(inflows=inflow,additional_params=additional_net_params,)

        # vehicles to be placed in the network at the start of a rollout (see
        # flow.core.params.VehicleParams)
        veh=vehicles

        # parameters specifying the positioning of vehicles upon initialization/
        # reset (see flow.core.params.InitialConfig)
        initial=InitialConfig()
        
        # network = MergeNetwork('merge', vehicles, net, initial)
        env = FlowMergeEnv()

    else:
        env_type, dataset_type = args.env.split('-')[0], args.env.split('-')[-2]
        env, dataset = load_d4rl_dataset(args.env)
        # dict_keys(['observations', 'actions', 'next_observations', 'rewards', 'terminals'])
        args.dataset = args.env
        args.d4rl = True

    os.makedirs(f'saved_policies/{args.env}/{args.dataset}', exist_ok=True)

    # only use batch data for model-free methods
    if args.algo in MODEL_FREE:
        args.real_ratio = 1.0

    args.run_name = run_name

    # Set random seed
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    env.seed(args.seed)
    env.action_space.seed(args.seed)

    if args.algo == 'sac':
        agent = SAC(env.observation_space.shape[0], env.action_space,
                    automatic_entropy_tuning=args.entropy_tuning)
    elif args.algo == 'codac':
        from distributional.codac import CODAC
        agent = CODAC(env.observation_space.shape[0], env.action_space,
                      version=args.version,
                      tau_type=args.tau_type, use_bc=args.use_bc,
                      min_z_weight=args.min_z_weight, actor_lr=args.actor_lr,
                      risk_type=args.risk_type, risk_param=args.risk_param,
                      dist_penalty_type=args.dist_penalty_type,
                      lagrange_thresh=args.lag,
                      use_automatic_entropy_tuning=args.entropy_tuning,
                      device=args.device)
    elif args.algo == 'cql':
        from sac.cql import CQL
        args.dist_penalty_type = 'none'
        agent = CQL(env.observation_space.shape[0], env.action_space,
                    min_q_weight=args.min_z_weight, policy_lr=args.actor_lr,
                    lagrange_thresh=args.lag,
                    automatic_entropy_tuning=args.entropy_tuning,
                    device=args.device)

    # initial ensemble model
    state_size = np.prod(env.observation_space.shape)
    action_size = np.prod(env.action_space.shape)

    # initialize dynamics model
    env_model = ProbEnsemble(state_size, action_size, reward_size=1)
    env_model.to(args.device)

    # Imaginary Environment
    predict_env = PredictEnv(env_model, args.env)

    # Sampler Environment
    env_sampler = EnvSampler(env, max_path_length=args.epoch_length)

    # Initial replay buffer for env
    if dataset is not None:
        n = dataset['observations'].shape[0]
        print(f"dataset name: {args.dataset}")
        print(f"{args.env} dataset size {n}")
        env_pool = ReplayMemory(n)
        for i in range(n):
            state, action, reward, next_state, done = dataset['observations'][i], dataset['actions'][i], dataset['rewards'][
                i], dataset['next_observations'][i], dataset['terminals'][i]
            env_pool.push(state, action, reward, next_state, done)
    else:
        env_pool = ReplayMemory(args.init_exploration_steps)
        exploration_before_start(args, env_sampler, env_pool, agent,
                                 init_exploration_steps=args.init_exploration_steps)

    # Initial pool for model
    rollouts_per_epoch = args.rollout_batch_size * args.epoch_length / args.model_train_freq
    model_steps_per_epoch = int(args.rollout_length * rollouts_per_epoch)
    new_pool_size = args.model_retain_epochs * model_steps_per_epoch
    model_pool = ReplayMemory(new_pool_size)
    
    if args.wandb:
        wandb.init(project='codac_final2',
                   group=args.env,
                   name=args.env+run_name,
                   config=args)

    # Train
    train(args, env_sampler, predict_env, agent, env_pool, model_pool)


if __name__ == '__main__':
    main()