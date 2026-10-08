"""Try the agent alone, with no board and no web server.

    python -m agent status
    python -m agent warm          (load the model once; the first answer after a restart is the slow one)
    python -m agent rule "turn the fan on when humidity is above 70"
    python -m agent eval eval/sentences.txt

The eval prints, for every test sentence, what the pattern reader made of it and (if Ollama is running)
what the model made of it, next to the expected outcome. A person decides which are correct: this script
only counts "made a rule the checker accepts", "refused" and "made a rule the checker caught".
"""
import json
import sys

from . import draft_rule, ollama, patterns, status
from .words import rule_parts
from rules import check_rule


def _show(res):
    if res["rule"] and not res["problems"]:
        return "RULE    " + rule_parts(res["rule"])["sentence"]
    if res["rule"]:
        return "CAUGHT  " + res["problems"][0]
    return "REFUSED " + (res["problems"][0] if res["problems"] else "")


def main(argv):
    if len(argv) >= 1 and argv[0] == "status":
        print(json.dumps(status(), indent=2))
    elif len(argv) >= 1 and argv[0] == "warm":
        from . import warm_up
        secs = warm_up()
        print("Model is not running or did not answer." if secs is None else "Model is warm. That took %s s." % secs)
    elif len(argv) >= 2 and argv[0] == "rule":
        res = draft_rule(" ".join(argv[1:]), [])
        print(json.dumps(res, indent=2))
    elif len(argv) >= 2 and argv[0] == "eval":
        model = ollama.status(max_age=0)["ready"]
        print("Model:", ollama.MODEL, "ready" if model else "NOT RUNNING (pattern reader only)")
        counts = {"pattern": {"RULE": 0, "CAUGHT": 0, "REFUSED": 0}, "model": {"RULE": 0, "CAUGHT": 0, "REFUSED": 0}}
        for line in open(argv[1], encoding="utf-8"):
            if "=>" not in line or line.lstrip().startswith("#"):
                continue
            sentence, expected = [x.strip() for x in line.split("=>", 1)]
            rule = patterns.parse(sentence)
            p = {"rule": rule, "problems": check_rule(rule, []) if rule else ["no pattern matched"]}
            ps = _show(p)
            counts["pattern"][ps.split()[0]] += 1
            print("\n" + sentence)
            print("  expected: " + expected)
            print("  pattern:  " + ps)
            if model:
                ms = _show(draft_rule(sentence, [])) if rule is None else ps + "  (pattern answered first)"
                counts["model"][ms.split()[0]] += 1
                print("  full:     " + ms)
        print("\nCounts (not a score: a person must mark which are correct)")
        for k in (("pattern", "model") if model else ("pattern",)):
            print("  %-8s rule %d, caught by checker %d, refused %d" % (
                k, counts[k]["RULE"], counts[k]["CAUGHT"], counts[k]["REFUSED"]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
