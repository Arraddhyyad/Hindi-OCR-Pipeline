# Data (not stored in git)

Generated pages are large (about 1 GB for the benchmark set), so they stay out of the repo. Keep them in a shared folder and put a copy here, in this layout:

    data/benchmark_v1/
      setA_standard/dataset/{train,val,test}/doc_*.png, doc_*_target.png, doc_*.json
      setB_hard/dataset/...
      setC_ladder/dataset/...

Shared folder link: (add the Drive link here)

How benchmark_v1 was made (same code as this repo, nothing else used):
- setA_standard: `python main.py generate --config config/hindi_sale_deed_v2.yaml --count 100 --verify`
- setB_hard: the hard config with every page forced to be a hard page (`config/hindi_sale_deed_v2_hard_all.yaml`), 40 pages
- setC_ladder: 5 pages, each written at damage stages 1 to 5 (`config/hindi_sale_deed_v2_ladder.yaml`)
