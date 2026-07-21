#!/usr/bin/env python3
"""Both-direction config drift: the reference pages vs the product source.

Usage: check_config_drift.py <product-root>
  <product-root> contains ControlPlane-API/, Gateway/, Agent/ checkouts.

Derives, per component, the authoritative key set:
  CP     — @ConfigurationProperties classes (prefix + fields, camelCase→kebab,
           nested config classes recursed) plus every ${sessionlayer.*} and
           @ConditionalOnProperty sessionlayer.* reference in src/main/java.
  Gateway— the serde field tree of gateway-core/src/config.rs (nested structs
           dotted; the tagged coordination enum contributes its tag + variant
           fields).
  Agent  — every #[arg(long)] clap field in src/main.rs (--kebab-case), plus
           the numeric exit-code contract from exit_status/EXIT_VERIFY_REFUSED.

The documented set is read from the reference pages' key tables (first column
of tables whose header starts with Key / Flag / Exit code), then diffed both
ways: a documented key that does not exist fails, an existing key that is not
documented fails.
"""
import pathlib
import re
import sys


def kebab(name):
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", name).lower()


def doc_table_firsts(md_path, header_names):
    """First-column backticked values of tables whose header first cell matches."""
    values = set()
    lines = pathlib.Path(md_path).read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|", lines[i + 1]):
            header = lines[i].strip("|").split("|")[0].strip().lower()
            in_scope = any(header.startswith(h) for h in header_names)
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                if in_scope:
                    m = re.match(r"^\|\s*`([^`]+)`", lines[i])
                    if m:
                        values.add(m.group(1))
                i += 1
        else:
            i += 1
    return values


# --- Control Plane ---------------------------------------------------------

def java_class_bodies(text):
    """Map class name -> body text, via brace matching from each declaration."""
    bodies = {}
    # Line-anchored so 'class' inside javadoc prose never matches.
    for m in re.finditer(r"^[\t ]*(?:(?:public|protected|private|static|final|abstract)\s+)*class\s+([A-Za-z0-9_]+)[^{\n]*\{", text, re.M):
        depth, start = 1, m.end()
        i = start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        bodies[m.group(1)] = text[start:i - 1]
    return bodies


FIELD_RE = re.compile(
    r"^\s*private\s+(?:final\s+)?([A-Za-z][A-Za-z0-9_.<>, ]*?)\s+([a-zA-Z][a-zA-Z0-9_]*)\s*(?:=[^;]*)?;",
    re.M,
)


def cp_properties_keys(java_file):
    text = java_file.read_text(encoding="utf-8")
    m = re.search(r'@ConfigurationProperties\(prefix\s*=\s*"([^"]+)"\)', text)
    if not m:
        return set()
    prefix = m.group(1)
    bodies = java_class_bodies(text)
    outer = re.search(r"public\s+class\s+([A-Za-z0-9_]+)", text).group(1)

    def own_fields(cls):
        # Fields of cls only: strip nested class bodies so inner fields don't leak.
        body = bodies[cls]
        for other, other_body in bodies.items():
            if other != cls and other_body in body:
                body = body.replace(other_body, "")
        for typ, name in FIELD_RE.findall(body):
            if "static" not in typ:
                yield typ.split("<")[0].strip(), name

    keys = set()

    def walk(cls, at):
        for typ, name in own_fields(cls):
            if typ in bodies and typ != cls:
                walk(typ, at + "." + kebab(name))
            else:
                keys.add(at + "." + kebab(name))

    walk(outer, prefix)
    return keys


def cp_keys(cp_root):
    keys = set()
    src = cp_root / "src/main/java"
    for f in src.rglob("*Properties.java"):
        keys |= cp_properties_keys(f)
    for f in src.rglob("*.java"):
        text = f.read_text(encoding="utf-8")
        keys |= set(re.findall(r"\$\{(sessionlayer\.[a-z0-9.-]+)", text))
        keys |= set(re.findall(r'@ConditionalOnProperty\(value\s*=\s*"(sessionlayer\.[a-z0-9.-]+)"', text))
    return keys


