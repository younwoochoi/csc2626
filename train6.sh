python train_offline.py --env flow --wandb --min_z_weight 1.0 --lag 10.0 --actor_lr 0.00003 --entropy "true"
python train_offline.py --env flow --wandb --min_z_weight 10.0 --lag 10.0 --actor_lr 0.00003 --entropy "false"
python train_offline.py --env flow --wandb --min_z_weight 10.0 --lag 10.0 --actor_lr 0.00003 --entropy "true"
python train_offline.py --env flow --wandb --min_z_weight 0.1 --lag -1 --actor_lr 0.00003 --entropy "false"