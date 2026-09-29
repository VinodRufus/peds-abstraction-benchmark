"""One tiny call to the pinned Gemini model. Exit 0 if quota is open, 1 if not."""
import sys
sys.path.insert(0, "src")
from common.runner import make_runner
c = make_runner("google:gemini-3.1-pro-preview").complete(
    "Reply OK.", "Say OK.", temperature=0.0, max_tokens=50)
if c.error:
    print("BLOCKED:", c.error[:160])
    sys.exit(1)
print("OPEN")