# --- Gateway ---------------------------------------------------------------

def gateway_keys(gw_root):
    text = (gw_root / "gateway-core/src/config.rs").read_text(encoding="utf-8")
    structs = {}
    for m in re.finditer(r"pub struct ([A-Za-z0-9_]+) \{(.*?)\n\}", text, re.S):
        structs[m.group(1)] = re.findall(r"^\s*pub ([a-z0-9_]+): ([A-Za-z0-9_:<>]+),", m.group(2), re.M)
    tagged = {}
    for m in re.finditer(r'#\[serde\(tag = "([a-z_]+)"[^)]*\)\]\s*pub enum ([A-Za-z0-9_]+) \{(.*?)\n\}', text, re.S):
        fields = set(re.findall(r"^\s{8}([a-z0-9_]+):", m.group(3), re.M))
        tagged[m.group(2)] = (m.group(1), fields)

    keys = set()

    def walk(struct, at):
        for name, typ in structs[struct]:
            base = typ.removeprefix("Option<").removesuffix(">") if typ.startswith("Option<") else typ
            path = f"{at}.{name}" if at else name
            if base in structs:
                walk(base, path)
            elif base in tagged:
                tag, fields = tagged[base]
                keys.add(f"{path}.{tag}")
                keys.update(f"{path}.{f}" for f in fields)
            else:
                keys.add(path)

    walk("GatewayConfig", "")
    return keys


# --- Agent -----------------------------------------------------------------

def agent_flags_and_exits(agent_root):
    text = (agent_root / "src/main.rs").read_text(encoding="utf-8")
    flags = set()
    # A clap long flag is a struct field whose preceding attribute contains
    # #[arg(... long ...)]; clap derives --kebab-case from the field name.
    # Non-greedy to the first `)]` — bracket lists like requires_all close
    # before it, so the shortcut holds for this file.
    for m in re.finditer(r"#\[arg\((.*?)\)\]\s*(?:pub\s+)?([a-z0-9_]+):", text, re.S):
        if re.search(r"\blong\b", m.group(1)):
            flags.add("--" + m.group(2).replace("_", "-"))
    exits = set(re.findall(r"=>\s*(\d+)\s*,?\s*\n", text[text.find("fn exit_status"):text.find("fn exit_status") + 400]))
    m = re.search(r"const EXIT_VERIFY_REFUSED: u8 = (\d+)", text)
    if m:
        exits.add(m.group(1))
    exits.add("0")
    return flags, exits


# --- diff ------------------------------------------------------------------

def diff(label, derived, documented):
    undocumented = sorted(derived - documented)
    nonexistent = sorted(documented - derived)
    for k in undocumented:
        print(f"{label}: UNDOCUMENTED (in source, not in doc): {k}")
    for k in nonexistent:
        print(f"{label}: NONEXISTENT (in doc, not in source): {k}")
    if not derived:
        print(f"{label}: FAIL — derived key set is empty (extractor or checkout broke)")
        return 1
    if undocumented or nonexistent:
        print(f"{label}: FAIL — {len(undocumented)} undocumented, {len(nonexistent)} nonexistent")
        return 1
    print(f"{label}: OK — {len(derived)} keys match both ways")
    return 0


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    product = pathlib.Path(sys.argv[1])
    rc = 0

    derived = cp_keys(product / "ControlPlane-API")
    documented = {k for k in doc_table_firsts("docs/reference/config-control-plane.md", ["key"])
                  if k.startswith("sessionlayer.")}
    rc |= diff("control-plane", derived, documented)

    derived = gateway_keys(product / "Gateway")
    rc |= diff("gateway", derived, doc_table_firsts("docs/reference/config-gateway.md", ["key"]))

    flags, exits = agent_flags_and_exits(product / "Agent")
    documented = {f for f in doc_table_firsts("docs/reference/config-agent.md", ["flag"]) if f.startswith("--")}
    rc |= diff("agent-flags", flags, documented)
    rc |= diff("agent-exit-codes", exits, doc_table_firsts("docs/reference/config-agent.md", ["exit code"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
