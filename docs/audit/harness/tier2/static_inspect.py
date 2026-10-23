"""Static, non-executing inspection of the committed pickles (stdlib only).
Walks opcodes with pickletools.genops; resolves STACK_GLOBAL from the preceding string pushes;
steps over joblib raw numpy buffers using the wrapper's declared dtype/shape. Never unpickles."""
import json, pickletools, struct, sys
SUSPICIOUS = {"os","posix","nt","subprocess","sys","builtins.eval","builtins.exec","builtins.compile",
              "builtins.getattr","builtins.__import__","builtins.open","importlib","socket","shutil","pickle","marshal","types","runpy","codecs"}

def walk(path):
    d = open(path, "rb").read()
    p, segs, globals_, opcount, raw = 0, 0, [], {}, []
    pending_wrapper = None
    while p < len(d):
        strs, ops, last = [], [], None
        try:
            for op, arg, pos in pickletools.genops(d[p:]):
                last = p + pos
                opcount[op.name] = opcount.get(op.name, 0) + 1
                if op.name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "BINUNICODE8"):
                    strs.append(arg)
                if op.name == "STACK_GLOBAL":
                    prev = [n for n, _ in ops[-4:]]
                    if prev[-1] == "MEMOIZE": prev = [n for n, _ in ops[-5:-1]]
                    globals_.append(f"{strs[-2]}.{strs[-1]}" if prev.count("SHORT_BINUNICODE") >= 2 else "memo-ref(previously seen global)")
                if op.name in ("GLOBAL", "INST"):
                    globals_.append(arg.replace(" ", "."))
                ops.append((op.name, arg))
                if op.name == "STOP":
                    break
            p = last + 1; segs += 1
            continue
        except Exception as e:
            err = str(e)
        # Not a pickle opcode here: expect a joblib raw buffer for the most recent wrapper in this segment.
        names = [a for n, a in ops if n == "SHORT_BINUNICODE"]
        if "shape" not in names or "dtype" not in names:
            return {"error": f"unparseable bytes at {p}: {err}", "ops_before": ops[-30:]}
        # shape and dtype from the last wrapper's state
        i = len(ops) - 1 - [n for n, _ in ops][::-1].index("SHORT_BINUNICODE") if False else None
        shape = None; dtype = None
        for k in range(len(ops) - 1, -1, -1):
            n, a = ops[k]
            if n == "SHORT_BINUNICODE" and a == "shape" and shape is None:
                ints = []
                for n2, a2 in ops[k+1:k+6]:
                    if n2 in ("BININT1", "BININT2", "BININT"): ints.append(a2)
                    if n2.startswith("TUPLE"): break
                shape = tuple(ints)
            if n == "SHORT_BINUNICODE" and a in ("f8", "f4", "i8", "i4") and dtype is None:
                dtype = a
            if n == "SHORT_BINUNICODE" and a == "shape" and dtype is not None:
                break
        # bytes consumed by genops before the failure: re-run to find the exact break offset
        q = p
        for op, arg, pos in pickletools.genops(d[p:]):
            q = p + pos + 1 + (len(op.code) - 1)
            break
        # find break offset precisely
        off = p
        try:
            for op, arg, pos in pickletools.genops(d[p:]):
                off = p + pos
        except Exception:
            pass
        # the failing opcode position is reported by genops in err; use it
        import re
        m = re.search(r"at position (\d+)", err)
        start = p + int(m.group(1))
        itemsize = {"f8": 8, "f4": 4, "i8": 8, "i4": 4}[dtype]
        n = 1
        for s in shape: n *= s
        padlen = d[start]
        data_start = start + 1 + padlen
        buf = d[data_start:data_start + n * itemsize]
        fmt = "<" + {"f8": "d", "f4": "f", "i8": "q", "i4": "i"}[dtype] * n
        raw.append({"dtype": dtype, "shape": shape, "padding": padlen, "offset": data_start,
                    "values": list(struct.unpack(fmt, buf))})
        # resume parsing after the buffer: the outer pickle continues (framing continues)
        p = data_start + n * itemsize
        # genops needs a fresh start; the remaining stream is a continuation without PROTO, which genops accepts
    sus = sorted({g for g in globals_ if g.split(".")[0] in SUSPICIOUS or g in SUSPICIOUS})
    return {"path": path, "bytes": len(d), "segments": segs, "globals": sorted(set(globals_)),
            "suspicious_globals": sus, "opcode_counts": opcount, "raw_numpy_buffers": raw}

out = {p: walk(p) for p in sys.argv[1:]}
print(json.dumps(out, indent=1, default=str))
