from ddgs import DDGS
import textwrap

url = "https://qonto.com/en/careers"

def pretty_print(title, result, width=100):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

    # Extract only the content
    content = result.get("content", "")

    # Decode bytes if needed
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    # Wrap long lines nicely
    wrapped = textwrap.fill(content, width=width)
    print(wrapped[:20000])  # limit output

    if len(wrapped) > 20000:
        print("\n... (truncated)\n")


with DDGS() as ddgs:
    pretty_print("MARKDOWN", ddgs.extract(url))
    pretty_print("PLAIN TEXT", ddgs.extract(url, fmt="text_plain"))
    pretty_print("RICH TEXT", ddgs.extract(url, fmt="text_rich"))
    pretty_print("RAW HTML", ddgs.extract(url, fmt="text"))
    pretty_print("RAW BYTES", ddgs.extract(url, fmt="content"))