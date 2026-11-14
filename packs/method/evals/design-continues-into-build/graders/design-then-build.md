---
type: tool_order
before:
  tool: Skill
  input_match: '"skill"\s*:\s*"(?:[\w-]+:)?design"'
after:
  tool: Skill
  input_match: '"skill"\s*:\s*"(?:[\w-]+:)?build"'
---
