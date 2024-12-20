

# Risky mass offline
python train_offline.py --env riskymass --risk_prob 0.9 --risk_penalty 50 --algo codac --risk_type cvar --entropy true --dist_penalty_type uniform --min_z_weight 0.1 --lag 10.0 --dataset_epoch 100 --seed 0