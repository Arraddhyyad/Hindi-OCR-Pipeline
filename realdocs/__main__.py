"""python -m realdocs <step> --work real_work

  fetch      search + download open-licensed Hindi documents  -> sources.csv, raw/
  prepare    render pages, drop blanks                          -> images/, pages.csv, contact_sheet.jpg
  pick       choose N pages across sources                      -> selected.csv
  annotate   automatic draft labels                             -> labels/*.json
  ls-export  files to load into Label Studio                    -> ls_tasks.json, ls_config.xml
  ls-import  read corrected annotations back
  build      write dataset/ for `python -m benchmark.run --set R=real_work/dataset`"""
import argparse

from . import annotate as ann, prepare as prep, review, sources

DEFAULT_QUERIES = ["sale deed", "registry deed", "court order", "gazette notification", "land record",
                   "बैनामा", "विक्रय पत्र", "अदालत आदेश", "राजपत्र", "भूमि अभिलेख"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["fetch", "prepare", "pick", "annotate", "ls-export", "ls-import", "build"])
    ap.add_argument("--work", default="real_work")
    ap.add_argument("--query", action="append", help="repeat for several; default is a built-in list")
    ap.add_argument("--max-items", type=int, default=40)
    ap.add_argument("--per-item", type=int, default=3, help="prepare: pages taken from each PDF")
    ap.add_argument("-n", type=int, default=50, help="pick: how many pages")
    ap.add_argument("--drop", nargs="*", default=[], help="pick: page ids rejected on the contact sheet")
    ap.add_argument("--lang", default="hin+eng")
    ap.add_argument("--export", help="ls-import: the JSON exported from Label Studio")
    ap.add_argument("--url-prefix", default="/data/local-files/?d=", help="ls-export")
    ap.add_argument("--include-draft", action="store_true", help="build: include unreviewed pages (dry run only)")
    a = ap.parse_args(argv)
    if a.step == "fetch":
        print(sources.fetch(a.query or DEFAULT_QUERIES, a.work, a.max_items))
    elif a.step == "prepare":
        print(prep.prepare(a.work, a.per_item), "pages ->", a.work + "/contact_sheet.jpg")
    elif a.step == "pick":
        print(len(prep.pick(a.work, a.n, a.drop)), "pages selected")
    elif a.step == "annotate":
        print(ann.annotate(a.work, a.lang), "pages drafted")
    elif a.step == "ls-export":
        print(review.export_tasks(a.work, a.url_prefix), "tasks -> ls_tasks.json, ls_config.xml")
    elif a.step == "ls-import":
        print(review.import_export(a.work, a.export), "pages reviewed")
    elif a.step == "build":
        print(review.build_dataset(a.work, include_draft=a.include_draft), "pages in dataset")


if __name__ == "__main__":
    main()
