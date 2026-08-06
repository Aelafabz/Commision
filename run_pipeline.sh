source venv/bin/activate.fish

pyhton pip install -r ./requirements.txt

python scripts/run_pipeline.py --abr "/home/aelaf/Downloads/Telegram Desktop/Commision/raw files/july 1-9/july 1-9 abronal" --sot "/home/aelaf/Downloads/Telegram Desktop/Commision/raw files/july 1-9/july 1-9 sot" --out "/home/aelaf/Downloads/Telegram Desktop/Commision/raw files/july 1-9/july 1-9 analysis"

python scripts/category_merger.py --input "/home/aelaf/Downloads/Telegram Desktop/Commision/raw files/july 1-9/july 1-9 analysis/july 1-9 Perfect Matches.xlsx" --out "/home/aelaf/Downloads/Telegram Desktop/Commision/raw files/july 1-9/july 1-9 analysis/july 1-9 summary.xlsx" --dictioanry configs/dictionary.json