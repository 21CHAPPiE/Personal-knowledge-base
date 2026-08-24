import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

md_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "中文说明.md")

with open(md_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print("包含“智慧水利”的行:")
for line in lines:
    if "智慧水利" in line:
        print(line.strip())
