# CSC2626

The code is originally from the official repository for [Conservative Distributional Offline Reinforcement Learning](https://arxiv.org/abs/2107.06106).

## Installations
This repository requires Python (>3.7), Pytorch (version 1.6.0 or above), and installation of the [D4RL](https://github.com/rail-berkeley/d4rl) dataset. Mujoco license
is also required in order to run the D4RL experiments. Packages ```gym```, ```numpy```, and ```wandb``` (optionally) are also needed (any version should work). To get started, 
run the following commands to create a conda environment (assuming CUDA10.1):
```bash
conda create -n codac python=3.7
source activate codac
pip install numpy==1.19.0 tqdm
pip install torch==1.6.0 torchvision==0.7.0
pip install gym==1.7.2
pip install d4rl
 ```
## Experiments

### D4RL
Run `train1.sh` to `train8.sh`

For `train5.sh`, run:
```
python train_online.py --env AntObstacle-v0 --risk_prob 0.95 --risk_penalty 90 --algo codac --risk_type neutral --entropy true
python train_online.py --env riskymass --risk_prob 0.9 --risk_penalty 50.0 --algo codac --risk_type neutral --entropy true
```
before running `train5.sh`
