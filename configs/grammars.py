from configs.digest_config import CATEGORIES


def boolean_grammar() -> str:
    return 'root ::= "True" | "False"'


def category_grammar() -> str:
    cats = " | ".join(f'"{cat}"' for cat in CATEGORIES)
    return f"root ::= {cats}"


def significance_grammar() -> str:
    return "root ::= [0-9]"


def duplicate_groups_grammar() -> str:
    return r"""
root ::= array
array ::= "[" ws (group (ws "," ws group)*)? ws "]"
group ::= "[" ws (number (ws "," ws number)*)? ws "]"
number ::= [0-9]+
ws ::= [ \t\n]*
"""
