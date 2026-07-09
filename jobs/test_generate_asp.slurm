#!/bin/bash
#SBATCH --job-name=test-asp-qwen-100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --gres=gpu:L40S:1
#SBATCH --qos=gpuResB_qos
#SBATCH --time=01:30:00
#SBATCH --partition=gpu_L40S
#SBATCH --output=logs/test-asp-qwen-100-%j.out
#SBATCH --error=logs/test-asp-qwen-100-%j.err

set -e

module load miniconda3/24.4.0
module load cuda/12.8

eval "$(conda shell.bash hook)"
conda activate prolog-asp

export HF_HOME=/hpc/groups/users-ai/mformenton/hf_cache
export TRANSFORMERS_CACHE=/hpc/groups/users-ai/mformenton/hf_cache
export HF_DATASETS_CACHE=/hpc/groups/users-ai/mformenton/hf_cache/datasets
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd /hpc/groups/users-ai/mformenton/Progetto-prolog-asp

echo "Nodo:"
hostname

echo "GPU:"
nvidia-smi

echo "Controllo Python:"
which python
python --version

echo "Test CUDA:"
python -c "import torch; print('CUDA disponibile:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')"

echo "Pulizia vecchi output limit100..."
rm -f data/asp_generated_limit100_test_hpc.jsonl
rm -f data/asp_checked_limit100_test_hpc.jsonl
rm -f outputs/asp_validation_report_limit100_test_hpc.txt

echo "Avvio generazione ASP limit 100..."

python3 -u scripts/generate_asp.py \
  --input data/prolog_for_asp.jsonl \
  --output data/asp_generated_limit100_test_hpc.jsonl \
  --prompt prompts/prolog_to_asp_prompt.txt \
  --limit 100 \
  --model Qwen/Qwen2.5-7B-Instruct \
  --max-new-tokens 512

echo "Generazione terminata."

echo "Avvio controllo ASP..."

python3 -u scripts/check_asp.py \
  --input data/asp_generated_limit100_test_hpc.jsonl \
  --output data/asp_checked_limit100_test_hpc.jsonl \
  --report outputs/asp_validation_report_limit100_test_hpc.txt \
  --limit 100 \
  --timeout 10

echo "Report finale:"
cat outputs/asp_validation_report_limit100_test_hpc.txt

echo "Fine job."
