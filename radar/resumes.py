"""Load Abi's resume variants (resumes/tex/<role>.tex) as plain text for matching."""
import re
from pathlib import Path

TEX_DIR = Path(__file__).parent.parent / "resumes" / "tex"


def tex_to_text(tex):
    tex = tex.split(r"\begin{document}", 1)[-1].split(r"\end{document}", 1)[0]
    tex = re.sub(r"(?<!\\)%.*", "", tex)  # comments
    tex = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", tex)
    tex = re.sub(r"\\(textbf|textit|emph|underline|small|large|Large|scshape|bfseries)\b", "", tex)
    tex = re.sub(r"\\(section|subsection)\*?\{([^}]*)\}", r"\n\n\2\n", tex)
    tex = re.sub(r"\\item\b", "\n- ", tex)
    tex = re.sub(r"\\(\\|newline)", "\n", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", tex)  # any other command
    tex = tex.replace("{", " ").replace("}", " ").replace("$", "").replace("\\", "").replace("&", " ")
    tex = re.sub(r"\[-?[\d.]+(pt|mm|em|cm|in)\]|-?[\d.]+(pt|mm|em|cm)\b", " ", tex)  # spacing sizes
    tex = re.sub(r"\b(center|itemize|enumerate|tabular\*?|minipage|flushleft|flushright)\b", " ", tex)
    tex = tex.replace("--", "-").replace(", ,", " | ")
    tex = re.sub(r"[ \t]+", " ", tex)
    return re.sub(r"\n\s*\n+", "\n\n", tex).strip()


def load():
    return {p.stem: tex_to_text(p.read_text()) for p in sorted(TEX_DIR.glob("*.tex"))}
