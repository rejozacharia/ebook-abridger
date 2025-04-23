from langchain_core.prompts import PromptTemplate

# --- Map Prompt Template ---
# This prompt is applied to each chapter individually.

map_template_string = """
You are an expert literary assistant tasked with creating an engaging abridged version of a book chapter.
Your goal is to significantly shorten the chapter while preserving its essence, narrative flow, key information, and unique character.

**Instructions:**

1.  **Summarize Concisely:** Reduce the chapter text to approximately 10-15% of its original length. Focus on the most crucial plot points, character developments, and thematic elements.
2.  **Preserve Key Elements:** Retain important dialogue, memorable anecdotes, significant descriptions, and critical events. Do not over-summarize to the point of losing the chapter's flavor or core message.
3.  **Maintain Narrative Voice:** The abridged version should reflect the original author's tone, style, and narrative perspective.
4.  **Ensure Clarity and Flow:** The resulting text must be coherent, readable, and flow logically.
5.  **Focus on this Chapter:** Primarily summarize the content provided below. While context from the overall book is useful, your main task here is to abridge *this specific chapter*.

**Input Chapter Text:**
```text
{text}
```

**Output:**
Provide the abridged version of the chapter based on the instructions above. Output only the abridged text, without any introductory phrases like "Here is the abridged version:".

**Abridged Chapter:**
"""

MAP_PROMPT = PromptTemplate(
    template=map_template_string,
    input_variables=["text"]
)


# --- Combine Prompt Template ---
# This prompt is used by the MapReduce chain to combine the individual chapter summaries.

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
*(The summaries above are concatenated results from the individual chapter abridgments)*

**Output:**
Provide the final, synthesized abridged text based on the instructions above. Output only the combined text.

**Final Abridged Text:**
"""

COMBINE_PROMPT = PromptTemplate(
    template=combine_template_string,
    input_variables=["text"]
)

# Example usage (for testing purposes)
if __name__ == '__main__':
    print("--- Map Prompt Template ---")
    print(MAP_PROMPT.format(text="This is a sample chapter text."))

    print("\n--- Combine Prompt Template ---")
    print(COMBINE_PROMPT.format(text="Summary of chapter 1.\nSummary of chapter 2."))