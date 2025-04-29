import os
import yaml
from langchain_core.prompts import PromptTemplate
from core.config_loader import load_config

# Load project configuration
_CFG = load_config()   # no args → uses project-root config.yaml

# Map of user-friendly length keys to reduction percentages
LENGTH_MAP = _CFG["chapter_summary_lengths"]
# Default length key if user provides none or invalid
DEFAULT_LENGTH = _CFG.get("default_summary_length", "short")


def get_map_prompt(summary_length_key: str | None = None) -> PromptTemplate:
    """
    Returns a PromptTemplate for per-chapter summarization.
    The template adapts to genre and dynamic length bounds supplied at formatting time.

    Input variables:
      - text: the full chapter text
      - genre: 'Fiction' or 'Non-Fiction'
      - length: the user-selected key (very_short/short/medium/long)
      - length_percent: the numeric percentage (e.g. 25)
      - length_words: approximate target word count (upper bound)
      - min_length_words: approximate minimum word count (lower bound)
    """
    key = summary_length_key or DEFAULT_LENGTH
    raw_pct = LENGTH_MAP.get(key, LENGTH_MAP[DEFAULT_LENGTH])
    # strip trailing '%' if present
    if isinstance(raw_pct, str) and raw_pct.endswith('%'):
        length_pct = int(raw_pct.rstrip('%'))
    else:
        length_pct = int(raw_pct)
    # upper bound words
    # actual word count computed at runtime, placeholder here
    # min percent = max(length_pct - 10, 10)
    min_pct = max(length_pct - 10, 10)

    template = """
SYSTEM:
You are an expert literary summarization assistant. Your task is to produce an abridged version of a text that:

- Keeps the author's voice & style: where appropriate, include up to two brief verbatim excerpts (≤2 sentences each) to preserve tone.
- Preserves key content: retell crucial plot points (for fiction) or core concepts, arguments, and terminology (for non-fiction) accurately.
- Adapts to genre:
    • If Fiction: focus on narrative flow, character arcs, and memorable dialogue.
    • If Non-Fiction: emphasize definitions, evidence, logical structure, and data.
- **Length Constraints:** Your summary must be at least {min_length_words} words and must not exceed {length_words} words.

USER:
Genre: **{genre}**  
Desired length: **{length}**  
Allowed range: **{min_length_words}–{length_words} words**  
Approximate ratio: **{length_percent}%** (upper bound)

**Input Text:**
```text
{text}
```

**Output:**
Deliver only the abridged text—strictly between the given word limits, without headers or disclaimers.
"""
    return PromptTemplate(
        template=template,
        input_variables=[
            "text", "genre", "length", "length_percent", "length_words", "min_length_words"
        ]
    )

# Combine chapters into a single narrative
combine_template_string = """
You are an expert literary editor tasked with assembling a coherent and engaging narrative from a series of abridged book chapters.
Your goal is to synthesize these summaries into a single, flowing text that represents the core story of the book.

**Instructions:**

1.  **Synthesize Coherently:** Combine the provided abridged chapter summaries into a unified narrative. Ensure smooth transitions between the content from different chapters.
2.  **Maintain Consistency:** Preserve a consistent narrative voice, tone, and style throughout the combined text, reflecting the original author's intent as represented in the summaries.
3.  **Refine for Flow:** Read through the combined text and make minor edits if necessary to improve readability, eliminate redundancy, and ensure logical progression of the story.
4.  **Final Output:** Produce the final, combined abridged text. Do not add extra commentary, introductions, or conclusions beyond what is present in the summaries.

**Input Abridged Chapter Summaries:**
```text
{text}
```

**Output:**
Provide the final, synthesized abridged text based on the instructions above. Output only the combined text.

**Final Abridged Text:**
"""

COMBINE_PROMPT = PromptTemplate(
    template=combine_template_string,
    input_variables=["text"]
)

# Overall book summary prompt (genre-agnostic)
overall_summary_template_string = """
You are an expert literary critic tasked with writing a concise summary of a book based on its chapter summaries.
Your goal is to provide a high-level overview of the book's main plot, themes, and conclusions.

**Instructions:**

1.  **Identify Core Narrative:** Read through the provided chapter summaries and identify the main storyline, key characters, central conflicts, and major turning points.
2.  **Extract Key Themes:** Determine the primary themes or messages conveyed throughout the summaries.
3.  **Synthesize Concisely:** Write a brief, coherent summary (e.g., 4-6 paragraphs) that captures the essence of the book as represented by the chapter summaries. Focus on the overall picture, not granular chapter details.
4.  **Maintain Neutral Tone:** Present the summary objectively.
5.  **Final Output:** Produce only the final book summary text, without any introductory phrases like "Here is the book summary:.".

**Input Chapter Summaries (Concatenated):**
```text
{text}
```

**Output:**
Provide the overall book summary based on the instructions above.

**Book Summary:**
"""

OVERALL_SUMMARY_PROMPT = PromptTemplate(
    template=overall_summary_template_string,
    input_variables=["text"]
)

# Fallback one-paragraph prompt
early_fallback_template = """
SYSTEM:
You are a helpful summarization assistant. Summarize the following chapter text in one concise paragraph.

USER:
```text
{text}
```

OUTPUT:
Provide only the one-paragraph summary.
"""

FALLBACK_PROMPT = PromptTemplate(
    template=early_fallback_template,
    input_variables=["text"]
)
